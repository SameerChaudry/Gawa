# Handles all the gui related logic while leaving all the backend conversion to main.py

from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from typing import override
from PIL import Image
from media_io import FRAME_SUFFIXES
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QResizeEvent, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

THUMBNAIL_SIZE = 120
CELL_SPACING = 12
MIN_COLUMNS = 1
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")
MAX_FPS = {"gif": 50, "webp": 90, "avif": 90, "apng": 90}

# Decode a frame at 5% of the the video's duration
def load_video_preview_image(file_path: Path) -> QImage:
    if FFMPEG_PATH is None or FFPROBE_PATH is None: return QImage()

    probe = subprocess.run([FFPROBE_PATH, "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration:stream=duration", 
        "-of", "json", str(file_path)], check=True, capture_output=True, text=True)
    probe_data = json.loads(probe.stdout)
    duration_values = [probe_data.get("format", {}).get("duration")]
    duration_values.extend(stream.get("duration") for stream in probe_data.get("streams", []))
    duration = next((float(value) for value in duration_values if value not in (None, "N/A") and float(value) > 0), None)
    if duration is None: return QImage()

    result = subprocess.run([FFMPEG_PATH, "-v", "error", "-ss", f"{duration * 0.05:.6f}", "-i", str(file_path),
        "-frames:v", "1", "-vf", "scale=120:120:force_original_aspect_ratio=decrease",
        "-f", "image2pipe", "-vcodec", "png", "pipe:1"],check=True, capture_output=True)
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

# Detach and delete every widget in a layout while leaving the layout intact
def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None: continue
        widget = item.widget()
        if widget is not None: widget.deleteLater()

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
        else:
            image_label.setText("(preview\nunavailable)")

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

# The grid's content widget with own QGridLayout and reflows its column count as the available width changes
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

    def has_video_inputs(self) -> bool:
        for thumbnail in self._thumbnails:
            file_path = thumbnail.file_path
            if file_path.is_dir():
                try:
                    if any(child.is_file() and child.suffix.lower() in self._video_suffixes
                        for child in file_path.iterdir()):
                            return True

                except OSError: continue
            elif file_path.suffix.lower() in self._video_suffixes: return True
        return False

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

