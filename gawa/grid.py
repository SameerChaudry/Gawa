# Thumbnail preview helpers, the thumbnail grid, and the scroll area

from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import override
from PIL import Image
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QStyle, QVBoxLayout, QWidget
from gawa.config import FFMPEG_PATH, FFPROBE_PATH, HIDE_CMD

THUMBNAIL_SIZE = 120
CELL_SPACING = 12
MIN_COLUMNS = 1

# Decode a frame at 5% of the the video's duration
def load_video_preview_image(file_path: Path) -> QImage:
    if FFMPEG_PATH is None or FFPROBE_PATH is None: return QImage()

    probe = subprocess.run([FFPROBE_PATH, "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration:stream=duration",
        "-of", "json", str(file_path)], check=True, capture_output=True, text=True, creationflags=HIDE_CMD)
    probe_data = json.loads(probe.stdout)
    duration_values = [probe_data.get("format", {}).get("duration")]
    duration_values.extend(stream.get("duration") for stream in probe_data.get("streams", []))
    duration = next((float(value) for value in duration_values if value not in (None, "N/A") and float(value) > 0), None)
    if duration is None: return QImage()

    result = subprocess.run([FFMPEG_PATH, "-v", "error", "-ss", f"{duration * 0.05:.6f}", "-i", str(file_path),
        "-frames:v", "1", "-vf", "scale=120:120:force_original_aspect_ratio=decrease","-f", "image2pipe",
        "-vcodec", "png", "pipe:1"],check=True, capture_output=True, creationflags=HIDE_CMD)
    image = QImage()
    image.loadFromData(result.stdout)
    return image

# Decode the first frame of an image with pillow
def load_preview_pixmap(file_path: Path,video_suffixes: set[str] | None = None) -> QPixmap:
    try:
        if (video_suffixes is not None and file_path.suffix.lower() in video_suffixes):
            return QPixmap.fromImage(load_video_preview_image(file_path))

        with Image.open(file_path) as img:
            img.seek(0)
            rgba = img.convert("RGBA")
            data = rgba.tobytes("raw", "RGBA")
            qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(qimage.copy())  # .copy() so the QImage owns its data
    except Exception: return QPixmap()

