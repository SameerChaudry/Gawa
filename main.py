# The app is split into just main.py, qt_ui, and media_io.py
# main.py handles the backend, qt_ui handles the gui, and
# media_io.py handles the file/folder imports and dbus implementation

from __future__ import annotations
import subprocess
import shutil
import sys
import json
import tempfile
import statistics
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, cast
from PIL import Image
from pathlib import Path
from PySide6.QtCore import QEvent, QObject, QSettings, QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from qt_ui import Ui_MainWindow
from media_io import (FRAME_SUFFIXES, VIDEO_SUFFIXES, choose_files,choose_frame_folder,
    choose_output_folder, get_frame_files, load_folder_frames)

deps = {
    "gifski":   shutil.which("gifski") is not None,
    "apngasm":  shutil.which("apngasm") is not None,
    "ffmpeg":   shutil.which("ffmpeg") is not None,
    "ffprobe":  shutil.which("ffprobe") is not None,
}

HIDE_CMD = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

@dataclass(frozen=True)
class ConversionSnapshot:
    image_paths: tuple[Path, ...]
    des_format: str
    quality: int
    options: dict[str, bool | int | float | str]
    output_dir: Path
    video_fps: float
    frames_fps: float

class FrameCache:
    def __init__(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="gawa-cache-")
        self.root = Path(self._temporary_directory.name)
        self.raw_dir = self.root / "raw"
        self.normalized_dir = self.root / "normalized"
        self.raw_dir.mkdir()
        self.normalized_dir.mkdir()
        self.entries: dict[tuple[Any, ...], tuple[str, list[int], str]] = {}
        self.normalized_entries: dict[tuple[Any, ...], tuple[tuple[Any, ...], int, set[str]]] = {}
        self._next_input_id = 0

    @staticmethod
    def make_source_key(image_path: Path, video_fps: float, frames_fps: float) -> tuple[Any, ...] | None:
        try:
            input_paths = get_frame_files(image_path) if image_path.is_dir() else [image_path]
            signatures = []
            for path in input_paths:
                stat = path.stat()
                signatures.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except OSError:
            return None

        return (str(image_path.resolve()), tuple(signatures), video_fps, frames_fps)

    @staticmethod
    def _copy_to_working(frames: list[Path], frame_dir: Path) -> bool:
        if not frames:
            return False
        for index, frame_path in enumerate(frames):
            shutil.copy2(frame_path, frame_dir / f"frame_{index:04d}.png")
        return True

    def restore_raw(self, key: tuple[Any, ...] | None, frame_dir: Path) -> tuple[list[int], str] | None:
        if key is None or key not in self.entries:
            return None
        input_name, delays, extractor = self.entries[key]
        raw_input_dir = self.raw_dir / input_name
        frames = sorted(raw_input_dir.glob("frame_*.png"))
        if len(frames) != len(delays) or not self._copy_to_working(frames, frame_dir):
            self.entries.pop(key, None)
            return None
        return list(delays), extractor

    def store_raw(self, key: tuple[Any, ...] | None, frame_dir: Path, delays: list[int], extractor: str) -> None:
        if key is None:
            return
        if key in self.entries:
            return
        input_name = f"input-{self._next_input_id:08d}"
        self._next_input_id += 1
        frames = sorted(frame_dir.glob("frame_*.png"))
        if len(frames) != len(delays):
            return
        raw_input_dir = self.raw_dir / input_name
        raw_input_dir.mkdir()
        for index, frame_path in enumerate(frames):
            shutil.copy2(frame_path, raw_input_dir / f"frame_{index:04d}.png")
        self.entries[key] = (input_name, list(delays), extractor)

    def restore_normalized(self, key: tuple[Any, ...] | None, settings: tuple[Any, ...],
    frame_dir: Path) -> set[str] | None:
        if key is None or key not in self.normalized_entries:
            return None
        cached_settings, frame_count, tools = self.normalized_entries[key]
        if cached_settings != settings:
            return None
        input_name = self.entries[key][0]
        normalized_input_dir = self.normalized_dir / input_name
        frames = sorted(normalized_input_dir.glob("frame_*.png"))
        if len(frames) != frame_count:
            self.normalized_entries.pop(key, None)
            return None
        for raw_frame in frame_dir.glob("frame_*.png"):
            raw_frame.unlink()
        if not self._copy_to_working(frames, frame_dir):
            self.normalized_entries.pop(key, None)
            return None
        return set(tools)

    def store_normalized(self, key: tuple[Any, ...] | None, settings: tuple[Any, ...],
    frame_dir: Path, frame_count: int, tools: set[str]) -> None:
        if key is None or not tools:
            return
        frames = sorted(frame_dir.glob("frame_*.png"))
        if len(frames) != frame_count:
            return
        input_name = self.entries[key][0]
        normalized_input_dir = self.normalized_dir / input_name
        normalized_input_dir.mkdir(parents=True, exist_ok=True)
        for old_frame in normalized_input_dir.glob("frame_*.png"):
            old_frame.unlink()
        for index, frame_path in enumerate(frames):
            shutil.copy2(frame_path, normalized_input_dir / f"frame_{index:04d}.png")
        self.normalized_entries[key] = (settings, frame_count, set(tools))

    def close(self) -> None:
        self._temporary_directory.cleanup()

