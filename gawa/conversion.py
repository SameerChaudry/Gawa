# Conversion data types, the frame cache, and the per-input conversion worker

from __future__ import annotations
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal
from gawa.config import Options, deps
from gawa.extraction import dump_frames, get_frame_files, load_folder_frames
from gawa.processing import adjust_delays, assemble_frames, normalize_frame_sequence, unique_output_path

CacheKey = tuple[object, ...]

# Stores all the information the worker needs to convert an input
@dataclass(frozen=True)
class ConversionSnapshot:
    image_paths: tuple[Path, ...]
    des_format: str
    quality: int
    options: Options
    output_dir: Path
    video_fps: float
    frames_fps: float

# Tracks the jobs, progress, and failures of one conversion run
@dataclass
class ConversionBatch:
    jobs: list[ConversionSnapshot]
    from_queue: bool
    index: int = 0
    failures: list[str] = field(default_factory=list)

# Metadata for one source's cached raw and normalized frame directories
@dataclass
class _CachedSource:
    input_name: str
    delays: list[int]
    extractor: str
    normalized_settings: tuple[object, ...] | None = None
    normalized_tools: set[str] | None = None

# Caches raw and normalized frames between queued conversions
class FrameCache:
    def __init__(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="gawa-cache-")
        self._root = Path(self._temporary_directory.name)
        self._entries: dict[CacheKey, _CachedSource] = {}
        self._next_input_id = 0

    # Generates a unique key for source frames based on input path, file sizes, and metadata
    @staticmethod
    def source_key(image_path: Path, video_fps: float, frames_fps: float) -> CacheKey | None:
        try:
            input_paths = get_frame_files(image_path) if image_path.is_dir() else [image_path]
            signatures = []
            for path in input_paths:
                stat = path.stat()
                signatures.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except OSError: return None

        return (str(image_path.resolve()), tuple(signatures), video_fps, frames_fps)

    # Copies exactly one frame sequence into an empty or stale working directory
    @staticmethod
    def _copy_frames(source_dir: Path, destination_dir: Path, expected_count: int) -> bool:
        frames = sorted(source_dir.glob("frame_*.png"))
        if len(frames) != expected_count: return False

        destination_dir.mkdir(parents=True, exist_ok=True)
        for old_frame in destination_dir.glob("frame_*.png"): old_frame.unlink()
        for index, frame_path in enumerate(frames):
            shutil.copy2(frame_path, destination_dir / f"frame_{index:04d}.png")
        return True

    # Returns (delays, extractor, normalization tools). tools is None when only raw frames were cached
    def restore(self, key: CacheKey | None, settings: tuple[object, ...], frame_dir: Path) -> tuple[list[int], str, set[str] | None] | None:
        if key is None: return None
        entry = self._entries.get(key)
        if entry is None: return None

        if entry.normalized_settings == settings and entry.normalized_tools is not None:
            normalized_dir = self._root / "normalized" / entry.input_name
            if self._copy_frames(normalized_dir, frame_dir, len(entry.delays)):
                return list(entry.delays), entry.extractor, set(entry.normalized_tools)
            entry.normalized_settings = None
            entry.normalized_tools = None

        raw_dir = self._root / "raw" / entry.input_name
        if self._copy_frames(raw_dir, frame_dir, len(entry.delays)):
            return list(entry.delays), entry.extractor, None
        self._entries.pop(key, None)
        return None

    def save_raw(self, key: CacheKey | None, frame_dir: Path, delays: list[int], extractor: str) -> None:
        if key is None or key in self._entries: return
        input_name = f"input-{self._next_input_id:08d}"
        if not self._copy_frames(frame_dir, self._root / "raw" / input_name, len(delays)): return
        self._next_input_id += 1
        self._entries[key] = _CachedSource(input_name, list(delays), extractor)

    def save_normalized(self, key: CacheKey | None, settings: tuple[object, ...], frame_dir: Path, tools: set[str]) -> None:
        if key is None or not tools: return
        entry = self._entries.get(key)
        if entry is None: return
        if not self._copy_frames(frame_dir, self._root / "normalized" / entry.input_name, len(entry.delays)): return
        entry.normalized_settings = settings
        entry.normalized_tools = set(tools)

    def close(self) -> None: self._temporary_directory.cleanup()

