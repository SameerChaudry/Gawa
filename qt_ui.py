"""
UI definition, hand-written to mirror what `pyside6-uic` would generate from
a Designer .ui file — including the inheritance pattern real generated code
uses, which matters for type checkers like basedpyright.

This file only builds and arranges widgets. It contains no application
logic — no file dialogs, no subprocess calls, no .clicked.connect() calls.

IMPORTANT: setupUi() assigns widgets to `self` (the Ui_MainWindow instance),
not to the `MainWindow` parameter. That's deliberate and matches real
pyside6-uic output exactly. It only works because main.py's MainWindow class
inherits from BOTH QMainWindow and Ui_MainWindow (see main.py), so when
setupUi() is called as `self.setupUi(self)` from MainWindow.__init__, the
`self` inside setupUi() IS the actual MainWindow instance via Python's
normal method resolution — assigning self.add_files_button here really does
attach it to that same object. Static type checkers can then see
`add_files_button` as a real, statically-known attribute of MainWindow
(inherited from Ui_MainWindow), instead of an attribute silently poked onto
a plain QMainWindow at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

THUMBNAIL_SIZE = 120
CELL_SPACING = 12  # gap between cells, used to estimate how many columns fit
MIN_COLUMNS = 1


class ThumbnailWidget(QWidget):
    """One cell in the grid: a scaled preview image + filename label underneath.

    Clicking a thumbnail toggles its selection (used for "Remove" — as
    opposed to "Remove All", which doesn't need selection at all). The
    widget just tracks its own selected/deselected look; ImageGridWidget
    owns the actual set of what's currently selected.
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

        pixmap = QPixmap(str(file_path))
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
        elided = metrics.elidedText(
            file_path.name, Qt.TextElideMode.ElideMiddle, THUMBNAIL_SIZE
        )
        name_label.setText(elided)

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
        # Restyle the image label's border/background to show selection,
        # rather than the whole widget, so the filename text underneath
        # doesn't get a distracting highlighted box behind it too.
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
    """The scrollable grid's *content* widget. Owns the QGridLayout and
    reflows its column count as the available width changes.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid_layout: QGridLayout = QGridLayout(self)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(CELL_SPACING)

        self._file_paths: list[Path] = []
        self._thumbnails: list[ThumbnailWidget] = []
        self._selected: set[ThumbnailWidget] = set()
        self._columns: int = MIN_COLUMNS

    def add_image(self, file_path: Path) -> None:
        self._file_paths.append(file_path)
        thumbnail = ThumbnailWidget(file_path)
        _ = thumbnail.clicked.connect(lambda: self._toggle_selection(thumbnail))
        self._thumbnails.append(thumbnail)
        row, col = divmod(len(self._thumbnails) - 1, self._columns)
        self.grid_layout.addWidget(thumbnail, row, col)

    def get_file_paths(self) -> list[Path]:
        """Return imported files in the order they were added."""
        return list(self._file_paths)

    def _toggle_selection(self, thumbnail: ThumbnailWidget) -> None:
        if thumbnail in self._selected:
            self._selected.discard(thumbnail)
            thumbnail.set_selected(False)
        else:
            self._selected.add(thumbnail)
            thumbnail.set_selected(True)

    def remove_selected(self) -> None:
        """Remove every currently-selected thumbnail (and its file) from the grid."""
        if not self._selected:
            return

        kept_paths: list[Path] = []
        kept_thumbnails: list[ThumbnailWidget] = []
        for path, thumbnail in zip(self._file_paths, self._thumbnails):
            if thumbnail in self._selected:
                self.grid_layout.removeWidget(thumbnail)
                thumbnail.deleteLater()
            else:
                kept_paths.append(path)
                kept_thumbnails.append(thumbnail)

        self._file_paths = kept_paths
        self._thumbnails = kept_thumbnails
        self._selected.clear()
        self._reflow()

    def remove_all(self) -> None:
        """Remove every imported file from the grid."""
        for thumbnail in self._thumbnails:
            self.grid_layout.removeWidget(thumbnail)
            thumbnail.deleteLater()

        self._file_paths.clear()
        self._thumbnails.clear()
        self._selected.clear()

    def reflow_for_width(self, available_width: int) -> None:
        """Recompute column count from an externally-supplied width and reflow if it changed.

        Uses contentsMargins() (returns a QMargins object) rather than
        getContentsMargins() (which unpacks as a tuple at runtime but has
        stub typing that basedpyright can't confirm is iterable) — same
        result, cleanly typed.
        """
        margins = self.grid_layout.contentsMargins()
        usable_width = available_width - margins.left() - margins.right()
        cell_width = THUMBNAIL_SIZE + CELL_SPACING
        new_columns = max(MIN_COLUMNS, usable_width // cell_width)
        if new_columns != self._columns:
            self._columns = new_columns
            self._reflow()

    def _reflow(self) -> None:
        """Re-place every existing thumbnail at its new row/col, reusing the
        same QGridLayout instance.

        Earlier this method rebuilt the layout from scratch by reparenting
        it onto a temporary throwaway QWidget. That was a real bug: adding a
        widget to a layout makes it a CHILD of whatever widget owns that
        layout, so the temporary widget silently took ownership of every
        ThumbnailWidget. The instant that temp widget got garbage collected,
        Qt destroyed its children along with it — deleting all the
        thumbnails out from under us, which is exactly what produced the
        "Internal C++ object already deleted" crash.

        removeWidget() is much simpler and doesn't have this danger: it only
        detaches a widget from the layout's row/col bookkeeping. It doesn't
        touch parentage or delete anything, so the same ThumbnailWidget
        instances survive and can be safely re-added at new positions.
        """
        for widget in self._thumbnails:
            self.grid_layout.removeWidget(widget)
        for index, widget in enumerate(self._thumbnails):
            row, col = divmod(index, self._columns)
            self.grid_layout.addWidget(widget, row, col)


class ResizingScrollArea(QScrollArea):
    """QScrollArea that tells its contained ImageGridWidget how wide the
    viewport actually is, every time the viewport resizes — including when
    a scrollbar appears/disappears purely from content changing, which
    doesn't fire this widget's own resizeEvent.
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
            # Always reserve room for the vertical scrollbar, even when it
            # isn't currently visible. Without this, adding one more column
            # can make the grid tall enough to need a scrollbar — which then
            # narrows the viewport. If that narrower width still divides
            # into the same column count (the scrollbar is often narrower
            # than one full cell), the column count never gets recalculated,
            # and the grid is left permanently a scrollbar's-width too wide
            # — exactly the "last column slightly truncated" symptom.
            # Reserving the space unconditionally breaks that feedback loop,
            # at the minor cost of occasionally fitting one fewer column
            # than the absolute maximum.
            scrollbar_width = self.verticalScrollBar().sizeHint().width()
            grid.reflow_for_width(self.viewport().width() - scrollbar_width)


class Ui_MainWindow:  # noqa: N801 (matches pyside6-uic's generated class naming)
    """Builds and arranges every widget onto `self`.

    Call as `self.setupUi(self)` from a class that inherits BOTH QMainWindow
    and Ui_MainWindow — see main.py. No signals are connected here; that's
    main.py's job.
    """

    # Note: no __init__ here on purpose. Giving Ui_MainWindow an __init__
    # (even just to declare these attributes) makes basedpyright flag the
    # multiple inheritance in MainWindow(QMainWindow, Ui_MainWindow) as
    # unsafe (reportUnsafeMultipleInheritance) — Qt's C++ constructor chain
    # isn't guaranteed to cooperate with a second Python __init__. So instead
    # each attribute below is annotated right where it's actually assigned,
    # in setupUi(), with an inline ignore for reportUninitializedInstanceVariable:
    # basedpyright wants every instance attribute set in __init__, but
    # setupUi() genuinely IS this class's one-and-only initializer, just
    # under a different name (to match pyside6-uic's convention).

    def setupUi(self, MainWindow: QMainWindow) -> None:  # noqa: N802, N803 (matches pyside6-uic convention)
        MainWindow.setWindowTitle("Animated Image Converter")
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

        top_bar.addWidget(self.add_files_button)
        top_bar.addWidget(self.remove_button)
        top_bar.addWidget(self.remove_all_button)
        top_bar.addSpacing(20)
        top_bar.addWidget(convert_to_label)
        top_bar.addWidget(self.format_dropdown)
        top_bar.addSpacing(20)
        top_bar.addWidget(quality_label)
        top_bar.addWidget(self.quality_spinbox)
        top_bar.addStretch()

        self.make_convert_button: QPushButton = QPushButton("Convert")  # pyright: ignore[reportUninitializedInstanceVariable]
        top_bar.addWidget(self.make_convert_button)

        root_layout.addLayout(top_bar)

        # ---------- scrollable image grid ----------
        self.image_grid: ImageGridWidget = ImageGridWidget()  # pyright: ignore[reportUninitializedInstanceVariable]

        scroll_area = ResizingScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.image_grid)

        root_layout.addWidget(scroll_area)