# Runs the conversion loop in a separate thread to avoid locking up the main thread
class ConversionWorker(QThread):
    log_message = Signal(str)

    def __init__(self, image_paths: list[Path], des_format: str, quality: int, options: dict[str, bool | int | float | str],
        output_dir: Path, video_fps: float, frames_fps: float, parent: QObject | None = None,
        frame_cache: FrameCache | None = None) -> None:

        super().__init__(parent)
        self.image_paths = image_paths
        self.des_format = des_format
        self.quality = quality
        self.options = options
        self.output_dir = output_dir
        self.video_fps = video_fps
        self.frames_fps = frames_fps
        self.frame_cache = frame_cache
        self.failures: list[str] = []

    def run(self) -> None:
        output_extension = "png" if self.des_format == "apng" else self.des_format
        reserved_outputs: set[Path] = set()

        # Iterates over all inputs to extract frames and encode them as the selected image format
        for index, image_path in enumerate(self.image_paths, start=1):
            if self.isInterruptionRequested():
                self.log_message.emit("Conversion cancelled.")
                break

            # Renames inputs with same name to avoid silent overwrites
            output_path = MainWindow.unique_output_path(
                self.output_dir, image_path.name if image_path.is_dir() else image_path.stem, output_extension, reserved_outputs)
            self.log_message.emit(f"[{index}/{len(self.image_paths)}] Extracting {image_path.name}")

            # Extracts image frames using pillow and video frames using ffmpeg and ffprobe (if available in PATH)
            try:
                with tempfile.TemporaryDirectory(prefix="gawa-frames-") as temp_dir:
                    frame_dir = Path(temp_dir)
                    extraction_started = time.perf_counter()
                    resize = self.options["resize_enabled"]
                    resize_size = None
                    if resize:
                        resize_size = (int(self.options["resize_width"]), int(self.options["resize_height"]))
                    fit_to_canvas = bool(self.options["fit_to_canvas"])
                    center_frames = bool(self.options["center_frames"])
                    resize_active = resize_size is not None and resize_size != (0, 0)
                    source_key = FrameCache.make_source_key(image_path, self.video_fps, self.frames_fps)
                    raw_frames = self.frame_cache.restore_raw(source_key, frame_dir) if self.frame_cache is not None else None
                    if raw_frames is not None:
                        delays, extracter = raw_frames
                        extraction_seconds = time.perf_counter() - extraction_started
                        self.log_message.emit(f"Reused raw frames for {image_path.name} in {extraction_seconds:.2f}s")
                    else:
                        if image_path.is_dir():
                            delays, extracter = load_folder_frames(
                                image_path, frame_dir, self.video_fps, self.frames_fps, MainWindow.dump_frames,
                                preserve_frame_sizes=True)
                        else:
                            delays, extracter = MainWindow.dump_frames(image_path, frame_dir, self.video_fps)
                        extraction_seconds = time.perf_counter() - extraction_started
                        if self.frame_cache is not None:
                            self.frame_cache.store_raw(source_key, frame_dir, delays, extracter)
                        self.log_message.emit(f"Extracted {len(delays)} raw frames using {extracter} in {extraction_seconds:.2f}s")

                    normalization_key = (resize_size, fit_to_canvas, center_frames)
                    normalization_started = time.perf_counter()
                    normalization_tools = self.frame_cache.restore_normalized(
                        source_key, normalization_key, frame_dir) if self.frame_cache is not None else None
                    if normalization_tools is not None:
                        normalization_seconds = time.perf_counter() - normalization_started
                        self.log_message.emit(f"Reused normalized frames for {image_path.name} in {normalization_seconds:.2f}s")
                    else:
                        normalization_tools = MainWindow.normalize_frame_sequence(
                            frame_dir, len(delays), resize_size, fit_to_canvas, center_frames, deps["ffmpeg"])
                        normalization_seconds = time.perf_counter() - normalization_started
                        if self.frame_cache is not None:
                            self.frame_cache.store_normalized(source_key, normalization_key,
                                frame_dir, len(delays), normalization_tools)
                        if normalization_tools:
                            normalization_text = " and ".join(
                                tool.capitalize() if tool == "pillow" else "FFmpeg"
                                for tool in ("pillow", "ffmpeg") if tool in normalization_tools)
                            self.log_message.emit(f"Normalized frames using {normalization_text} in {normalization_seconds:.2f}s")

                    delays = MainWindow.adjust_delays(delays, self.options)

                    if self.des_format == "gif":
                        low_delays = sum(delay < 20 for delay in delays)
                        if low_delays: self.log_message.emit(f"Warning: Found {low_delays} frame delay(s) below 20 ms. This may cause inconsistent behavior when playing back the gif")
                    elif self.des_format != "gif":
                        low_delays = sum(delay < 11 for delay in delays)
                        if low_delays: self.log_message.emit(f"Warning: Found {low_delays} frame delay(s) below 11 ms. This may cause inconsistent behavior when playing back the {self.des_format}")
                    self.log_message.emit(f"Encoding {image_path.name}")

                    # Encodes the selected image format using the extracted png frames
                    encoding_started = time.perf_counter()
                    encoder = MainWindow.assemble_frames(self.des_format, self.quality, delays,
                        output_path, self.options, frame_dir, self.log_message.emit)
                    encoding_seconds = time.perf_counter() - encoding_started
                    output_size = output_path.stat().st_size
                    self.log_message.emit(f"Saved to {output_path} using {encoder} in {encoding_seconds:.2f}s ({output_size / 1_048_576:.2f} MiB)")

            except Exception as error:
                failure = f"{image_path.name}: {error}"
                self.failures.append(failure)
                self.log_message.emit(f"Failed {failure}")

        if not self.failures and not self.isInterruptionRequested():
            self.log_message.emit("Conversion complete.")

