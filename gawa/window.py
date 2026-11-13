# The Ui_MainWindow layout and the MainWindow controller for the main window

from __future__ import annotations
from pathlib import Path
from typing import cast
from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget)
from gawa.config import deps
from gawa.conversion import ConversionBatch, ConversionSnapshot, ConversionWorker, FrameCache
from gawa.dialogs import choose_files, choose_frame_folder, choose_output_folder
from gawa.extraction import FRAME_SUFFIXES, VIDEO_SUFFIXES, get_frame_files, inspect_inputs
from gawa.grid import ImageGridWidget, ResizingScrollArea
from gawa.sidebar import SidebarWidget

BENCHMARK_INTRO = "These are just the results from testing 263 254x450 png frames of a flat color animation using different encoding options for each of the 4 formats. Don't take these too literally as these are provided just for reference, because different encoders support different inputs, work better for specific kinds of content, have certain limitations, etc. For more details, read benchmarks.md"

BENCHMARKS = {
    "gif": """GIF Benchmarks
Encoder  Quality  Speed    Time    Size     Min VMAF  Mean VMAF  Features
Pillow   n/a      n/a      1.27 s  7.60 MB  94.70     99.57      Global color table made by sampling 66 frames of the animation; no dithering; disposal=2
Pillow   n/a      n/a      0.87 s  4.04 MB  94.81     99.14      Local color table (default); disposal=2
gifski   80       --fast   6.91 s  4.51 MB  95.68     99.40      --fast
gifski   80       default  8.41 s  4.42 MB  95.58     99.40      Default
gifski   80       --extra  14.56 s 4.33 MB  94.83     99.35      --extra
ffmpeg   n/a      n/a      1.03 s  6.90 MB  96.55     99.61      palettegen=stats_mode=diff + paletteuse=dither=none
ffmpeg   n/a      n/a      2.28 s  7.95 MB  96.39     99.55      palettegen=stats_mode=diff + paletteuse=dither=sierra2_4a""",
    "apng": """APNG Benchmarks
Encoder  Quality   Speed       Time     Size       Min VMAF  Mean VMAF  Features
Pillow   lossless  compress=0  1.21 s   120.42 MB  97.43     99.77      Disposal=background; blend=source
Pillow   lossless  compress=6  3.26 s   16.99 MB   97.43     99.77      Disposal=background; blend=source
Pillow   lossless  compress=9  12.62 s  16.76 MB   97.43     99.77      Disposal=background; blend=source
apngasm  lossless  default     25.00 s  14.18 MB   97.43     99.77      Default settings""",
    "webp": """WebP Benchmarks
Encoder   Quality  Speed  Time     Size     Min VMAF  Mean VMAF  Features
Pillow    80       0      1.45 s   2.72 MB  95.16     99.31      Lossy
Pillow    80       4      3.63 s   1.94 MB  95.10     99.29      Lossy
Pillow    80       6      81.84 s  1.93 MB  95.19     99.37      Lossy
Pillow    80       4      3.63 s   1.94 MB  95.10     99.29      Lossy, exact=True

Note: The exact=true result is identical to exact=false (default) because the tested animation was opaque with no transparent pixels, and exact=true only affects images with fully transparent pixels""",
    "avif": """AVIF Benchmarks
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

Note: The ffmpeg method uses libsvtav1 for significantly better efficiency compared to pillow's default libaom AV1 encoder. But libsvtav1 doesn't support transparency and subsampling formats except yuv420p and yuv420p10le""",
}

