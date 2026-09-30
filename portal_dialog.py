# Interfaces with the native xdg portal for whichever linux distro it's running on via DBus

from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtCore import SLOT, QEventLoop, QObject, QUrl, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

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


def _choose_via_portal(title: str, *, directory: bool, multiple: bool,
    parent_window: str = "") -> tuple[bool, list[Path]] | None:

    if not sys.platform.startswith("linux"): return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected(): return None
    portal = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.FileChooser", bus)
    if not portal.isValid(): return None

    reply = portal.call("OpenFile", parent_window, title, {"directory": directory, "multiple": multiple})
    if reply.type() == QDBusMessage.MessageType.ErrorMessage: return None

    handle_path = reply.arguments()[0].path()
    waiter = _ResponseWaiter()
    connected = bus.connect("org.freedesktop.portal.Desktop", handle_path, "org.freedesktop.portal.Request",
        "Response", waiter, SLOT("on_response(uint,QVariantMap)"))  # type: ignore[arg-type]
    if not connected: return None

    waiter.loop.exec()  # blocks this call until the user picks or cancels
    if waiter.response_code != 0: return False, []  # cancelled, or the portal errored
    uris = waiter.results.get("uris")
    if not isinstance(uris, list): return False, []

    paths = [Path(QUrl(uri).toLocalFile()) for uri in uris if isinstance(uri, str)]
    return (True, paths) if paths else (False, [])

def choose_folder_via_portal(title: str, parent_window: str = "") -> Path | None:
    result = _choose_via_portal(title, directory=True, multiple=False, parent_window=parent_window)
    if result is None or not result[0] or not result[1]: return None
    return result[1][0]

def choose_files_via_portal(title: str, parent_window: str = "") -> list[Path] | None:
    result = _choose_via_portal(title, directory=False, multiple=True, parent_window=parent_window)
    if result is None: return None
    return result[1] if result[0] else []