class MainWindow(QMainWindow, Ui_MainWindow):
    log_message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.setAcceptDrops(True)
        self.set_video_suffixes(VIDEO_SUFFIXES)
        self.settings = QSettings("Gawa", "Gawa")
        saved_output_dir = cast(str, self.settings.value("output_dir", "", type=str))
        saved_path = Path(saved_output_dir).expanduser() if saved_output_dir else None
        self.output_dir = saved_path if saved_path is not None and saved_path.is_dir() else None
        self.worker: ConversionWorker | None = None
        self.conversion_queue: list[ConversionSnapshot] = []
        self._active_jobs: list[ConversionSnapshot] = []
        self._active_job_index = 0
        self._active_is_queue = False
        self._active_failures: list[str] = []
        self.frame_cache = FrameCache()

        if self.output_dir is not None:
            self.output_folder_button.setText(self.output_dir.name or str(self.output_dir))
            self.output_folder_button.setToolTip(str(self.output_dir))

        # underscore assignment just tells basedpyright that the returned connection object is useless
        _ = self.log_message.connect(self.log_output.appendPlainText)
        _ = self.add_folder_button.clicked.connect(self.on_add_folder_clicked)
        _ = self.add_files_button.clicked.connect(self.on_add_files_clicked)
        _ = self.remove_all_button.clicked.connect(self.on_remove_all_clicked)
        _ = self.make_convert_button.clicked.connect(self.on_make_convert_clicked)
        _ = self.add_to_queue_action.triggered.connect(self.on_add_to_queue_clicked)
        _ = self.clear_queue_action.triggered.connect(self.on_clear_queue_clicked)
        _ = self.format_dropdown.currentTextChanged.connect(self.on_format_changed)
        _ = self.sidebar.benchmarks_button.clicked.connect(self.on_benchmarks_clicked)
        _ = self.output_folder_button.clicked.connect(self.on_choose_output_folder_clicked)

        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        _ = self.delete_shortcut.activated.connect(self.image_grid.remove_selected)
        self.backspace_shortcut = QShortcut(QKeySequence("Backspace"), self)
        self.backspace_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        _ = self.backspace_shortcut.activated.connect(self.image_grid.remove_selected)
        self.on_format_changed(self.format_dropdown.currentText())

    def on_add_files_clicked(self) -> None:
        for file_path in choose_files(self):
            self.image_grid.add_image(file_path)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DragEnter:
            drag_event = cast(QDragEnterEvent, event)
            if drag_event.mimeData().hasUrls() and any(url.isLocalFile() for url in drag_event.mimeData().urls()):
                drag_event.acceptProposedAction()
                return True

        elif event.type() == QEvent.Type.Drop:
            drop_event = cast(QDropEvent, event)
            paths = [url.toLocalFile() for url in drop_event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.import_startup_paths(paths)
                drop_event.acceptProposedAction()
                return True
                
        return super().event(event)

    # Import files/folders passed from the command line when launching
    def import_startup_paths(self, paths: list[str]) -> None:
        for argument in paths:
            path = Path(argument).expanduser()
            if path.is_dir():
                try:
                    if get_frame_files(path): self.image_grid.add_folder(path)
                    else: self.log_message.emit(f"Skipped folder with no supported media: {path}")
                except OSError as error: self.log_message.emit(f"Could not read folder {path}: {error}")

            elif path.is_file() and path.suffix.lower() in FRAME_SUFFIXES | VIDEO_SUFFIXES:
                self.image_grid.add_image(path)
                self.log_message.emit(f"Imported: {path}")
            else: self.log_message.emit(f"Skipped unsupported or missing path: {path}")

    def on_add_folder_clicked(self) -> None:
        folder = choose_frame_folder(self)
        if folder is not None: self.image_grid.add_folder(folder)

    def on_remove_all_clicked(self) -> None:
        self.image_grid.remove_all()

    # Tries to use the native file dialog portal via DBus for linux and
    # falls back to native qt file dialog on failure, cancel or on Windows
    def on_choose_output_folder_clicked(self) -> None:
        folder = choose_output_folder(self, str(self.output_dir or Path.home()))
        if folder is None: return

        self.output_dir = folder
        self.settings.setValue("output_dir", str(self.output_dir))
        self.output_folder_button.setText(self.output_dir.name or str(self.output_dir))
        self.output_folder_button.setToolTip(str(self.output_dir))

    # Rebuilds the sidebar to show different configuration options when the selected format changes
    def on_format_changed(self, format_name: str) -> None:
        self.sidebar.rebuild(format_name.lower(), deps)

    def on_benchmarks_clicked(self) -> None:
        des_format = self.format_dropdown.currentText().lower()
        self.log_message.emit("These are just the results from testing 263 254x450 png frames of a flat color animation using different encoding options for each of the 4 formats. Don't take these too literally as these are provided just for reference, because different encoders support different inputs, work better for specific kinds of content, have certain limitations, etc")
        if des_format == "gif":
            self.log_message.emit("""GIF Benchmarks
Encoder  Quality  Speed    Time    Size     Min VMAF  Mean VMAF  Features
Pillow   n/a      n/a      1.27 s  7.60 MB  94.70     99.57      Global color table made by sampling 66 frames of the animation; no dithering; disposal=2
Pillow   n/a      n/a      0.87 s  4.04 MB  94.81     99.14      Local color table (default); disposal=2
gifski   80       --fast   6.91 s  4.51 MB  95.68     99.40      --fast
gifski   80       default  8.41 s  4.42 MB  95.58     99.40      Default
gifski   80       --extra  14.56 s 4.33 MB  94.83     99.35      --extra
ffmpeg   n/a      n/a      1.03 s  6.90 MB  96.55     99.61      palettegen=stats_mode=diff + paletteuse=dither=none
ffmpeg   n/a      n/a      2.28 s  7.95 MB  96.39     99.55      palettegen=stats_mode=diff + paletteuse=dither=sierra2_4a""")
        elif des_format == "apng":
            self.log_message.emit("""APNG Benchmarks
Encoder  Quality   Speed       Time     Size       Min VMAF  Mean VMAF  Features
Pillow   lossless  compress=0  1.21 s   120.42 MB  97.43     99.77      Disposal=background; blend=source
Pillow   lossless  compress=6  3.26 s   16.99 MB   97.43     99.77      Disposal=background; blend=source
Pillow   lossless  compress=9  12.62 s  16.76 MB   97.43     99.77      Disposal=background; blend=source
apngasm  lossless  default     25.00 s  14.18 MB   97.43     99.77      Default settings""")
        elif des_format == "webp":
            self.log_message.emit("""WebP Benchmarks
Encoder   Quality  Speed  Time     Size     Min VMAF  Mean VMAF  Features
Pillow    80       0      1.45 s   2.72 MB  95.16     99.31      Lossy
Pillow    80       4      3.63 s   1.94 MB  95.10     99.29      Lossy
Pillow    80       6      81.84 s  1.93 MB  95.19     99.37      Lossy
Pillow    80       4      3.63 s   1.94 MB  95.10     99.29      Lossy, exact=True

Note: The exact=true result is identical to exact=false (default) because the tested animation was opaque with no transparent pixels, and exact=true only affects images with fully transparent pixels""")
        elif des_format == "avif":
            self.log_message.emit("""AVIF Benchmarks
Encoder  Quality  Speed  Time       Size       Min VMAF  Mean VMAF  Features
Pillow   80       10     2.73 s     1.99 MB    94.06     99.37      libaom
Pillow   80       7      3.74 s     1.91 MB    95.49     99.47      libaom
Pillow   80       6      57.41 s    1.34 MB    94.82     99.37      libaom
Pillow   80       5      93.33 s    1.31 MB    95.04     99.39      libaom
Pillow   80       3      165.40 s   1.28 MB    95.08     99.37      libaom
Pillow   80       1      1131.68 s  1.28 MB    95.32     99.43      libaom
ffmpeg   CRF 35   13     2.80 s     693.56 KB  91.97     97.73      libsvtav1
ffmpeg   CRF 35   10     4.22 s     617.92 KB  90.70     97.75      libsvtav1
ffmpeg   CRF 35   7      9.78 s     522.47 KB  92.16     97.88      libsvtav1
ffmpeg   CRF 35   5      24.28 s    491.25 KB  92.94     98.31      libsvtav1
ffmpeg   CRF 35   3      53.70 s    449.50 KB  93.53     98.43      libsvtav1
ffmpeg   CRF 35   1      134.37 s   438.94 KB  93.56     98.45      libsvtav1

Note: The ffmpeg method uses libsvtav1 for significantly better efficiency compared to pillow's default libaom AV1 encoder. But libsvtav1 doesn't support transparency and subsampling formats except yuv420p and yuv420p10le""")

    # Calculates an fps value using a list of delays or a custom delay value
    @staticmethod
    def get_fps(delays: list[int], options: dict[str, bool | int | float | str]) -> float:
        if options.get("delay_speed_enabled", True) and options.get("delay_speed_mode") == "Custom fps":
            return float(options["delay_speed_value"])

        valid_delays = [delay for delay in delays if delay > 0]
        if not valid_delays: valid_delays = [100]

        delay_mode = options["delay_mode"]

        if delay_mode == "Average":  delay_ms = sum(valid_delays) / len(valid_delays)
        elif delay_mode == "Mode":   delay_ms = statistics.mode(valid_delays)
        elif delay_mode == "Custom fps": return float(options["custom_fps"])
        else: raise ValueError(f"Unknown delay mode: {delay_mode}")

        return max(1.0, 1000 / max(1.0, delay_ms))

    @staticmethod
    def adjust_delays(delays: list[int], options: dict[str, bool | int | float | str]) -> list[int]:
        if not options.get("delay_speed_enabled", True): return delays
        value = float(options["delay_speed_value"])
        if options["delay_speed_mode"] == "Multiplier":
            return [max(1, round(delay * value)) for delay in delays]
        if options["delay_speed_mode"] == "Custom fps":
            if value <= 0: raise ValueError("Custom fps must be greater than zero")
            return [max(1, round((index + 1) * 1000 / value) - round(index * 1000 / value))
                for index in range(len(delays))]
        raise ValueError(f"Unknown delay adjustment mode: {options['delay_speed_mode']}")

    @staticmethod
    def get_resize_dimensions(original_size: tuple[int, int], resize_size: tuple[int, int]) -> tuple[int, int]:
        original_width, original_height = original_size
        width, height = resize_size
        if width == 0 and height == 0: return original_size
        if width == 0: width = max(1, round(original_width * height / original_height))
        elif height == 0: height = max(1, round(original_height * width / original_width))
        return width, height

    @staticmethod
    def normalize_frame_sequence(frame_dir: Path, frame_count: int, resize_size: tuple[int, int] | None,
    fit_to_canvas: bool, center_frames: bool, use_ffmpeg: bool) -> set[str]:
        frames = [frame_dir / f"frame_{index:04d}.png" for index in range(frame_count)]
        frame_sizes: list[tuple[int, int]] = []
        for frame_path in frames:
            with Image.open(frame_path) as frame:
                frame_sizes.append(frame.size)

        source_canvas = (max(width for width, _ in frame_sizes), max(height for _, height in frame_sizes))
        output_canvas = MainWindow.get_resize_dimensions(source_canvas, resize_size) if resize_size is not None else source_canvas
        if all(size == source_canvas for size in frame_sizes) and output_canvas == source_canvas:
            return set()

        composition_canvas = output_canvas if fit_to_canvas else source_canvas
        filter_chain: list[str] = []
        if fit_to_canvas:
            filter_chain.append(f"scale={output_canvas[0]}:{output_canvas[1]}:force_original_aspect_ratio=decrease")

        pad_x = "(ow-iw)/2" if center_frames else "0"
        pad_y = "(oh-ih)/2" if center_frames else "0"
        filter_chain.append(f"pad={composition_canvas[0]}:{composition_canvas[1]}:{pad_x}:{pad_y}:color=black@0")
        if composition_canvas != output_canvas:
            filter_chain.append(f"scale={output_canvas[0]}:{output_canvas[1]}")

        with tempfile.TemporaryDirectory(prefix="gawa-normalized-", dir=frame_dir) as temp_name:
            normalized_dir = Path(temp_name)
            if use_ffmpeg:
                try:
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-start_number", "0", "-i",
                        str(frame_dir / "frame_%04d.png"), "-vf", ",".join(filter_chain), "-start_number", "0",
                        str(normalized_dir / "frame_%04d.png")], check=True, capture_output=True, creationflags=HIDE_CMD)
                    normalized_frames = sorted(normalized_dir.glob("frame_*.png"))
                    if len(normalized_frames) != frame_count:
                        raise RuntimeError(f"Expected {frame_count} normalized frames, got {len(normalized_frames)}")
                    for index, frame_path in enumerate(normalized_frames):
                        shutil.move(str(frame_path), frames[index])
                    return {"ffmpeg"}
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass

            for index, frame_path in enumerate(frames):
                with Image.open(frame_path) as image:
                    frame = image.convert("RGBA")
                    if fit_to_canvas:
                        scale = min(output_canvas[0] / frame.width, output_canvas[1] / frame.height)
                        fitted_size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
                        if fitted_size != frame.size:
                            frame = frame.resize(fitted_size, Image.Resampling.LANCZOS)

                    canvas = Image.new("RGBA", composition_canvas, (0, 0, 0, 0))
                    x = (composition_canvas[0] - frame.width) // 2 if center_frames else 0
                    y = (composition_canvas[1] - frame.height) // 2 if center_frames else 0
                    canvas.paste(frame, (x, y))
                    if composition_canvas != output_canvas:
                        canvas = canvas.resize(output_canvas, Image.Resampling.LANCZOS)
                    canvas.save(frame_path, format="PNG")

        return {"pillow"}

    # Extracts animation frames as individual pngs
    @staticmethod
    def dump_frames(image_path: Path, frame_dir: Path, video_fps: float = 0) -> tuple[list[int], str]:
        if frame_dir.exists(): shutil.rmtree(frame_dir)
        frame_dir.mkdir()

        if image_path.suffix.lower() in VIDEO_SUFFIXES:
            if not deps["ffmpeg"] or not deps["ffprobe"]:
                raise ValueError("Both ffmpeg and ffprobe need to be in PATH for processing video inputs")

            # Uses ffprobe to get the source video fps
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                "-of", "json", str(image_path)], check=True, capture_output=True, text=True, creationflags=HIDE_CMD)
            streams = json.loads(probe.stdout).get("streams", [])
            if not streams: raise ValueError("No video stream was found.")

            source_fps: Fraction | None = None
            for rate_name in ("avg_frame_rate", "r_frame_rate"):
                rate_text = streams[0].get(rate_name, "")
                try:
                    rate = Fraction(rate_text)
                except (ValueError, ZeroDivisionError):
                    continue
                if rate > 0:
                    source_fps = rate
                    break

            if source_fps is None: raise ValueError("Could not determine the video's source frame rate.")
            fps = source_fps if video_fps == 0 else Fraction(str(video_fps))
            frame_dir.mkdir(exist_ok=True)

            # Uses source fps or custom fps for extracting frames
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(image_path), "-vf", f"fps={fps}", "-fps_mode", "passthrough",
                "-start_number", "0", str(frame_dir / "frame_%04d.png")], check=True, capture_output=True, creationflags=HIDE_CMD)
            extracted = sorted(frame_dir.glob("frame_*.png"))
            if not extracted: raise ValueError("No video frames were decoded.")

            frame_rate = float(fps)
            delays_ms = [max(1, round((index + 1) * 1000 / frame_rate) - round(index * 1000 / frame_rate))
                for index in range(len(extracted))]
            return delays_ms, f"ffmpeg ({frame_rate:g} fps)"

        # Get animated image delay
        with Image.open(image_path) as img:
            expected_frames = getattr(img, "n_frames", 1)
            delays_ms = []
            for frame_index in range(expected_frames):
                img.seek(frame_index)
                img.load()
                delays_ms.append(int(img.info.get("duration", 100) or 100))

        # Extract animated image frames using ffmpeg if available
        # FFmpeg 9 seemed to only write a single frame for every tested avif for some reason 
        if deps["ffmpeg"] and image_path.suffix.lower() != ".avif":
            try:
                cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(image_path), "-fps_mode", "passthrough",
                    str(frame_dir / "frame_%04d.png")]
                subprocess.run(cmd, check=True, capture_output=True, creationflags=HIDE_CMD)
                extracted = sorted(frame_dir.glob("frame_*.png"))
                if len(extracted) == expected_frames:
                    for index, frame in enumerate(extracted):
                        frame.rename(frame_dir / f"frame_{index:04d}.png")
                    return delays_ms, "ffmpeg"

            except (OSError, subprocess.SubprocessError): pass

        # Pillow fallback for extracting frames if avif or if ffmpeg fails for some reason
        shutil.rmtree(frame_dir)
        frame_dir.mkdir()
        delays_ms = []
        with Image.open(image_path) as img:
            for frame_index in range(getattr(img, "n_frames", 1)):
                img.seek(frame_index)
                img.convert("RGBA").save(frame_dir / f"frame_{frame_index:04d}.png", format="PNG")
                delays_ms.append(int(img.info.get("duration", 100) or 100))
        return delays_ms, "pillow"

    # Loads, copy, and close each image instead of keeping all frame images open as once
    @staticmethod
    def load_frames(frames: list[Path]) -> list[Image.Image]:
        loaded: list[Image.Image] = []
        for frame_path in frames:
            with Image.open(frame_path) as image:
                image.load()
                loaded.append(image.copy())
        return loaded

    # Encodes animations using a directory of frames and list of delays
    @staticmethod
    def assemble_frames(des_format: str, quality: int, delays: list[int], out_path: Path, options: dict[str, bool | int | float | str],
    frame_dir: Path, log_message: Callable[[str], None] | None = None) -> str:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frames = [frame_dir / f"frame_{i:04d}.png" for i in range(len(delays))]

        def log_fallback(encoder: str, error: Exception) -> None:
            out_path.unlink(missing_ok=True)
            if log_message is not None: log_message(f"{encoder} failed: {error}. Falling back to Pillow.")

        if(des_format == "gif"):
            if(deps["gifski"] and options["use_gifski"] and len(frames) > 1):
                fps = MainWindow.get_fps(delays, options)
                cmd = ["gifski", "--quality", str(quality), "--fps", str(fps)]
                if options["gifski_speed"] == "Fast": cmd += ["--fast"]
                elif options["gifski_speed"] == "Extra": cmd += ["--extra"]
                cmd += ["-o", str(out_path)] + frames
                try:
                    subprocess.run(cmd, check=True, creationflags=HIDE_CMD)
                    return "gifski"
                except (OSError, subprocess.SubprocessError) as error:
                    log_fallback("Gifski", error)

            elif(deps["ffmpeg"] and options["use_ffmpeg"] and len(frames) > 1):
                fps = MainWindow.get_fps(delays, options)
                input_pattern = str(frame_dir / "frame_%04d.png")
                dither = "sierra2_4a" if options["dither"] else "none"
                try:
                    subprocess.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern, "-vf","palettegen=stats_mode=diff",
                        "-update", "1", str(frame_dir / "palette.png")], check=True, creationflags=HIDE_CMD)
                    subprocess.run(['ffmpeg','-y','-framerate', str(fps),'-i', input_pattern, '-i', str(frame_dir / "palette.png"),
                        '-lavfi', f'paletteuse=dither={dither}', '-r', str(fps), str(out_path)], check=True, creationflags=HIDE_CMD)
                    return "ffmpeg"
                except (OSError, subprocess.SubprocessError) as error:
                    log_fallback("FFmpeg GIF encoder", error)

            # Use pillow for the gif encode. Uses local color table for every frame by default
            # which is not supported by both gifski and ffmpeg
            imgs = MainWindow.load_frames(frames)
            imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,  disposal=2)
            return "pillow"

        if(des_format == "apng"):
            if(deps["apngasm"] and options["use_apngasm"]):
                spec_path = frame_dir / "animation.json"
                try:
                    with spec_path.open("w", encoding="utf-8") as spec_file:
                        json.dump({"frames": [{frame_path.name: f"{delay}/1000"}
                            for frame_path, delay in zip(frames, delays)]}, spec_file)
                    cmd = ["apngasm", "-o", str(out_path), "-f", str(spec_path), "-F"]
                    subprocess.run(cmd, check=True, creationflags=HIDE_CMD)
                    return "apngasm"
                except (OSError, subprocess.SubprocessError) as error:
                    log_fallback("apngasm", error)

            imgs = MainWindow.load_frames(frames)
            imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
                disposal=1, compress_level=options["speed"])
            return "pillow"

        if(des_format == "webp"):
            imgs = MainWindow.load_frames(frames)
            webp_quality_options: dict[str, Any] = {"lossless": True} if quality == 100 else {"quality": quality}
            imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0, method=options["speed"],
                exact=options["exact"], allow_mixed=options["use_mixed"], **webp_quality_options)
            return "pillow"
            
        if(des_format == "avif"):
            speed = options["speed"]
            subsampling = str(options["subsampling"])

            if(deps["ffmpeg"] and options["use_ffmpeg"]):
                fps = MainWindow.get_fps(delays, options)
                pixel_format = subsampling
                crf = str(options["crf"])
                input_pattern = str(frame_dir / "frame_%04d.png")

                try:
                    subprocess.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern, "-vf", "scale=in_range=full:out_range=full",
                    "-c:v", "libsvtav1", "-preset", str(speed), "-crf", crf, "-pix_fmt", pixel_format, "-color_range", "2",
                    "-f", "avif", "-loop", "0", str(out_path)], check=True, creationflags=HIDE_CMD)
                    return "ffmpeg"
                except (OSError, subprocess.SubprocessError) as error:
                    log_fallback("FFmpeg AVIF encoder", error)

            imgs = MainWindow.load_frames(frames)
            imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays,
                speed=speed, subsampling=subsampling, quality=quality)
            return "pillow"
        
        else: raise ValueError(f"Invalid output format: {des_format}")

    # Use a unique filename suffix to avoid rewriting output files
    @staticmethod
    def unique_output_path(output_dir: Path, stem: str, extension: str, reserved: set[Path]) -> Path:
        candidate = output_dir / f"{stem}.{extension}"
        suffix = 1
        while candidate.exists() or candidate in reserved:
            candidate = output_dir / f"{stem}-{suffix}.{extension}"
            suffix += 1

        reserved.add(candidate)
        return candidate

    def _capture_conversion_snapshot(self) -> ConversionSnapshot | None:
        image_paths = self.image_grid.get_file_paths()
        if not image_paths: return None

        if self.output_dir is None:
            self.on_choose_output_folder_clicked()
            if self.output_dir is None: return None

        return ConversionSnapshot(
            tuple(image_paths),
            self.format_dropdown.currentText().lower(),
            self.quality_spinbox.value(),
            self.sidebar.snapshot(),
            self.output_dir,
            self.sidebar.video_fps_spinbox.value(),
            self.sidebar.frames_fps_spinbox.value(),
        )

    def on_add_to_queue_clicked(self) -> None:
        snapshot = self._capture_conversion_snapshot()
        if snapshot is None: return
        self.conversion_queue.append(snapshot)
        self.make_convert_button.setText(f"Convert ({len(self.conversion_queue)})")
        self.log_message.emit(
            f"Added queue operation {len(self.conversion_queue)}: {snapshot.des_format.upper()} "
            f"({len(snapshot.image_paths)} input(s))"
        )

    def on_clear_queue_clicked(self) -> None:
        self.conversion_queue.clear()
        self.make_convert_button.setText("Convert (0)")
        self.log_message.emit("Queue cleared.")

    def on_make_convert_clicked(self) -> None:
        queued = bool(self.conversion_queue)
        jobs = list(self.conversion_queue) if queued else []
        if not queued:
            snapshot = self._capture_conversion_snapshot()
            if snapshot is None: return
            jobs.append(snapshot)

        self._active_jobs = jobs
        self._active_job_index = 0
        self._active_is_queue = queued
        self._active_failures = []
        self.make_convert_button.setEnabled(False)
        self._start_next_conversion_job()

    def _start_next_conversion_job(self) -> None:
        snapshot = self._active_jobs[self._active_job_index]
        if self._active_is_queue:
            self.log_message.emit(
                f"Queue operation {self._active_job_index + 1}/{len(self._active_jobs)}: "
                f"{snapshot.des_format.upper()} ({len(snapshot.image_paths)} input(s))"
            )

        self.worker = ConversionWorker(
            list(snapshot.image_paths), snapshot.des_format, snapshot.quality, snapshot.options,
            snapshot.output_dir, snapshot.video_fps, snapshot.frames_fps, self, self.frame_cache,
        )
        _ = self.worker.log_message.connect(self.log_output.appendPlainText)
        _ = self.worker.finished.connect(self.on_conversion_finished)
        self.worker.start()

    def on_conversion_finished(self) -> None:
        worker = self.worker
        if worker is not None:
            for failure in worker.failures:
                if self._active_is_queue:
                    failure = f"Queue operation {self._active_job_index + 1}: {failure}"
                self._active_failures.append(failure)
        self.worker = None
        if worker is not None: worker.deleteLater()

        self._active_job_index += 1
        if self._active_job_index < len(self._active_jobs):
            self._start_next_conversion_job()
            return

        failures = self._active_failures
        self._active_jobs = []
        self._active_job_index = 0
        self._active_is_queue = False
        self._active_failures = []
        self.make_convert_button.setEnabled(True)
        if failures:
            QMessageBox.warning(self, "Some conversions failed", "The following files could not be converted:\n\n" + "\n".join(failures),)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        self.frame_cache.close()
        super().closeEvent(event)

def main(argv: list[str] | None = None) -> None:
    startup_paths = list(sys.argv[1:] if argv is None else argv)
    app = QApplication([sys.argv[0]])
    window = MainWindow()
    window.import_startup_paths(startup_paths)
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().with_name("gawa.svg"))))
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()