# Runs the conversion loop in a separate thread to avoid locking up the main thread
class ConversionWorker(QThread):
    log_message = Signal(str)

    def __init__(self, snapshot: ConversionSnapshot, parent: QObject | None = None, frame_cache: FrameCache | None = None) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.frame_cache = frame_cache
        self.failures: list[str] = []

    # Extracts, caches, normalizes, and adjusts delays for one input
    def _prepare_frames(self, image_path: Path, frame_dir: Path) -> list[int]:
        snapshot = self.snapshot
        options = snapshot.options
        resize_size = ((int(options["resize_width"]), int(options["resize_height"]))
            if options["resize_enabled"] else None)

        fit_to_canvas = bool(options["fit_to_canvas"])
        center_frames = bool(options["center_frames"])
        normalization_key = (resize_size, fit_to_canvas, center_frames)
        cache = self.frame_cache
        source_key = (cache.source_key(image_path, snapshot.video_fps, snapshot.frames_fps)
            if cache is not None else None)

        started = time.perf_counter()
        cached = cache.restore(source_key, normalization_key, frame_dir) if cache is not None else None
        if cached is None:
            if image_path.is_dir():
                delays, extractor = load_folder_frames(image_path, frame_dir,
                    snapshot.video_fps, snapshot.frames_fps)
            else: delays, extractor = dump_frames(image_path, frame_dir, snapshot.video_fps)

            extraction_seconds = time.perf_counter() - started
            if cache is not None: cache.save_raw(source_key, frame_dir, delays, extractor)
            self.log_message.emit(f"Extracted {len(delays)} raw frames using {extractor} in {extraction_seconds:.2f}s")
            tools = None
        else:
            delays, _, tools = cached
            frame_kind = "normalized" if tools is not None else "raw"
            self.log_message.emit(f"Reused {frame_kind} frames for {image_path.name} in {time.perf_counter() - started:.2f}s")

        if tools is None:
            started = time.perf_counter()
            tools = normalize_frame_sequence(frame_dir, len(delays),
                resize_size, fit_to_canvas, center_frames, deps["ffmpeg"])
            normalization_seconds = time.perf_counter() - started
            if cache is not None:
                cache.save_normalized(source_key, normalization_key, frame_dir, tools)
            if tools:
                tools_text = " and ".join(
                    "Pillow" if tool == "pillow" else "FFmpeg"
                    for tool in ("pillow", "ffmpeg") if tool in tools)
                self.log_message.emit(f"Normalized frames using {tools_text} in {normalization_seconds:.2f}s")

        delays = adjust_delays(delays, options)
        minimum_delay = 20 if snapshot.des_format == "gif" else 11
        low_delays = sum(delay < minimum_delay for delay in delays)
        if low_delays: self.log_message.emit(
                f"Warning: Found {low_delays} frame delay(s) below {minimum_delay} ms. "
                f"This may cause inconsistent behavior when playing back the {snapshot.des_format}")
        return delays

    # Iterates over all inputs to extract frames and encode them as the selected image format
    def run(self) -> None:
        snapshot = self.snapshot
        output_extension = "png" if snapshot.des_format == "apng" else snapshot.des_format
        reserved_outputs: set[Path] = set()

        for index, image_path in enumerate(snapshot.image_paths, start=1):
            # Checks if the user tried to close the app window during conversion
            # and closes it after the currently running conversion
            if self.isInterruptionRequested():
                self.log_message.emit("Conversion cancelled.")
                break

            # Renames inputs with same name to avoid silent overwrites
            output_path = unique_output_path(
                snapshot.output_dir, image_path.name if image_path.is_dir()
                else image_path.stem, output_extension, reserved_outputs)
            self.log_message.emit(f"[{index}/{len(snapshot.image_paths)}] Extracting {image_path.name}")

            try:
                with tempfile.TemporaryDirectory(prefix="gawa-frames-") as temp_dir:
                    frame_dir = Path(temp_dir)
                    delays = self._prepare_frames(image_path, frame_dir)
                    self.log_message.emit(f"Encoding {image_path.name}")

                    # Encodes the selected image format using the extracted png frames
                    encoding_started = time.perf_counter()
                    encoder = assemble_frames(snapshot.des_format, snapshot.quality, delays,
                        output_path, snapshot.options, frame_dir, self.log_message.emit)
                    encoding_seconds = time.perf_counter() - encoding_started
                    output_size = output_path.stat().st_size
                    self.log_message.emit(f"Saved to {output_path} using {encoder} in {encoding_seconds:.2f}s ({output_size / 1_048_576:.2f} MiB)")

            except Exception as error:
                failure = f"{image_path.name}: {error}"
                self.failures.append(failure)
                self.log_message.emit(f"Failed {failure}")

        if not self.failures and not self.isInterruptionRequested():
            self.log_message.emit("Conversion complete.")
