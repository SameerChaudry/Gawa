# Native file/folder selection. Uses xdg portal on linux and 
# native explorer.exe on windows with a Qt fallback for both

from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtCore import SLOT, QEventLoop, QObject, QUrl, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from gawa.extraction import MEDIA_FILTER, get_frame_files

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