# The main window's layout and widgets. Only the internal layout is built here
# The controller wires signals in MainWindow.__init__
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

        # The top bar
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

        self.make_convert_button: QToolButton = QToolButton()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.make_convert_button.setText("Convert (0)")
        self.make_convert_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.convert_menu: QMenu = QMenu(self.make_convert_button)  # pyright: ignore[reportUninitializedInstanceVariable]
        self.add_to_queue_action: QAction = self.convert_menu.addAction("Add to queue")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.clear_queue_action: QAction = self.convert_menu.addAction("Clear queue")  # pyright: ignore[reportUninitializedInstanceVariable]
        self.make_convert_button.setMenu(self.convert_menu)
        top_bar.addWidget(self.make_convert_button)

        root_layout.addLayout(top_bar)

        # The sidebar
        self.sidebar: SidebarWidget = SidebarWidget(self.quality_spinbox, self.speed_label, self.speed_spinbox)  # pyright: ignore[reportUninitializedInstanceVariable]

        # The scrollable image grid
        self.image_grid: ImageGridWidget = ImageGridWidget()  # pyright: ignore[reportUninitializedInstanceVariable]

        scroll_area = ResizingScrollArea()
        scroll_area.setObjectName("grid_area")
        scroll_area.setStyleSheet("QScrollArea#grid_area { border: 1px solid black; }")
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.image_grid)

        self.log_output: QPlainTextEdit = QPlainTextEdit()  # pyright: ignore[reportUninitializedInstanceVariable]
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(1000)
        log_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
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

        self.main_splitter: QSplitter = QSplitter(Qt.Orientation.Horizontal)  # pyright: ignore[reportUninitializedInstanceVariable]
        self.main_splitter.setChildrenCollapsible(True)
        self.main_splitter.setHandleWidth(6)
        self.main_splitter.addWidget(self.content_splitter)
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, True)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        sidebar_width = self.sidebar.sizeHint().width()
        self.main_splitter.setSizes([MainWindow.width() - sidebar_width, sidebar_width])

        root_layout.addWidget(self.main_splitter, 1)