# A grid cell with a scaled preview and filename underneath
# Clicking selects/deselects an image, video or folder in the grid
class ThumbnailWidget(QWidget):
    clicked: Signal = Signal()

    def __init__(self, file_path: Path, video_suffixes: set[str] | None = None,
        parent: QWidget | None = None) -> None:

        super().__init__(parent)
        self.file_path: Path = file_path
        self._selected: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        image_label = QLabel()
        image_label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("border: 1px solid palette(mid);")

        if file_path.is_dir():
            pixmap = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon).pixmap(THUMBNAIL_SIZE - 24, THUMBNAIL_SIZE - 24)
            image_label.setToolTip(str(file_path))
        else: pixmap = load_preview_pixmap(file_path, video_suffixes)

        if not pixmap.isNull():
            scaled = pixmap.scaled(THUMBNAIL_SIZE, THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            image_label.setPixmap(scaled)
        else: image_label.setText("(preview\nunavailable)")

        name_label = QLabel(file_path.name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setFixedWidth(THUMBNAIL_SIZE)
        name_label.setWordWrap(False)
        metrics = name_label.fontMetrics()
        name_label.setText(metrics.elidedText(file_path.name, Qt.TextElideMode.ElideMiddle, THUMBNAIL_SIZE))

        layout.addWidget(image_label)
        layout.addWidget(name_label)

        self._image_label: QLabel = image_label
        self._update_style()

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def _update_style(self) -> None:
        # Only restyle the image label, not the whole widget, so the
        # filename text underneath doesn't get highlighted too.
        if self._selected:
            self._image_label.setStyleSheet("border: 2px solid palette(highlight); background-color: palette(highlight);")
        else:
            self._image_label.setStyleSheet("border: 1px solid palette(mid);")

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton: self.clicked.emit()
        super().mousePressEvent(event)

# The grid's content widget with its own QGridLayout and reflows its column count as the available width changes
class ImageGridWidget(QWidget):
    contents_changed: Signal = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid_layout: QGridLayout = QGridLayout(self)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(CELL_SPACING)

        self._thumbnails: list[ThumbnailWidget] = []
        self._selected: set[ThumbnailWidget] = set()
        self._columns: int = MIN_COLUMNS
        self._video_suffixes: set[str] = set()

    def add_image(self, file_path: Path) -> None:
        thumbnail = ThumbnailWidget(file_path, self._video_suffixes)
        _ = thumbnail.clicked.connect(lambda: self._toggle_selection(thumbnail))
        self._thumbnails.append(thumbnail)
        row, col = divmod(len(self._thumbnails) - 1, self._columns)
        self.grid_layout.addWidget(thumbnail, row, col)
        self.contents_changed.emit()

    def add_folder(self, folder_path: Path) -> None:
        thumbnail = ThumbnailWidget(folder_path, self._video_suffixes)
        _ = thumbnail.clicked.connect(lambda: self._toggle_selection(thumbnail))
        self._thumbnails.append(thumbnail)
        row, col = divmod(len(self._thumbnails) - 1, self._columns)
        self.grid_layout.addWidget(thumbnail, row, col)
        self.contents_changed.emit()

    def set_video_suffixes(self, suffixes: set[str]) -> None:
        self._video_suffixes = {suffix.lower() for suffix in suffixes}
        self.contents_changed.emit()

    # Return imported file paths in the order they were added
    def get_file_paths(self) -> list[Path]:
        return [t.file_path for t in self._thumbnails]

    def _toggle_selection(self, thumbnail: ThumbnailWidget) -> None:
        if thumbnail in self._selected:
            self._selected.discard(thumbnail)
            thumbnail.set_selected(False)
        else:
            self._selected.add(thumbnail)
            thumbnail.set_selected(True)

    def remove_selected(self) -> None:
        if not self._selected: return

        kept: list[ThumbnailWidget] = []
        for thumbnail in self._thumbnails:
            if thumbnail in self._selected:
                self.grid_layout.removeWidget(thumbnail)
                thumbnail.deleteLater()
            else: kept.append(thumbnail)

        self._thumbnails = kept
        self._selected.clear()
        self._reflow()
        self.contents_changed.emit()

    def remove_all(self) -> None:
        for thumbnail in self._thumbnails:
            self.grid_layout.removeWidget(thumbnail)
            thumbnail.deleteLater()

        self._thumbnails.clear()
        self._selected.clear()
        self.contents_changed.emit()

    # Recompute column count using width and reflow if needed
    def reflow_for_width(self, available_width: int) -> None:
        """Recompute column count from an externally-supplied width and reflow if it changed."""
        margins = self.grid_layout.contentsMargins()
        usable_width = available_width - margins.left() - margins.right()
        cell_width = THUMBNAIL_SIZE + CELL_SPACING
        new_columns = max(MIN_COLUMNS, usable_width // cell_width)
        if new_columns != self._columns:
            self._columns = new_columns
            self._reflow()

    def _reflow(self) -> None:
        for widget in self._thumbnails:
            self.grid_layout.removeWidget(widget)
        for index, widget in enumerate(self._thumbnails):
            row, col = divmod(index, self._columns)
            self.grid_layout.addWidget(widget, row, col)

# QScrollArea that tells ImageGridWidget how wide the viewport is whenever it resizes
class ResizingScrollArea(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_grid()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow_grid()
        return super().eventFilter(watched, event)

    # Always reserve room for the vertical scrollbar, even when not currently visible
    def _reflow_grid(self) -> None:
        grid = self.widget()
        if isinstance(grid, ImageGridWidget):
            scrollbar_width = self.verticalScrollBar().sizeHint().width()
            grid.reflow_for_width(self.viewport().width() - scrollbar_width)
