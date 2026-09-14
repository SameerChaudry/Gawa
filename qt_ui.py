"""
UI definition, hand-written to mirror pyside6-uic's generated-code style
(including the inheritance pattern needed for basedpyright to see widgets as
real, statically-known attributes). Only builds and arranges widgets: no
file dialogs, no subprocess calls, no signal connections to backend logic.
That all lives in main.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import override

from PIL import Image
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

THUMBNAIL_SIZE = 120
CELL_SPACING = 12
MIN_COLUMNS = 1


def load_preview_pixmap(file_path: Path) -> QPixmap:
    """Decode the first frame via Pillow rather than QPixmap(path), since Qt's
    AVIF plugin isn't guaranteed to ship with PySide6. Returns a null QPixmap
    on failure, same as a failed QPixmap(path) would.
    """
    try:
        with Image.open(file_path) as img:
            img.seek(0)
            rgba = img.convert("RGBA")
            data = rgba.tobytes("raw", "RGBA")
            qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(qimage.copy())  # .copy() so the QImage owns its data
    except Exception:
        return QPixmap()


def clear_layout(layout: QLayout) -> None:
    """Detach and delete every widget in a layout, leaving the layout itself intact."""
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class ThumbnailWidget(QWidget):
    """One grid cell: a scaled preview + filename. Clicking toggles selection;
    ImageGridWidget owns the actual set of what's selected.
    """

    clicked: Signal = Signal()

    def __init__(self, file_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_path: Path = file_path
        self._selected: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        image_label = QLabel()
        image_label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("border: 1px solid palette(mid);")

        pixmap = load_preview_pixmap(file_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                THUMBNAIL_SIZE,
                THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
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
            self._image_label.setStyleSheet(
                "border: 2px solid palette(highlight); background-color: palette(highlight);"
            )
        else:
            self._image_label.setStyleSheet("border: 1px solid palette(mid);")

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ImageGridWidget(QWidget):
    """The scrollable grid's content widget: owns the QGridLayout and reflows
    its column count as the available width changes.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid_layout: QGridLayout = QGridLayout(self)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(CELL_SPACING)

        self._thumbnails: list[ThumbnailWidget] = []
        self._selected: set[ThumbnailWidget] = set()
        self._columns: int = MIN_COLUMNS

    def add_image(self, file_path: Path) -> None:
        thumbnail = ThumbnailWidget(file_path)
        _ = thumbnail.clicked.connect(lambda: self._toggle_selection(thumbnail))
        self._thumbnails.append(thumbnail)
        row, col = divmod(len(self._thumbnails) - 1, self._columns)
        self.grid_layout.addWidget(thumbnail, row, col)

    def get_file_paths(self) -> list[Path]:
        """Return imported files in the order they were added."""
        return [t.file_path for t in self._thumbnails]

    def _toggle_selection(self, thumbnail: ThumbnailWidget) -> None:
        if thumbnail in self._selected:
            self._selected.discard(thumbnail)
            thumbnail.set_selected(False)
        else:
            self._selected.add(thumbnail)
            thumbnail.set_selected(True)

    def remove_selected(self) -> None:
        if not self._selected:
            return

        kept: list[ThumbnailWidget] = []
        for thumbnail in self._thumbnails:
            if thumbnail in self._selected:
                self.grid_layout.removeWidget(thumbnail)
                thumbnail.deleteLater()
            else:
                kept.append(thumbnail)

        self._thumbnails = kept
        self._selected.clear()
        self._reflow()

    def remove_all(self) -> None:
        for thumbnail in self._thumbnails:
            self.grid_layout.removeWidget(thumbnail)
            thumbnail.deleteLater()

        self._thumbnails.clear()
        self._selected.clear()

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
        # removeWidget() only detaches a widget from the layout's row/col
        # bookkeeping -- it doesn't reparent or delete anything, so the same
        # ThumbnailWidget instances survive and get re-added at new spots.
        for widget in self._thumbnails:
            self.grid_layout.removeWidget(widget)
        for index, widget in enumerate(self._thumbnails):
            row, col = divmod(index, self._columns)
            self.grid_layout.addWidget(widget, row, col)