class MainWindow(QMainWindow, Ui_MainWindow):
    log_message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        _ = self.image_grid.contents_changed.connect(self.update_fps_controls)
        self.setAcceptDrops(True)
        self.set_video_suffixes(VIDEO_SUFFIXES)
        self.settings = QSettings("Gawa", "Gawa")
        saved_output_dir = cast(str, self.settings.value("output_dir", "", type=str))
        saved_path = Path(saved_output_dir).expanduser() if saved_output_dir else None
        self.output_dir = saved_path if saved_path is not None and saved_path.is_dir() else None
        self.worker: ConversionWorker | None = None
        self.conversion_queue: list[ConversionSnapshot] = []
        self.conversion_batch: ConversionBatch | None = None
        self.frame_cache = FrameCache()

        if self.output_dir is not None:
            self.output_folder_button.setText(self.output_dir.name or str(self.output_dir))
            self.output_folder_button.setToolTip(str(self.output_dir))

        # underscore assignment just tells basedpyright that the returned connection object is useless
        _ = self.log_message.connect(self.log_output.appendPlainText)
        _ = self.add_files_button.clicked.connect(self.on_add_files_clicked)
        _ = self.add_folder_button.clicked.connect(self.on_add_folder_clicked)
        _ = self.remove_all_button.clicked.connect(self.on_remove_all_clicked)
        _ = self.make_convert_button.clicked.connect(self.on_make_convert_clicked)
        _ = self.clear_queue_action.triggered.connect(self.on_clear_queue_clicked)
        _ = self.format_dropdown.currentTextChanged.connect(self.on_format_changed)
        _ = self.add_to_queue_action.triggered.connect(self.on_add_to_queue_clicked)
        _ = self.sidebar.benchmarks_button.clicked.connect(self.on_benchmarks_clicked)
        _ = self.output_folder_button.clicked.connect(self.on_choose_output_folder_clicked)

        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        _ = self.delete_shortcut.activated.connect(self.image_grid.remove_selected)
        self.backspace_shortcut = QShortcut(QKeySequence("Backspace"), self)
        self.backspace_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        _ = self.backspace_shortcut.activated.connect(self.image_grid.remove_selected)
        self.on_format_changed(self.format_dropdown.currentText())

    def set_video_suffixes(self, suffixes: set[str]) -> None:
        self.image_grid.set_video_suffixes(suffixes)

    # Enable "Video FPS" and "Frames FPS" when frames or videos are present in a directory
    def update_fps_controls(self) -> None:
        has_video, has_static_frames = inspect_inputs(self.image_grid.get_file_paths(), VIDEO_SUFFIXES)
        self.sidebar.update_fps_controls(has_video=has_video, has_static_frames=has_static_frames)

    def on_add_files_clicked(self) -> None:
        for file_path in choose_files(self): self.image_grid.add_image(file_path)

    # Allows drag and drop for importing files and folders
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

    # Import files/folders passed from the command line (or when using "Open with") when launching
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
    # falls back to native qt file dialog on failure, cancel or if on Windows
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
        self.log_message.emit(BENCHMARK_INTRO)
        benchmark = BENCHMARKS.get(des_format)
        if benchmark is not None: self.log_message.emit(benchmark)

    def _capture_conversion_snapshot(self) -> ConversionSnapshot | None:
        image_paths = self.image_grid.get_file_paths()
        if not image_paths: return None

        if self.output_dir is None:
            self.on_choose_output_folder_clicked()
            if self.output_dir is None: return None

        return ConversionSnapshot(
            image_paths=tuple(image_paths),
            des_format=self.format_dropdown.currentText().lower(),
            quality=self.quality_spinbox.value(),
            options=self.sidebar.snapshot(),
            output_dir=self.output_dir,
            video_fps=self.sidebar.video_fps_spinbox.value(),
            frames_fps=self.sidebar.frames_fps_spinbox.value(),
        )

    def on_add_to_queue_clicked(self) -> None:
        snapshot = self._capture_conversion_snapshot()
        if snapshot is None: return
        self.conversion_queue.append(snapshot)
        self.make_convert_button.setText(f"Convert ({len(self.conversion_queue)})")
        self.log_message.emit(f"Added queue operation {len(self.conversion_queue)}: {snapshot.des_format.upper()} ({len(snapshot.image_paths)} input(s))")

    def on_clear_queue_clicked(self) -> None:
        self.conversion_queue.clear()
        self.make_convert_button.setText("Convert (0)")
        self.log_message.emit("Queue cleared.")

    def on_make_convert_clicked(self) -> None:
        from_queue = bool(self.conversion_queue)
        if from_queue: jobs = list(self.conversion_queue)
        else:
            snapshot = self._capture_conversion_snapshot()
            if snapshot is None: return
            jobs = [snapshot]

        self.conversion_batch = ConversionBatch(jobs, from_queue)
        self.make_convert_button.setEnabled(False)
        self._start_next_conversion_job()

    def _start_next_conversion_job(self) -> None:
        batch = self.conversion_batch
        if batch is None: return
        snapshot = batch.jobs[batch.index]
        if batch.from_queue:
            self.log_message.emit(f"Queue operation {batch.index + 1}/{len(batch.jobs)}: {snapshot.des_format.upper()} ({len(snapshot.image_paths)} input(s))")

        self.worker = ConversionWorker(snapshot, self, self.frame_cache)
        _ = self.worker.log_message.connect(self.log_output.appendPlainText)
        _ = self.worker.finished.connect(self.on_conversion_finished)
        self.worker.start()

    def on_conversion_finished(self) -> None:
        batch, worker = self.conversion_batch, self.worker
        if batch is None or worker is None: return

        prefix = f"Queue operation {batch.index + 1}: " if batch.from_queue else ""
        batch.failures.extend(prefix + failure for failure in worker.failures)
        batch.index += 1
        self.worker = None
        worker.deleteLater()

        if batch.index < len(batch.jobs):
            self._start_next_conversion_job()
            return

        self.conversion_batch = None
        self.make_convert_button.setEnabled(True)
        if batch.failures:
            QMessageBox.warning(self, "Some conversions failed",
                "The following files could not be converted:\n\n" + "\n".join(batch.failures))

    # If user tries to close the window during a conversion, it will close after the current input is converted
    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        self.frame_cache.close()
        super().closeEvent(event)
