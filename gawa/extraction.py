# Contains media type definitions, input discovery, and frame extraction

from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from PIL import Image
from gawa.config import HIDE_CMD, deps

FRAME_SUFFIXES = {".gif", ".webp", ".avif", ".apng", ".png", ".jpg", ".jpeg"}
VIDEO_SUFFIXES = {".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".ogv", ".ts", ".webm", ".wmv"}
MEDIA_FILTER = "Media (" + " ".join(f"*{suffix}" for suffix in sorted(FRAME_SUFFIXES | VIDEO_SUFFIXES)) + ")"

# Return supported images and video in the folder alphabetically
def get_frame_files(folder_path: Path) -> list[Path]:
    return sorted((path for path in folder_path.iterdir()
            if path.is_file() and path.suffix.lower() in FRAME_SUFFIXES | VIDEO_SUFFIXES),
            key=lambda path: path.name.casefold())

# Returns whether the inputs contain videos and static images in input folders
def inspect_inputs(paths: list[Path], video_suffixes: set[str]) -> tuple[bool, bool]:
    has_video = False
    has_static_frames = False
    for file_path in paths:
        if not file_path.is_dir():
            has_video = has_video or file_path.suffix.lower() in video_suffixes
            continue

        try:
            for child in file_path.iterdir():
                if not child.is_file(): continue
                suffix = child.suffix.lower()
                if suffix in video_suffixes:
                    has_video = True
                elif suffix in FRAME_SUFFIXES:
                    try:
                        with Image.open(child) as image:
                            if getattr(image, "n_frames", 1) == 1: has_static_frames = True
                    except OSError:
                        continue
                if has_video and has_static_frames: return True, True
        except OSError:
            continue
    return has_video, has_static_frames

# Extracts animation frames as individual pngs
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

            try: rate = Fraction(rate_text)
            except (ValueError, ZeroDivisionError): continue
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

    # Get animated image delays
    with Image.open(image_path) as img:
        expected_frames = getattr(img, "n_frames", 1)
        delays_ms = []
        for frame_index in range(expected_frames):
            img.seek(frame_index)
            img.load()
            delays_ms.append(int(img.info.get("duration", 100) or 100))

    # Extract animated image frames using ffmpeg if available
    # FFmpeg 9 seems to only write a single frame for every tested avif for some reason
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

    # Pillow fallback for extracting frames if extracting avif,
    # ffmpeg is unavailable, or it fails for some reason
    shutil.rmtree(frame_dir)
    frame_dir.mkdir()
    delays_ms = []
    with Image.open(image_path) as img:
        for frame_index in range(getattr(img, "n_frames", 1)):
            img.seek(frame_index)
            img.convert("RGBA").save(frame_dir / f"frame_{frame_index:04d}.png", format="PNG")
            delays_ms.append(int(img.info.get("duration", 100) or 100))
    return delays_ms, "pillow"

# Load all images, animations, and videos in the folder as a png frame sequence
# Frames use "Frames fps", animations use source fps, and videos use "Video fps"
# Frames keep their native dimensions. processing.py normalizes the canvas afterwards
def load_folder_frames(folder_path: Path, frame_dir: Path, video_fps: float,
    frames_fps: float) -> tuple[list[int], str]:

    media_files = get_frame_files(folder_path)
    if not media_files: raise ValueError("The folder contains no supported image or video files.")

    frame_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in frame_dir.glob("frame_*.png"): old_frame.unlink()

    delays_ms: list[int] = []
    extractors: set[str] = set()
    frame_index = 0
    with tempfile.TemporaryDirectory(prefix="gawa-folder-", dir=frame_dir) as temp_name:
        temp_dir = Path(temp_name)
        for media_index, media_path in enumerate(media_files):
            if media_path.suffix.lower() in VIDEO_SUFFIXES:
                video_dir = temp_dir / f"video-{media_index:04d}"
                media_delays, extractor = dump_frames(media_path, video_dir, video_fps)
                extractors.add("ffmpeg" if extractor.lower().startswith("ffmpeg") else "pillow")
                delays_ms.extend(media_delays)

                for frame_path in sorted(video_dir.glob("frame_*.png")):
                    with Image.open(frame_path) as image:
                        image.convert("RGBA").save(frame_dir / f"frame_{frame_index:04d}.png", format="PNG")
                    frame_index += 1
            else:
                extractors.add("pillow")
                with Image.open(media_path) as image:
                    frame_count = getattr(image, "n_frames", 1)
                    for media_frame_index in range(frame_count):
                        image.seek(media_frame_index)
                        image.load()
                        image.convert("RGBA").save(frame_dir / f"frame_{frame_index:04d}.png", format="PNG")
                        frame_index += 1
                        delay = int(image.info.get("duration", 100) or 100)
                        delays_ms.append(max(1, round(1000 / frames_fps)) if frame_count == 1 else delay)

    extractor_names = " and ".join(tool for tool in ("pillow", "ffmpeg") if tool in extractors)
    return delays_ms, extractor_names
