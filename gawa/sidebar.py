# Contains shared row/label helpers and the per-format option builders

from __future__ import annotations
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLayout,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

MAX_FPS = {"gif": 50, "webp": 90, "avif": 90, "apng": 90}

# A bold label that separates sidebar sections
def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold;")
    return label

# A horizontal row of widgets with a trailing stretch
def option_row(*widgets: QWidget) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets: layout.addWidget(widget)
    layout.addStretch()
    return row

# Detach and delete every widget in a layout while leaving the layout intact
def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None: continue
        widget = item.widget()
        if widget is not None: widget.deleteLater()

# The sidebar with import, encoder, and other settings
class SidebarWidget(QFrame):
    def __init__(self, quality_spinbox: QSpinBox, speed_label: QLabel, speed_spinbox: QSpinBox,
    parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar_widget")
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setStyleSheet("QFrame#sidebar_widget { border: 1px solid black; }")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(section_label("Import settings"))

        self.resize_enabled: QCheckBox = QCheckBox("Resize:")
        self.resize_enabled.setToolTip("Set the output canvas size. A dimension of 0 preserves the canvas aspect ratio; 0 for both keeps its current size.")
        self.resize_width_label: QLabel = QLabel("Width:")
        self.resize_width_spinbox: QSpinBox = QSpinBox()
        self.resize_width_spinbox.setRange(0, 16384)
        self.resize_width_spinbox.setValue(0)
        self.resize_width_spinbox.setToolTip("Output canvas width in pixels. Set to 0 to derive it from Height.")
        self.resize_height_label: QLabel = QLabel("Height:")
        self.resize_height_spinbox: QSpinBox = QSpinBox()
        self.resize_height_spinbox.setRange(0, 16384)
        self.resize_height_spinbox.setValue(0)
        self.resize_height_spinbox.setToolTip("Output canvas height in pixels. Set to 0 to derive it from Width.")
        layout.addWidget(option_row(self.resize_enabled, self.resize_width_label, self.resize_width_spinbox,
            self.resize_height_label, self.resize_height_spinbox))
        for widget in (self.resize_width_label, self.resize_width_spinbox,
            self.resize_height_label, self.resize_height_spinbox):
            widget.setEnabled(False)
            _ = self.resize_enabled.toggled.connect(widget.setEnabled)

        self.frames_fps_label: QLabel = QLabel("Frames FPS:")
        self.frames_fps_spinbox: QDoubleSpinBox = QDoubleSpinBox()
        self.frames_fps_spinbox.setRange(0.01, 90)
        self.frames_fps_spinbox.setDecimals(2)
        self.frames_fps_spinbox.setSingleStep(1)
        self.frames_fps_spinbox.setValue(10)
        self.frames_fps_spinbox.setToolTip("Frame rate used for static images in an imported frame folder")

        self.video_fps_label: QLabel = QLabel("Video FPS:")
        self.video_fps_spinbox: QDoubleSpinBox = QDoubleSpinBox()
        self.video_fps_spinbox.setRange(0, 90)
        self.video_fps_spinbox.setDecimals(2)
        self.video_fps_spinbox.setSingleStep(1)
        self.video_fps_spinbox.setValue(0)
        self.video_fps_spinbox.setToolTip("Frame rate used when decoding video inputs. 0 uses the video's source frame rate. Does not affect image inputs")
        layout.addWidget(option_row(self.frames_fps_label, self.frames_fps_spinbox,
            self.video_fps_label, self.video_fps_spinbox))
        for widget in (self.frames_fps_label, self.frames_fps_spinbox,
            self.video_fps_label, self.video_fps_spinbox):
            widget.setEnabled(False)

        layout.addWidget(section_label("Encoder settings"))
        self._layout: QVBoxLayout = QVBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._layout)

        layout.addWidget(section_label("Other settings"))
        self.fit_to_canvas: QCheckBox = QCheckBox("Fit to canvas boundary")
        self.fit_to_canvas.setToolTip("Scale each frame up or down, preserving aspect ratio, to fit inside the output canvas.")
        self.center_frames: QCheckBox = QCheckBox("Center frames")
        self.center_frames.setToolTip("Center each frame on the output canvas; unused canvas area is transparent.")
        layout.addWidget(option_row(self.fit_to_canvas, self.center_frames))

        self.delay_speed_enabled: QCheckBox = QCheckBox("Speed:")
        self.delay_speed_enabled.setChecked(False)
        self.delay_speed_enabled.setToolTip("Enable changing frame delays for this conversion.")
        self.delay_speed_mode: QComboBox = QComboBox()
        self.delay_speed_mode.addItems(["Multiplier", "Custom fps"])
        self.delay_speed_mode.setCurrentText("Multiplier")
        self.delay_speed_mode.setToolTip("Multiply existing delays or replace them with a constant frame rate.")
        self.delay_speed_value: QDoubleSpinBox = QDoubleSpinBox()
        self.delay_speed_value.setDecimals(2)
        self.delay_speed_value.setSingleStep(0.1)
        self.delay_speed_value.setRange(0.01, 10)
        self.delay_speed_value.setValue(1)
        self.delay_speed_value.setToolTip("Multiplier applied to each existing frame delay")
        layout.addWidget(option_row(self.delay_speed_enabled, self.delay_speed_mode, self.delay_speed_value))
        for widget in (self.delay_speed_mode, self.delay_speed_value):
            widget.setVisible(self.delay_speed_enabled.isChecked())
            _ = self.delay_speed_enabled.toggled.connect(widget.setVisible)

        self.benchmarks_button: QPushButton = QPushButton("Benchmarks")
        layout.addWidget(option_row(self.benchmarks_button))
        layout.addStretch()

        self._quality_spinbox: QSpinBox = quality_spinbox
        self._speed_label: QLabel = speed_label
        self._speed_spinbox: QSpinBox = speed_spinbox
        self._saved_quality_value: int = quality_spinbox.value()
        self._current_format: str | None = None
        self._has_video = False
        self._has_static_frames = False
        self._frame_rate_conflict = False
        self.options: dict[str, QWidget] = {}
        _ = quality_spinbox.valueChanged.connect(self._remember_quality_value)
        _ = self.delay_speed_mode.currentTextChanged.connect(self._update_delay_speed_range)

    # Enable FPS controls when their inputs and encoder support them
    def update_fps_controls(self, has_video: bool | None = None, has_static_frames: bool | None = None,
    framerate_conflict: bool | None = None) -> None:
        if has_video is not None: self._has_video = has_video
        if has_static_frames is not None:  self._has_static_frames = has_static_frames
        if framerate_conflict is not None: self._frame_rate_conflict = framerate_conflict
        static_frames_enabled = self._has_static_frames and not self._frame_rate_conflict
        for widget in (self.frames_fps_label, self.frames_fps_spinbox): widget.setEnabled(static_frames_enabled)
        for widget in (self.video_fps_label, self.video_fps_spinbox): widget.setEnabled(self._has_video)

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
    def value(self, name: str) -> bool | int | float | str:
        widget = self.options.get(name)
        if widget is None: raise KeyError(f"Option {name!r} is not available for this format")
        if isinstance(widget, QCheckBox): return widget.isChecked()
        if isinstance(widget, QSpinBox):  return widget.value()
        if isinstance(widget, QComboBox): return widget.currentText()
        if isinstance(widget, QDoubleSpinBox): return widget.value()
        raise TypeError(f"Unsupported option widget for {name!r}: {type(widget).__name__}")

    # Copy current option values so conversion workers don't need to read Qt widgets
    def snapshot(self) -> dict[str, bool | int | float | str]:
        return {name: self.value(name) for name in self.options}

    def _update_delay_speed_range(self, _mode: str | None = None, reset_value: bool = True) -> None:
        if self.delay_speed_mode.currentText() == "Multiplier":
            self.delay_speed_value.setRange(0.01, 10)
            if reset_value: self.delay_speed_value.setValue(1)
            self.delay_speed_value.setToolTip("Multiplier applied to each existing frame delay")
            return

        fmt = self._current_format or "gif"
        max_fps = MAX_FPS.get(fmt, 90)
        self.delay_speed_value.setRange(0.01, max_fps)
        if reset_value: self.delay_speed_value.setValue(min(20, max_fps))
        self.delay_speed_value.setToolTip(f"Frame rate used to set frame delays. Maximum {max_fps} fps for {fmt.upper()}")

    # Clear and rebuild the row based on the output format
    def rebuild(self, fmt: str, deps: dict[str, bool]) -> None:
        if self._current_format == "apng":
            self._quality_spinbox.setValue(self._saved_quality_value)

        self._current_format = fmt
        max_fps = MAX_FPS.get(fmt, 90)
        self._update_delay_speed_range(reset_value=False)
        self.frames_fps_spinbox.setMaximum(max_fps)
        self.frames_fps_spinbox.setToolTip(f"Frame rate used for static images in an imported folder. Maximum {max_fps} fps for {fmt.upper()}")
        self.video_fps_spinbox.setMaximum(max_fps)
        self.video_fps_spinbox.setToolTip(f"Frame rate used when decoding video inputs. 0 uses the video's source frame rate. Maximum {max_fps} fps for {fmt.upper()}. Does not affect image inputs")
        clear_layout(self._layout)
        self.options = {}
        self.update_fps_controls(framerate_conflict=False)
        self._quality_spinbox.setEnabled(True)
        self._quality_spinbox.setToolTip("")
        self._speed_label.setEnabled(False)
        self._speed_spinbox.setEnabled(False)
        self._speed_spinbox.setToolTip("")

        if fmt == "gif":    self._build_gif(deps)
        elif fmt == "apng": self._build_apng(deps)
        elif fmt == "webp": self._build_webp(deps)
        elif fmt == "avif": self._build_avif(deps)

        self.options.update({
            "delay_speed_mode": self.delay_speed_mode,
            "delay_speed_value": self.delay_speed_value,
            "delay_speed_enabled": self.delay_speed_enabled,
            "resize_enabled": self.resize_enabled,
            "resize_width": self.resize_width_spinbox,
            "resize_height": self.resize_height_spinbox,
            "fit_to_canvas": self.fit_to_canvas,
            "center_frames": self.center_frames,
        })

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
        spin = QDoubleSpinBox()
        spin.setRange(0.01, MAX_FPS["gif"])
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setValue(20)
        spin.setToolTip("Maximum fps for gif is 50. Higher values don't play consistently across most browsers/image viewers")
        self._speed_spinbox.setToolTip("Speed is unavailable for GIF")

        self._layout.addWidget(option_row(gifski, use_ffmpeg, dither))
        delay_row = option_row(delay_label, combo, spin)
        gifski_speed_row = option_row(gifski_speed_label, gifski_speed)
        for row in (delay_row, gifski_speed_row):
            self._layout.addWidget(row)

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
            gifski_active = gifski.isChecked() and gifski_available
            ffmpeg_active = use_ffmpeg.isChecked() and ffmpeg_available
            if ffmpeg_active: self.update_fps_controls(framerate_conflict=True)

            gifski.setEnabled(gifski_available)
            use_ffmpeg.setEnabled(ffmpeg_available)
            dither.setVisible(ffmpeg_active)
            gifski_speed_row.setVisible(gifski_active)
            gifski.setToolTip(
                "Unavailable: gifski isn't installed" if not gifski_available
                else "Most efficient gif encoder but doesn't support variable frame delay and local color tables")
            use_ffmpeg.setToolTip(
                "Unavailable: ffmpeg isn't installed" if not ffmpeg_available
                else "Use ffmpeg's palettegen/paletteuse pipeline. Uses a single palette for the entire GIF")

            if gifski_active:
                use_ffmpeg.setChecked(False)
                use_ffmpeg.setEnabled(False)
            elif ffmpeg_active:
                gifski.setChecked(False)
                gifski.setEnabled(False)

            self._quality_spinbox.setEnabled(gifski_active)
            self._quality_spinbox.setToolTip(
                "Gifski quality (higher is better)" if gifski_active
                else "FFmpeg GIF encoding does not use quality" if ffmpeg_active
                else "Pillow and ffmpeg GIF encoding do not use quality. Use Gifski to adjust GIF quality")

            encoder_active = gifski_active or ffmpeg_active
            delay_row.setVisible(encoder_active)
            spin.setVisible(encoder_active and combo.currentText() == "Custom fps")
            if not ffmpeg_active:
                self.update_fps_controls(framerate_conflict=False)

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
                else "Speed is unavailable while apngasm is selected.")

        _ = use_apngasm.toggled.connect(update_speed_availability)
        update_speed_availability()

        # APNG is lossless so quality doesn't apply
        self._quality_spinbox.setEnabled(False)
        self._quality_spinbox.setValue(100)
        self._quality_spinbox.setToolTip("APNG is lossless. Quality is always 100.")

    def _build_webp(self, deps: dict[str, bool]) -> None:
        exact = QCheckBox("Use exact")
        exact.setToolTip("Preserve RGB values in fully transparent pixels")
        use_mixed = QCheckBox("Use mixed mode")
        use_mixed.setToolTip("Let pillow choose lossy or lossless compression per frame (slow)")
        self._layout.addWidget(option_row(exact, use_mixed))
        self.options["exact"] = exact
        self.options["use_mixed"] = use_mixed
        self.options["speed"] = self._speed_spinbox
        self._enable_speed(0, 6, 4, "Higher values are slower but may improve compression")

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
        custom_fps = QDoubleSpinBox()
        custom_fps.setRange(0.01, MAX_FPS["avif"])
        custom_fps.setDecimals(2)
        custom_fps.setSingleStep(0.1)
        custom_fps.setValue(20)
        custom_fps.setToolTip("Maximum fps for avif is 90. Higher values don't play consistently across most browsers/image viewers")

        self._layout.addWidget(option_row(subsampling_label, subsampling))
        self._layout.addWidget(option_row(use_ffmpeg, crf_label, crf))
        delay_row = option_row(delay_label, delay_mode, custom_fps)
        self._layout.addWidget(delay_row)

        self.options["subsampling"] = subsampling
        self.options["speed"] = self._speed_spinbox
        self.options["use_ffmpeg"] = use_ffmpeg
        self.options["crf"] = crf
        self.options["delay_mode"] = delay_mode
        self.options["custom_fps"] = custom_fps

        self._enable_speed(0, 10, 7, "Pillow speed: Higher values are faster")
        ffmpeg_available = deps["ffmpeg"]
        use_ffmpeg.setEnabled(ffmpeg_available)
        use_ffmpeg.setToolTip("Best size/quality/speed tradeoff, using libsvtav1. But doesn't support transparency and subsampling formats except yuv420p and yuv420p10le"
            if ffmpeg_available else "Unavailable: ffmpeg isn't installed")

        def update_constraints() -> None:
            ffmpeg_active = use_ffmpeg.isChecked() and ffmpeg_available
            if ffmpeg_active: self.update_fps_controls(framerate_conflict=True)

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
            delay_row.setVisible(ffmpeg_active)
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
                self.update_fps_controls(framerate_conflict=False)

        _ = use_ffmpeg.toggled.connect(update_constraints)
        _ = delay_mode.currentTextChanged.connect(update_constraints)
        update_constraints()
