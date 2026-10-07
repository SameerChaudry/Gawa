# Everything for picking inputs and the output folder: file dialogs (xdg portal on linux, qt fallback),
# supported media types, and loading a folder of images, animations, and videos as a png frame sequence

from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from typing import Callable
from PIL import Image
from PySide6.QtCore import SLOT, QEventLoop, QObject, QUrl, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

FRAME_SUFFIXES = {".gif", ".webp", ".avif", ".apng", ".png", ".jpg", ".jpeg"}
VIDEO_SUFFIXES = {".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".ogv", ".ts", ".webm", ".wmv"}
MEDIA_FILTER = "Media (" + " ".join(f"*{suffix}" for suffix in sorted(FRAME_SUFFIXES | VIDEO_SUFFIXES)) + ")"

class _ResponseWaiter(QObject):
    # QDBusConnection.connect() needs a real QObject slot, hence the @Slot signature
    # and the SLOT() string used to connect it below, instead of the usual .connect(func)

    def __init__(self) -> None:
        super().__init__()
        self.loop = QEventLoop()
        self.response_code: int | None = None
        self.results: dict[str, object] = {}

    @Slot("uint", "QVariantMap")
    def on_response(self, response_code: int, results: dict[str, object]) -> None:
        self.response_code = response_code
        self.results = results
        self.loop.quit()

# Returns the picked paths, [] if cancelled, or None if the portal is unavailable
def _portal_pick(title: str, directory: bool) -> list[Path] | None:
    if not sys.platform.startswith("linux"): return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected(): return None
    portal = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.FileChooser", bus)
    if not portal.isValid(): return None

    reply = portal.call("OpenFile", "", title, {"directory": directory, "multiple": not directory})
    if reply.type() == QDBusMessage.MessageType.ErrorMessage: return None

    handle_path = reply.arguments()[0].path()
    waiter = _ResponseWaiter()
    connected = bus.connect("org.freedesktop.portal.Desktop", handle_path, "org.freedesktop.portal.Request",
        "Response", waiter, SLOT("on_response(uint,QVariantMap)"))  # type: ignore[arg-type]
    if not connected: return None

    waiter.loop.exec()  # blocks this call until the user picks or cancels
    uris = waiter.results.get("uris")
    if waiter.response_code != 0 or not isinstance(uris, list): return []  # cancelled, or the portal errored
    return [Path(QUrl(uri).toLocalFile()) for uri in uris if isinstance(uri, str)]

# Tries the portal first, then falls back to the qt dialog. Returns [] if cancelled
def _pick(parent: QWidget, title: str, directory: bool, start_dir: str = "") -> list[Path]:
    paths = _portal_pick(title, directory)
    if paths is not None: return paths
    if directory:
        chosen = QFileDialog.getExistingDirectory(parent, title, start_dir)
        return [Path(chosen)] if chosen else []
    chosen_files, _ = QFileDialog.getOpenFileNames(parent, title, "", MEDIA_FILTER)
    return [Path(path_str) for path_str in chosen_files]

def choose_files(parent: QWidget) -> list[Path]:
    return _pick(parent, "Select images and videos", directory=False)

def choose_output_folder(parent: QWidget, start_dir: str) -> Path | None:
    paths = _pick(parent, "Choose output folder", directory=True, start_dir=start_dir)
    return paths[0] if paths else None

# Returns the folder only if it contains at least one supported file, otherwise warns and returns None
def choose_frame_folder(parent: QWidget) -> Path | None:
    paths = _pick(parent, "Select frame folder", directory=True, start_dir=str(Path.home()))
    if not paths: return None

    try: media_files = get_frame_files(paths[0])
    except OSError as error:
        QMessageBox.warning(parent, "Could not read folder", str(error))
        return None
    if not media_files:
        QMessageBox.warning(parent, "No media found", "The selected folder does not contain any supported image or video files.")
        return None
    return paths[0]

# Return supported images and video in the folder alphabetically
def get_frame_files(folder_path: Path) -> list[Path]:
    return sorted((path for path in folder_path.iterdir()
            if path.is_file() and path.suffix.lower() in FRAME_SUFFIXES | VIDEO_SUFFIXES),
            key=lambda path: path.name.casefold())

# Load all images, animations, and videos in the folder as a png frame sequence
# Frames use "Frames fps", animations use source fps, and videos use "Video fps"
# Frames are padded with transparency to fill the maximum width and height if needed
def load_folder_frames(folder_path: Path, frame_dir: Path, video_fps: float, frames_fps: float,
    dump_frames: Callable[[Path, Path, float], tuple[list[int], str]]) -> tuple[list[int], str]:

    media_files = get_frame_files(folder_path)
    if not media_files: raise ValueError("The folder contains no supported image or video files.")

    frame_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in frame_dir.glob("frame_*.png"): old_frame.unlink()

    max_width = 0
    max_height = 0
    ordered_frames: list[Path] = []
    delays_ms: list[int] = []
    with tempfile.TemporaryDirectory(prefix="gawa-folder-", dir=frame_dir) as temp_name:
        temp_dir = Path(temp_name)
        for media_index, media_path in enumerate(media_files):
            if media_path.suffix.lower() in VIDEO_SUFFIXES:
                video_dir = temp_dir / f"video-{media_index:04d}"
                media_delays, _ = dump_frames(media_path, video_dir, video_fps)
                frames = sorted(video_dir.glob("frame_*.png"))
            else:
                frames = []
                media_delays = []
                with Image.open(media_path) as image:
                    frame_count = getattr(image, "n_frames", 1)
                    for frame_index in range(frame_count):
                        image.seek(frame_index)
                        image.load()
                        frame_path = temp_dir / f"image-{media_index:04d}-{frame_index:06d}.png"
                        image.convert("RGBA").save(frame_path, format="PNG")
                        frames.append(frame_path)
                        delay = int(image.info.get("duration", 100) or 100)
                        media_delays.append(max(1, round(1000 / frames_fps)) if frame_count == 1 else delay)

            for frame_path in frames:
                with Image.open(frame_path) as image:
                    max_width = max(max_width, image.width)
                    max_height = max(max_height, image.height)
            ordered_frames.extend(frames)
            delays_ms.extend(media_delays)

        for frame_index, frame_path in enumerate(ordered_frames):
            with Image.open(frame_path) as image:
                canvas = Image.new("RGBA", (max_width, max_height), (0, 0, 0, 0))
                canvas.paste(image.convert("RGBA"), (0, 0))
                canvas.save(frame_dir / f"frame_{frame_index:04d}.png", format="PNG")

    return delays_ms, "folder media (alphabetical order)"