# The row of format-specific conversion options between the top bar and the image grid
# that builds new widgets based on the input and outputs formats for conversion
# Also includes some right-aligned widgets like the persistent Benchmarks button
class MiddleBarWidget(QWidget):
    def __init__(
        self, quality_spinbox: QSpinBox, speed_label: QLabel, speed_spinbox: QSpinBox,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._row_layout: QHBoxLayout = QHBoxLayout(self)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._layout: QHBoxLayout = QHBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.addLayout(self._layout)
        self._row_layout.addStretch()

        self.frames_fps_label: QLabel = QLabel("Frames FPS:")
        self.frames_fps_spinbox: QDoubleSpinBox = QDoubleSpinBox()
        self.frames_fps_spinbox.setRange(0.01, 90)
        self.frames_fps_spinbox.setDecimals(2)
        self.frames_fps_spinbox.setSingleStep(1)
        self.frames_fps_spinbox.setValue(10)
        self.frames_fps_spinbox.setToolTip("Frame rate used for static images in an imported frame folder")
        self.frames_fps_label.hide()
        self.frames_fps_spinbox.hide()

        self._row_layout.addWidget(self.frames_fps_label)
        self._row_layout.addWidget(self.frames_fps_spinbox)

        self.video_fps_label: QLabel = QLabel("Video FPS:")
        self.video_fps_spinbox: QDoubleSpinBox = QDoubleSpinBox()
        self.video_fps_spinbox.setRange(0, 90)
        self.video_fps_spinbox.setDecimals(2)
        self.video_fps_spinbox.setSingleStep(1)
        self.video_fps_spinbox.setValue(0)
        self.video_fps_spinbox.setToolTip("Frame rate used when decoding video inputs. 0 uses the video's source frame rate. Does not affect image inputs")
        self.video_fps_label.hide()
        self.video_fps_spinbox.hide()

        self._row_layout.addWidget(self.video_fps_label)
        self._row_layout.addWidget(self.video_fps_spinbox)
        self.benchmarks_button: QPushButton = QPushButton("Benchmarks")
        self._row_layout.addWidget(self.benchmarks_button)

        self._quality_spinbox: QSpinBox = quality_spinbox
        self._speed_label: QLabel = speed_label
        self._speed_spinbox: QSpinBox = speed_spinbox
        self._saved_quality_value: int = quality_spinbox.value()
        self._current_format: str | None = None
        self._has_static_frames = False
        self._frame_rate_conflict = False
        self.options: dict[str, QWidget] = {}
        _ = quality_spinbox.valueChanged.connect(self._remember_quality_value)

    # Make "Frames FPS" visible if "Framerate calculation" isn't visible and visa versa
    def update_frames_fps_visibility(self, has_static_frames: bool | None = None,
    framerate_conflict: bool | None = None) -> None:
        if has_static_frames is not None:  self._has_static_frames = has_static_frames
        if framerate_conflict is not None: self._frame_rate_conflict = framerate_conflict
        visible = self._has_static_frames and not self._frame_rate_conflict
        self.frames_fps_label.setVisible(visible)
        self.frames_fps_spinbox.setVisible(visible)
        self.frames_fps_spinbox.setEnabled(visible)

    # Restore the previously selected quality when switching away from apng since apng is lossless
    def _remember_quality_value(self, value: int) -> None:
        if self._current_format != "apng": self._saved_quality_value = value

    # Set speed spinbox visibility and range as needed
    def _enable_speed(self, minimum: int, maximum: int, value: int, tooltip: str) -> None:
        self._speed_label.setEnabled(True)
        self._speed_spinbox.setEnabled(True)
        self._speed_spinbox.setRange(minimum, maximum)
        self._speed_spinbox.setValue(value)
        self._speed_spinbox.setToolTip(tooltip)

    # Returns the current value of a widget
    def value(self, name: str) -> bool | int | str:
        widget = self.options.get(name)
        if widget is None: raise KeyError(f"Option {name!r} is not available for this format")
        if isinstance(widget, QCheckBox): return widget.isChecked()
        if isinstance(widget, QSpinBox):  return widget.value()
        if isinstance(widget, QComboBox): return widget.currentText()
        raise TypeError(f"Unsupported option widget for {name!r}: {type(widget).__name__}")

    # Copy current option values so conversion workers don't need to read Qt widgets
    def snapshot(self) -> dict[str, bool | int | str]:
        return {name: self.value(name) for name in self.options}

    # Clear and rebuild the row based on the output format
    def rebuild(self, fmt: str, deps: dict[str, bool]) -> None:
        if self._current_format == "apng":
            self._quality_spinbox.setValue(self._saved_quality_value)

        self._current_format = fmt
        max_fps = MAX_FPS.get(fmt, 90)
        self.frames_fps_spinbox.setMaximum(max_fps)
        self.frames_fps_spinbox.setToolTip(f"Frame rate used for static images in an imported folder. Maximum {max_fps} fps for {fmt.upper()})")
        self.video_fps_spinbox.setMaximum(max_fps)
        self.video_fps_spinbox.setToolTip(f"Frame rate used when decoding video inputs. 0 uses the video's source frame rate. Maximum {max_fps} fps for {fmt.upper()}. Does not affect image inputs")
        clear_layout(self._layout)
        self.options = {}
        self.update_frames_fps_visibility(framerate_conflict=False)
        self._quality_spinbox.setEnabled(True)
        self._quality_spinbox.setToolTip("")
        self._speed_label.setEnabled(False)
        self._speed_spinbox.setEnabled(False)
        self._speed_spinbox.setToolTip("")

        if fmt == "gif":    self._build_gif(deps)
        elif fmt == "apng": self._build_apng(deps)
        elif fmt == "webp": self._build_webp(deps)
        elif fmt == "avif": self._build_avif(deps)

        self._layout.addStretch()

    def _build_gif(self, deps: dict[str, bool]) -> None:
        gifski = QCheckBox("Use Gifski")
        use_ffmpeg = QCheckBox("Use ffmpeg")
        dither = QCheckBox("Apply Dithering")
        dither.setChecked(False)
        dither.setToolTip("Apply sierra2_4a dithering to the GIF")

        gifski_speed_label = QLabel("Speed:")
        gifski_speed = QComboBox()
        gifski_speed.addItems(["Default", "Fast", "Extra"])
        gifski_speed.setToolTip("Fast: Faster encode for slightly larger size\nExtra: Slower encode for slightly smaller size")

        delay_label = QLabel("Framerate Calculation:")
        combo = QComboBox()
        combo.addItems(["Mode", "Average", "Custom fps"])
        combo.setToolTip("Mode: Uses the most common frame delay\nAverage: Uses the average frame delay\nCustom fps: Uses a custom frame rate")
        spin = QSpinBox()
        spin.setRange(1, MAX_FPS["gif"])
        spin.setValue(20)
        spin.setToolTip("Maximum fps for gif is 50. Higher values don't play consistently across most browsers/image viewers")
        self._speed_spinbox.setToolTip("Speed is unavailable for GIF")

        for w in (gifski, use_ffmpeg, dither, gifski_speed_label, gifski_speed, delay_label, combo, spin):
            self._layout.addWidget(w)

        self.options["use_gifski"] = gifski
        self.options["use_ffmpeg"] = use_ffmpeg
        self.options["dither"] = dither
        self.options["gifski_speed"] = gifski_speed
        self.options["delay_mode"] = combo
        self.options["custom_fps"] = spin

        self._quality_spinbox.setEnabled(False)
        self._quality_spinbox.setToolTip("Pillow and ffmpeg GIF encoding do not use quality. Use Gifski to adjust GIF quality")

        def update_constraints() -> None:
            gifski_available = deps["gifski"]
            ffmpeg_available = deps["ffmpeg"]
            ffmpeg_active = use_ffmpeg.isChecked() and ffmpeg_available
            if ffmpeg_active: self.update_frames_fps_visibility(framerate_conflict=True)

            gifski.setEnabled(gifski_available)
            use_ffmpeg.setEnabled(ffmpeg_available)
            dither.setVisible(use_ffmpeg.isChecked() and ffmpeg_available)
            gifski_speed_label.setVisible(gifski.isChecked() and gifski_available)
            gifski_speed.setVisible(gifski.isChecked() and gifski_available)

            if not gifski_available: gifski.setToolTip("Unavailable: gifski isn't installed")
            else: gifski.setToolTip("Most efficient gif encoder but doesn't support variable frame delay and local color tables")

            if not ffmpeg_available: use_ffmpeg.setToolTip("Unavailable: ffmpeg isn't installed")
            else: use_ffmpeg.setToolTip("Use ffmpeg's palettegen/paletteuse pipeline. Uses a single palette for the entire GIF")

            if gifski.isChecked() and gifski_available:
                use_ffmpeg.setChecked(False)
                use_ffmpeg.setEnabled(False)
                self._quality_spinbox.setEnabled(True)
                self._quality_spinbox.setToolTip("Gifski quality (higher is better)")
                dither.setVisible(False)
                delay_label.setVisible(True)
                combo.setVisible(True)
                spin.setVisible(combo.currentText() == "Custom fps")

            elif use_ffmpeg.isChecked() and ffmpeg_available:
                gifski.setChecked(False)
                gifski.setEnabled(False)
                self._quality_spinbox.setEnabled(False)
                self._quality_spinbox.setToolTip("FFmpeg GIF encoding does not use quality")
                dither.setVisible(True)
                delay_label.setVisible(True)
                combo.setVisible(True)
                spin.setVisible(combo.currentText() == "Custom fps")

            else:
                if not gifski_available: gifski.setEnabled(False)
                if not ffmpeg_available: use_ffmpeg.setEnabled(False)
                self._quality_spinbox.setEnabled(False)
                self._quality_spinbox.setToolTip("Pillow and ffmpeg GIF encoding do not use quality. Use Gifski to adjust GIF quality")
                dither.setVisible(False)
                delay_label.setVisible(False)
                combo.setVisible(False)
                spin.setVisible(False)

            if not ffmpeg_active:
                self.update_frames_fps_visibility(framerate_conflict=False)

        _ = gifski.toggled.connect(update_constraints)
        _ = use_ffmpeg.toggled.connect(update_constraints)
        _ = combo.currentTextChanged.connect(update_constraints)
        update_constraints()

    def _build_apng(self, deps: dict[str, bool]) -> None:
        use_apngasm = QCheckBox("Use apngasm (very slow, better compression)")
        self._layout.addWidget(use_apngasm)
        self.options["use_apngasm"] = use_apngasm
        self.options["speed"] = self._speed_spinbox

        apngasm_available = deps["apngasm"]
        use_apngasm.setEnabled(apngasm_available)
        use_apngasm.setToolTip("" if apngasm_available else "Unavailable: apngasm isn't installed")

        self._enable_speed(0, 9, 6, "Pillow PNG compression level. 0 is fastest, 9 is smallest")

        def update_speed_availability() -> None:
            pillow_encoder_active = not (apngasm_available and use_apngasm.isChecked())
            self._speed_label.setEnabled(pillow_encoder_active)
            self._speed_spinbox.setEnabled(pillow_encoder_active)
            self._speed_spinbox.setToolTip(
                "Pillow PNG compression level. 0 is fastest, 9 is smallest" if pillow_encoder_active
                else "Speed is unavailable while apngasm is selected."
            )

        _ = use_apngasm.toggled.connect(update_speed_availability)
        update_speed_availability()

        # APNG is lossless so quality doesn't apply
        self._quality_spinbox.setEnabled(False)
        self._quality_spinbox.setValue(100)
        self._quality_spinbox.setToolTip("APNG is lossless. Quality is always 100.")

    def _build_webp(self, deps: dict[str, bool]) -> None:
        exact = QCheckBox("Use exact")
        exact.setToolTip("Preserve RGB values in fully transparent pixels")
        self._layout.addWidget(exact)
        use_mixed = QCheckBox("Use mixed mode")
        use_mixed.setToolTip("Let pillow choose lossy or lossless compression per frame (slow)")
        self._layout.addWidget(use_mixed)
        self.options["exact"] = exact
        self.options["use_mixed"] = use_mixed
        self.options["speed"] = self._speed_spinbox
        self._enable_speed(0, 6, 4, "Higher values are slower but may improve compression")
        self._speed_spinbox.setToolTip("Higher values are slower but may improve compression")

    def _build_avif(self, deps: dict[str, bool]) -> None:
        pillow_subsampling = ["4:0:0", "4:2:0", "4:2:2", "4:4:4"]
        ffmpeg_pixel_formats = ["yuv420p", "yuv420p10le"]

        subsampling_label = QLabel("Subsampling:")
        subsampling = QComboBox()
        subsampling.addItems(pillow_subsampling)
        subsampling.setCurrentText("4:2:0")

        use_ffmpeg = QCheckBox("Use ffmpeg")
        crf_label = QLabel("Crf:")
        crf = QSpinBox()
        crf.setRange(0, 63)
        crf.setValue(35)
        crf.setToolTip("Lower is better quality but larger size")

        delay_label = QLabel("Framerate Calculation:")
        delay_mode = QComboBox()
        delay_mode.addItems(["Mode", "Average", "Custom fps"])
        delay_mode.setToolTip("Mode: Uses the most common frame delay\nAverage: Uses the average frame delay\nCustom fps: Uses a custom frame rate")
        custom_fps = QSpinBox()
        custom_fps.setRange(1, MAX_FPS["avif"])
        custom_fps.setValue(20)
        custom_fps.setToolTip("Maximum fps for avif is 90. Higher values don't play consistently across most browsers/image viewers")

        for w in (subsampling_label, subsampling, use_ffmpeg, crf_label, crf, delay_label, delay_mode, custom_fps):
            self._layout.addWidget(w)

        self.options["subsampling"] = subsampling
        self.options["speed"] = self._speed_spinbox
        self.options["use_ffmpeg"] = use_ffmpeg
        self.options["crf"] = crf
        self.options["delay_mode"] = delay_mode
        self.options["custom_fps"] = custom_fps

        self._enable_speed(0, 10, 7, "Pillow speed: Higher values are faster")
        ffmpeg_available = deps["ffmpeg"]
        use_ffmpeg.setEnabled(ffmpeg_available)
        use_ffmpeg.setToolTip("Best size/quality/speed tradeoff, using libsvtav1. But doesn't support transparency and subsampling formats except yuv420p and yuv420p10le" if ffmpeg_available
            else "Unavailable: ffmpeg isn't installed.")

        def update_constraints() -> None:
            ffmpeg_active = use_ffmpeg.isChecked() and ffmpeg_available
            if ffmpeg_active: self.update_frames_fps_visibility(framerate_conflict=True)

            current_choice = subsampling.currentText()
            subsampling.clear()
            if ffmpeg_active:
                subsampling_label.setText("Pixel format:")
                subsampling.addItems(ffmpeg_pixel_formats)
                subsampling.setCurrentText(current_choice if current_choice in ffmpeg_pixel_formats else "yuv420p")
                subsampling.setToolTip("Pixel formats supported by the SVT-AV1 ffmpeg encoder")
            else:
                subsampling_label.setText("Subsampling:")
                subsampling.addItems(pillow_subsampling)
                subsampling.setCurrentText(current_choice if current_choice in pillow_subsampling else "4:2:0")
                subsampling.setToolTip("Chroma subsampling decides which color range is used by the aom encoder. 4:4:4 is best quality but largest size")

            crf_label.setVisible(ffmpeg_active)
            crf.setVisible(ffmpeg_active)
            delay_label.setVisible(ffmpeg_active)
            delay_mode.setVisible(ffmpeg_active)
            custom_fps.setVisible(ffmpeg_active and delay_mode.currentText() == "Custom fps")

            if ffmpeg_active:
                self._speed_spinbox.setRange(-2, 13)
                self._speed_spinbox.setToolTip("FFmpeg preset: Higher is faster but less efficient")
            else:
                self._speed_spinbox.setRange(0, 10)
                self._speed_spinbox.setToolTip("Pillow speed: Higher is faster but less efficient")

            self._quality_spinbox.setEnabled(not ffmpeg_active)
            self._quality_spinbox.setToolTip("100 quality is lossy since lossless isn't supported by Pillow"
                if not ffmpeg_active else "Quality is set via Crf when using ffmpeg.")
            if not ffmpeg_active:
                self.update_frames_fps_visibility(framerate_conflict=False)

        _ = use_ffmpeg.toggled.connect(update_constraints)
        _ = delay_mode.currentTextChanged.connect(update_constraints)
        update_constraints()

# The main window's layout and widgets. All internal UI signals are connected here, but backend signals are connected in main.py
class Ui_MainWindow:
    # No __init__ because giving Ui_MainWindow one makes basedpyright flag the
    # multiple inheritance in MainWindow as unsafe. setupUi() is this class's real initializer instead
    # so each attribute is annotated where it's assigned, with an inline ignore
    def setupUi(self, MainWindow: QMainWindow) -> None:
        MainWindow.setWindowTitle("Gawa")
        MainWindow.resize(700, 500)

        self.central_widget: QWidget = QWidget()  # pyright: ignore[reportUninitializedInstanceVariable]
        MainWindow.setCentralWidget(self.central_widget)
        root_layout = QVBoxLayout(self.central_widget)

        # ---------- top bar ----------
        top_bar = QHBoxLayout()

        self.add_files_button: QPushButton = QPushButton("Add Files")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.add_folder_button: QPushButton = QPushButton("Add Folder")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.remove_all_button: QPushButton = QPushButton("Remove All")  # pyright: ignore[reportUninitializedInstanceVariable]

        convert_to_label = QLabel("Convert to:")
        self.format_dropdown: QComboBox = QComboBox()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.format_dropdown.addItems(["GIF", "WEBP", "AVIF", "APNG"])

        quality_label = QLabel("Quality:")
        self.quality_spinbox: QSpinBox = QSpinBox()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.quality_spinbox.setRange(1, 100)
        self.quality_spinbox.setValue(80)
        self.quality_spinbox.setToolTip("100 uses lossless encoding, 1-99 is lossy")

        self.speed_label: QLabel = QLabel("Speed:")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.speed_spinbox: QSpinBox = QSpinBox()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.speed_spinbox.setRange(0, 13)
        self.speed_spinbox.setValue(7)

        save_to_label = QLabel("Save to:")
        self.output_folder_button: QPushButton = QPushButton("Choose folder...")  # pyright: ignore[reportUninitializedInstanceVariable]

        top_bar.addWidget(self.add_files_button)
        top_bar.addWidget(self.add_folder_button)
        top_bar.addWidget(self.remove_all_button)
        top_bar.addWidget(convert_to_label)
        top_bar.addWidget(self.format_dropdown)
        top_bar.addWidget(quality_label)
        top_bar.addWidget(self.quality_spinbox)
        top_bar.addWidget(self.speed_label)
        top_bar.addWidget(self.speed_spinbox)
        top_bar.addSpacing(10)
        top_bar.addStretch()
        top_bar.addWidget(save_to_label)
        top_bar.addWidget(self.output_folder_button)
        top_bar.addSpacing(5)

        self.make_convert_button: QPushButton = QPushButton("Convert")  # pyright: ignore[reportUninitializedInstanceVariable]
        top_bar.addWidget(self.make_convert_button)

        root_layout.addLayout(top_bar)

        # ---------- middle bar (format-specific conversion options) ----------
        self.middle_bar: MiddleBarWidget = MiddleBarWidget(self.quality_spinbox, self.speed_label, self.speed_spinbox)  # pyright: ignore[reportUninitializedInstanceVariable]
        root_layout.addWidget(self.middle_bar)

        # ---------- scrollable image grid ----------
        self.image_grid: ImageGridWidget = ImageGridWidget()  # pyright: ignore[reportUninitializedInstanceVariable]
        _ = self.image_grid.contents_changed.connect(self.update_video_fps_visibility)

        scroll_area = ResizingScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.image_grid)

        self.log_output: QPlainTextEdit = QPlainTextEdit()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(1000)
        log_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.log_output.setFont(log_font)
        self.log_output.setFont(log_font)
        self.log_output.setMinimumHeight(80)

        self.content_splitter: QSplitter = QSplitter(Qt.Orientation.Vertical)  # pyright: ignore[reportUninitializedInstanceVariable]
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(6)
        self.content_splitter.addWidget(scroll_area)
        self.content_splitter.addWidget(self.log_output)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([400, 120])

        root_layout.addWidget(self.content_splitter, 1)

    def set_video_suffixes(self, suffixes: set[str]) -> None:
        self.image_grid.set_video_suffixes(suffixes)

    # Show "Video FPS" if any video inputs are present and "Frames FPS" if any static frames are present
    def update_video_fps_visibility(self) -> None:
        has_video = self.image_grid.has_video_inputs()
        self.middle_bar.video_fps_label.setVisible(has_video)
        self.middle_bar.video_fps_spinbox.setVisible(has_video)
        has_static_frames = False
        for folder_path in self.image_grid.get_file_paths():
            if not folder_path.is_dir(): continue

            try:
                for frame_path in folder_path.iterdir():
                    if not frame_path.is_file() or frame_path.suffix.lower() not in FRAME_SUFFIXES:
                        continue
                    try:
                        with Image.open(frame_path) as image:
                            if getattr(image, "n_frames", 1) == 1:
                                has_static_frames = True
                                break
                    except OSError: continue
                if has_static_frames: break
            except OSError: continue
        self.middle_bar.update_frames_fps_visibility(has_static_frames=has_static_frames)