class ResizingScrollArea(QScrollArea):
    """QScrollArea that tells its ImageGridWidget how wide the viewport
    actually is whenever it resizes, including when a scrollbar
    appears/disappears purely from content changing.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow_grid()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow_grid()
        return super().eventFilter(watched, event)

    def _reflow_grid(self) -> None:
        grid = self.widget()
        if isinstance(grid, ImageGridWidget):
            # Always reserve room for the vertical scrollbar, even when not
            # currently visible -- otherwise adding a column can trigger a
            # scrollbar that narrows the viewport without ever recomputing
            # column count, leaving the grid permanently too wide.
            scrollbar_width = self.verticalScrollBar().sizeHint().width()
            grid.reflow_for_width(self.viewport().width() - scrollbar_width)


class MiddleBarWidget(QWidget):
    """The row of format-specific conversion options between the top bar and
    the image grid: builds its own widgets per format and handles any
    visual conflicts between them (greying out, hiding, tooltips).

    `quality_spinbox` and the shared `speed_label`/`speed_spinbox` live in
    the top bar but get reused/repurposed per format, so they're passed in
    once from setupUi(). `deps` (passed into rebuild(), not stored) is a
    plain name -> bool availability map from main.py's shutil.which() checks.

    After rebuild(), `value(name)` is main.py's read API for the current
    format's options -- it doesn't need to know which Qt widget backs each one.
    """

    def __init__(
        self, quality_spinbox: QSpinBox, speed_label: QLabel, speed_spinbox: QSpinBox,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._layout: QHBoxLayout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._quality_spinbox: QSpinBox = quality_spinbox
        self._speed_label: QLabel = speed_label
        self._speed_spinbox: QSpinBox = speed_spinbox
        self._saved_quality_value: int = quality_spinbox.value()
        self._current_format: str | None = None
        self.options: dict[str, QWidget] = {}
        _ = quality_spinbox.valueChanged.connect(self._remember_quality_value)

    def _remember_quality_value(self, value: int) -> None:
        # APNG forces this to 100 itself; don't let that overwrite the real
        # value we'll want to restore once the user leaves APNG.
        if self._current_format != "apng":
            self._saved_quality_value = value

    def _enable_speed(self, minimum: int, maximum: int, value: int, tooltip: str) -> None:
        """Turn on the shared speed control and configure it for the current format."""
        self._speed_label.setEnabled(True)
        self._speed_spinbox.setEnabled(True)
        self._speed_spinbox.setRange(minimum, maximum)
        self._speed_spinbox.setValue(value)
        self._speed_spinbox.setToolTip(tooltip)

    def value(self, name: str) -> bool | int | str:
        """Current value of a format-specific option: bool for checkboxes,
        int for spinboxes, str for combo boxes.
        """
        widget = self.options.get(name)
        if widget is None:
            raise KeyError(f"Option {name!r} is not available for this format")
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        raise TypeError(f"Unsupported option widget for {name!r}: {type(widget).__name__}")

    def rebuild(self, fmt: str, deps: dict[str, bool]) -> None:
        """Tear down and rebuild the row for `fmt` (already lowercased, e.g.
        "gif"). Restores the quality spinbox's value if we're leaving APNG.
        """
        if self._current_format == "apng":
            self._quality_spinbox.setValue(self._saved_quality_value)

        self._current_format = fmt
        clear_layout(self._layout)
        self.options = {}
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
        local_color_table = QCheckBox("Local color table")
        gifski = QCheckBox("Use Gifski")
        delay_label = QLabel("Delay:")
        combo = QComboBox()
        combo.addItems(["Mode", "Average", "Custom"])
        spin = QSpinBox()
        spin.setRange(1, 9999)
        spin.setValue(20)
        self._speed_spinbox.setToolTip("Speed is unavailable for Gif")

        for w in (local_color_table, gifski, delay_label, combo, spin):
            self._layout.addWidget(w)

        self.options["local_color_table"] = local_color_table
        self.options["use_gifski"] = gifski
        self.options["delay_mode"] = combo
        self.options["delay_ms"] = spin

        self._quality_spinbox.setEnabled(False)
        self._quality_spinbox.setToolTip("Pillow GIF encoding does not use quality. Use Gifski to adjust GIF quality")

        def update_constraints() -> None:
            local_color_table.setEnabled(not gifski.isChecked())
            local_color_table.setToolTip(
                "Unavailable while Gifski is enabled" if gifski.isChecked()
                else "Lets each frame have 255 colors instead of the whole gif at the cost of file size"
            )

            gifski_available = deps["gifski"] and not local_color_table.isChecked()
            gifski.setEnabled(gifski_available)
            if not gifski_available:
                gifski.setToolTip(
                    "Unavailable: gifski isn't installed." if not deps["gifski"]
                    else "Unavailable: incompatible with local color table"
                )
            else:
                gifski.setToolTip("Most efficient gif encoder but doesn't support variable frame delay and local color tables")

            use_gifski = gifski.isChecked() and gifski_available
            self._quality_spinbox.setEnabled(use_gifski)
            self._quality_spinbox.setToolTip(
                "Gifski quality (higher is better)" if use_gifski
                else "Pillow GIF encoding does not use quality. Use Gifski to adjust GIF quality."
            )
            delay_label.setVisible(use_gifski)
            combo.setVisible(use_gifski)
            spin.setVisible(use_gifski and combo.currentText() == "Custom")

        _ = gifski.toggled.connect(update_constraints)
        _ = local_color_table.toggled.connect(update_constraints)
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

        # APNG is effectively lossless either way it's encoded, so "quality"
        # doesn't apply here regardless of whether apngasm ends up checked.
        self._quality_spinbox.setEnabled(False)
        self._quality_spinbox.setValue(100)
        self._quality_spinbox.setToolTip("APNG is lossless. Quality is always 100.")

    def _build_webp(self, deps: dict[str, bool]) -> None:
        use_img2webp = QCheckBox("Use img2webp")
        use_mixed = QCheckBox("Use mixed mode")
        sharp = QCheckBox("Use sharp YUV conversion")

        use_img2webp.setEnabled(deps["img2webp"])
        use_img2webp.setToolTip(
            "Use img2webp for encoding. Provides better efficiency" if deps["img2webp"]
            else "Unavailable: img2webp isn't installed."
        )
        use_mixed.setToolTip("Let img2webp choose lossy or lossless compression per frame (slow)")
        sharp.setToolTip("Use img2webp's sharper RGB-to-YUV conversion (slower)")

        for w in (use_img2webp, use_mixed, sharp):
            self._layout.addWidget(w)

        self.options["use_img2webp"] = use_img2webp
        self.options["use_mixed"] = use_mixed
        self.options["sharp"] = sharp
        self.options["speed"] = self._speed_spinbox

        self._enable_speed(0, 6, 4, "Pillow WebP method: higher values are slower but may improve compression")

        def update_constraints() -> None:
            img2webp_active = use_img2webp.isChecked() and use_img2webp.isEnabled()
            sharp.setVisible(img2webp_active)
            use_mixed.setVisible(img2webp_active)
            self._speed_spinbox.setToolTip(
                "img2webp method: higher values are slower but may improve compression" if img2webp_active
                else "Pillow WebP method: higher values are slower but may improve compression"
            )

        _ = use_img2webp.toggled.connect(update_constraints)
        update_constraints()

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

        delay_label = QLabel("Delay:")
        delay_mode = QComboBox()
        delay_mode.addItems(["Mode", "Average", "Custom"])
        delay_ms = QSpinBox()
        delay_ms.setRange(1, 9999)
        delay_ms.setValue(20)

        for w in (subsampling_label, subsampling, use_ffmpeg, crf_label, crf, delay_label, delay_mode, delay_ms):
            self._layout.addWidget(w)

        self.options["subsampling"] = subsampling
        self.options["speed"] = self._speed_spinbox
        self.options["use_ffmpeg"] = use_ffmpeg
        self.options["crf"] = crf
        self.options["delay_mode"] = delay_mode
        self.options["delay_ms"] = delay_ms

        self._enable_speed(0, 10, 8, "Pillow speed: Higher values are faster")
        ffmpeg_available = deps["ffmpeg"]
        use_ffmpeg.setEnabled(ffmpeg_available)
        use_ffmpeg.setToolTip(
            "Best size/quality/speed tradeoff, using libsvtav1." if ffmpeg_available
            else "Unavailable: ffmpeg isn't installed."
        )

        def update_constraints() -> None:
            ffmpeg_active = use_ffmpeg.isChecked() and ffmpeg_available

            # SVT-AV1's ffmpeg interface takes pixel-format names, not
            # Pillow's subsampling values -- swap the combo to match.
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
            delay_ms.setVisible(ffmpeg_active and delay_mode.currentText() == "Custom")

            if ffmpeg_active:
                self._speed_spinbox.setRange(-2, 13)
                self._speed_spinbox.setToolTip("FFmpeg preset: Higher is faster but less efficient")
            else:
                self._speed_spinbox.setRange(0, 10)
                self._speed_spinbox.setToolTip("Pillow speed: Higher is faster but less efficient")

            self._quality_spinbox.setEnabled(not ffmpeg_active)
            self._quality_spinbox.setToolTip("" if not ffmpeg_active else "Quality is set via Crf when using ffmpeg.")

        _ = use_ffmpeg.toggled.connect(update_constraints)
        _ = delay_mode.currentTextChanged.connect(update_constraints)
        update_constraints()


class Ui_MainWindow:  # noqa: N801 (matches pyside6-uic's generated class naming)
    """Builds and arranges every widget onto `self`. Call as `self.setupUi(self)`
    from a class that inherits both QMainWindow and Ui_MainWindow -- see main.py.
    No signals are connected here; that's main.py's job.
    """

    # No __init__: giving Ui_MainWindow one makes basedpyright flag the
    # multiple inheritance in MainWindow(QMainWindow, Ui_MainWindow) as
    # unsafe. setupUi() is this class's real initializer instead, so each
    # attribute is annotated where it's assigned, with an inline ignore.

    def setupUi(self, MainWindow: QMainWindow) -> None:  # noqa: N802, N803 (matches pyside6-uic convention)
        MainWindow.setWindowTitle("Gawa")
        MainWindow.resize(700, 500)

        self.central_widget: QWidget = QWidget()  # pyright: ignore[reportUninitializedInstanceVariable]
        MainWindow.setCentralWidget(self.central_widget)
        root_layout = QVBoxLayout(self.central_widget)

        # ---------- top bar ----------
        top_bar = QHBoxLayout()

        self.add_files_button: QPushButton = QPushButton("Add Files")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.remove_button: QPushButton = QPushButton("Remove")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.remove_all_button: QPushButton = QPushButton("Remove All")  # pyright: ignore[reportUninitializedInstanceVariable]

        convert_to_label = QLabel("Convert to:")
        self.format_dropdown: QComboBox = QComboBox()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.format_dropdown.addItems(["GIF", "WEBP", "AVIF", "APNG"])

        quality_label = QLabel("Quality:")
        self.quality_spinbox: QSpinBox = QSpinBox()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.quality_spinbox.setRange(1, 100)
        self.quality_spinbox.setValue(90)
        self.quality_spinbox.setToolTip("100 uses lossless encoding, 1-99 is lossy")

        self.speed_label: QLabel = QLabel("Speed:")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.speed_spinbox: QSpinBox = QSpinBox()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.speed_spinbox.setRange(0, 13)
        self.speed_spinbox.setValue(8)

        save_to_label = QLabel("Save to:")
        self.output_folder_button: QPushButton = QPushButton("Choose folder...")  # pyright: ignore[reportUninitializedInstanceVariable]

        top_bar.addWidget(self.add_files_button)
        top_bar.addWidget(self.remove_button)
        top_bar.addWidget(self.remove_all_button)
        top_bar.addWidget(convert_to_label)
        top_bar.addWidget(self.format_dropdown)
        top_bar.addWidget(quality_label)
        top_bar.addWidget(self.quality_spinbox)
        top_bar.addWidget(self.speed_label)
        top_bar.addWidget(self.speed_spinbox)
        top_bar.addSpacing(20)
        top_bar.addWidget(save_to_label)
        top_bar.addWidget(self.output_folder_button)
        top_bar.addStretch()

        self.make_convert_button: QPushButton = QPushButton("Convert")  # pyright: ignore[reportUninitializedInstanceVariable]
        top_bar.addWidget(self.make_convert_button)

        root_layout.addLayout(top_bar)

        # ---------- middle bar (format-specific conversion options) ----------
        self.middle_bar: MiddleBarWidget = MiddleBarWidget(
            self.quality_spinbox, self.speed_label, self.speed_spinbox
        )  # pyright: ignore[reportUninitializedInstanceVariable]
        root_layout.addWidget(self.middle_bar)

        # ---------- scrollable image grid ----------
        self.image_grid: ImageGridWidget = ImageGridWidget()  # pyright: ignore[reportUninitializedInstanceVariable]

        scroll_area = ResizingScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.image_grid)

        root_layout.addWidget(scroll_area)