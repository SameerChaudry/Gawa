# The app is split into just main.py and qt_ui
# main.py handles the backend while qt_ui handles the gui

from __future__ import annotations
import subprocess
import shutil
import sys
import json
import tempfile
from fractions import Fraction
from typing import Any, cast
from PIL import Image
from pathlib import Path
from PySide6.QtCore import QObject, QSettings, QThread, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox
from qt_ui import Ui_MainWindow
from portal_dialog import choose_files_via_portal, choose_folder_via_portal
import statistics

deps = {
    "gifski":   shutil.which("gifski") is not None,
    "apngasm":  shutil.which("apngasm") is not None,
    "ffmpeg":   shutil.which("ffmpeg") is not None,
    "ffprobe":  shutil.which("ffprobe") is not None,
}

VIDEO_SUFFIXES = {
    ".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg",
    ".mpg", ".mts", ".ogv", ".ts", ".webm", ".wmv",
}

# Runs the conversion loop in a separate thread to avoid locking up the main thread
class ConversionWorker(QThread):
    log_message = Signal(str)

    def __init__(self, image_paths: list[Path], des_format: str, quality: int, options: dict[str, bool | int | str],
        output_dir: Path, video_fps: float, parent: QObject | None = None) -> None:

        super().__init__(parent)
        self.image_paths = image_paths
        self.des_format = des_format
        self.quality = quality
        self.options = options
        self.output_dir = output_dir
        self.video_fps = video_fps
        self.failures: list[str] = []

    def run(self) -> None:
        output_extension = "png" if self.des_format == "apng" else self.des_format
        reserved_outputs: set[Path] = set()

        # Iterates over all inputs to extract frames and encode them as the selected image format
        for index, image_path in enumerate(self.image_paths, start=1):
            if self.isInterruptionRequested():
                self.log_message.emit("Conversion cancelled.")
                break

            # Renames inputs with same name to avoid silent overwrites
            output_path = MainWindow.unique_output_path(
                self.output_dir, image_path.stem, output_extension, reserved_outputs)
            self.log_message.emit(f"[{index}/{len(self.image_paths)}] Extracting {image_path.name}")

            # Extracts image frames using pillow and video frames using ffmpeg and ffprobe (if available in PATH)
            try:
                with tempfile.TemporaryDirectory(prefix="gawa-frames-") as temp_dir:
                    frame_dir = Path(temp_dir)
                    delays, extracter = MainWindow.dump_frames(image_path, frame_dir, self.video_fps)
                    if self.des_format == "gif":
                        adjusted_delays = sum(delay < 20 for delay in delays)
                        if adjusted_delays:
                            delays = [20 if delay < 20 else delay for delay in delays]
                            self.log_message.emit(f"Warning: Adjusted {adjusted_delays} frame delay(s) below 20 ms to 20 ms to avoid unintended behavior when playing back the gif")
                    self.log_message.emit(f"Extracted {len(delays)} frames using {extracter}")
                    self.log_message.emit(f"Converting {image_path.name}")

                    # Encodes the selected image format using the extracted png frames
                    encoder = MainWindow.assemble_frames(self.des_format, self.quality, delays, output_path, self.options, frame_dir)
                    self.log_message.emit(f"Saved to {output_path} using {encoder}")

            except (OSError, ValueError, subprocess.SubprocessError) as error:
                failure = f"{image_path.name}: {error}"
                self.failures.append(failure)
                self.log_message.emit(f"Failed {failure}")

        if not self.failures and not self.isInterruptionRequested():
            self.log_message.emit("Conversion complete.")

class MainWindow(QMainWindow, Ui_MainWindow):
    log_message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.set_video_suffixes(VIDEO_SUFFIXES)
        self.settings = QSettings("Gawa", "Gawa")
        saved_output_dir = cast(str, self.settings.value("output_dir", "", type=str))
        saved_path = Path(saved_output_dir).expanduser() if saved_output_dir else None
        self.output_dir = saved_path if saved_path is not None and saved_path.is_dir() else None
        self.worker: ConversionWorker | None = None

        if self.output_dir is not None:
            self.output_folder_button.setText(self.output_dir.name or str(self.output_dir))
            self.output_folder_button.setToolTip(str(self.output_dir))

        # underscore assignment just tells basedpyright that the returned connection object is useless
        _ = self.log_message.connect(self.log_output.appendPlainText)
        _ = self.remove_button.clicked.connect(self.on_remove_clicked)
        _ = self.add_files_button.clicked.connect(self.on_add_files_clicked)
        _ = self.remove_all_button.clicked.connect(self.on_remove_all_clicked)
        _ = self.make_convert_button.clicked.connect(self.on_make_convert_clicked)
        _ = self.format_dropdown.currentTextChanged.connect(self.on_format_changed)
        _ = self.middle_bar.benchmarks_button.clicked.connect(self.on_benchmarks_clicked)
        _ = self.output_folder_button.clicked.connect(self.on_choose_output_folder_clicked)
        self.on_format_changed(self.format_dropdown.currentText())

    def on_add_files_clicked(self) -> None:
        file_paths = choose_files_via_portal("Select images and videos")
        if file_paths is None:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self, "Select images and videos", "",
                "Media (*.gif *.webp *.avif *.apng *.png *.jpg *.jpeg *.mp4 *.mkv *.mov *.avi *.webm *.flv *.wmv *.mpeg *.mpg *.m4v *.ts *.mts *.3gp *.ogv)"
            )
            file_paths = [Path(path_str) for path_str in file_paths]
        for file_path in file_paths:
            self.image_grid.add_image(file_path)

    def on_remove_clicked(self) -> None:
        self.image_grid.remove_selected()

    def on_remove_all_clicked(self) -> None:
        self.image_grid.remove_all()

    # Tries to use the native file dialog portal via DBus for linux and
    # falls back to native qt file dialog on failure, cancel or on Windows
    def on_choose_output_folder_clicked(self) -> None:
        start_dir = str(self.output_dir or Path.home())
        folder = choose_folder_via_portal("Choose output folder")

        if folder is None:
            chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", start_dir)
            folder = Path(chosen) if chosen else None
        if folder is None: return

        self.output_dir = Path(folder)
        self.settings.setValue("output_dir", str(self.output_dir))
        self.output_folder_button.setText(self.output_dir.name or str(self.output_dir))
        self.output_folder_button.setToolTip(str(self.output_dir))

    # Rebuilds the middle bar to show different configuration options when the selected format changes
    def on_format_changed(self, format_name: str) -> None:
        self.middle_bar.rebuild(format_name.lower(), deps)

    def on_benchmarks_clicked(self) -> None:
        des_format = self.format_dropdown.currentText().lower()
        self.log_message.emit("These are just the results from testing 263 254x450 png frames of a flat color animation using different encoding options for each of the 4 formats. Don't take these too literally as these are provided just for reference, because different encoders support different inputs, work better for specific kinds of content, have certain limitations, etc")
        if des_format == "gif":
            self.log_message.emit("""GIF Benchmarks
Encoder  Quality  Speed    Time    Size     Min VMAF  Mean VMAF  Features
Pillow   n/a      n/a      1.27 s  7.60 MB  94.70     99.57      Global color table made by sampling 66 frames of the animation; no dithering; disposal=2
Pillow   n/a      n/a      0.87 s  4.04 MB  94.81     99.14      Local color table (default); disposal=2
gifski   80       --fast   6.91 s  4.51 MB  95.68     99.40      --fast
gifski   80       default  8.41 s  4.42 MB  95.58     99.40      Default
gifski   80       --extra  14.56 s 4.33 MB  94.83     99.35      --extra
ffmpeg   n/a      n/a      1.03 s  6.90 MB  96.55     99.61      palettegen=stats_mode=diff + paletteuse=dither=none
ffmpeg   n/a      n/a      2.28 s  7.95 MB  96.39     99.55      palettegen=stats_mode=diff + paletteuse=dither=sierra2_4a""")
        elif des_format == "apng":
            self.log_message.emit("""APNG Benchmarks
Encoder  Quality   Speed       Time     Size       Min VMAF  Mean VMAF  Features
Pillow   lossless  compress=0  1.21 s   120.42 MB  97.43     99.77      Disposal=background; blend=source
Pillow   lossless  compress=6  3.26 s   16.99 MB   97.43     99.77      Disposal=background; blend=source
Pillow   lossless  compress=9  12.62 s  16.76 MB   97.43     99.77      Disposal=background; blend=source
apngasm  lossless  default     25.00 s  14.18 MB   97.43     99.77      Default settings""")
        elif des_format == "webp":
            self.log_message.emit("""WebP Benchmarks
Encoder   Quality  Speed  Time     Size     Min VMAF  Mean VMAF  Features
Pillow    80       0      1.45 s   2.72 MB  95.16     99.31      Lossy
Pillow    80       4      3.63 s   1.94 MB  95.10     99.29      Lossy
Pillow    80       6      81.84 s  1.93 MB  95.19     99.37      Lossy
Pillow    80       4      3.63 s   1.94 MB  95.10     99.29      Lossy, exact=True

Note: The exact=true result is identical to exact=false (default) because the tested animation was opaque with no transparent pixels, and exact=true only affects images with fully transparent pixels""")

        elif des_format == "avif":
            self.log_message.emit("""AVIF Benchmarks
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
ffmpeg   CRF 35   1      134.37 s   438.94 KB  93.56     98.45      libsvtav1""")

    # Calculates an fps value using a list of delays or a custom delay value
    @staticmethod
    def get_fps(delays: list[int], options: dict[str, bool | int | str]) -> int:
        valid_delays = [delay for delay in delays if delay > 0]
        if not valid_delays: valid_delays = [100]

        delay_mode = options["delay_mode"]

        if delay_mode == "Average":  delay_ms = sum(valid_delays) / len(valid_delays)
        elif delay_mode == "Mode":   delay_ms = statistics.mode(valid_delays)
        elif delay_mode == "Custom": delay_ms = options["delay_ms"]
        else: raise ValueError(f"Unknown delay mode: {delay_mode}")

        return max(1, round(1000 / max(1, int(delay_ms))))

    # Extracts animation frames as individual pngs
    @staticmethod
    def dump_frames(image_path: Path, frame_dir: Path, video_fps: float = 0) -> tuple[list[int], str]:
        if frame_dir.exists(): shutil.rmtree(frame_dir)
        frame_dir.mkdir()

        if image_path.suffix.lower() in VIDEO_SUFFIXES:
            if not deps["ffmpeg"] or not deps["ffprobe"]:
                raise ValueError("Both ffmpeg and ffprobe need to be in PATH for processing video inputs")

            # Uses ffprobe to get the source video fps
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                "-of", "json", str(image_path)], check=True, capture_output=True, text=True)
            streams = json.loads(probe.stdout).get("streams", [])
            if not streams: raise ValueError("No video stream was found.")

            source_fps: Fraction | None = None
            for rate_name in ("avg_frame_rate", "r_frame_rate"):
                rate_text = streams[0].get(rate_name, "")
                try:
                    rate = Fraction(rate_text)
                except (ValueError, ZeroDivisionError):
                    continue
                if rate > 0:
                    source_fps = rate
                    break
            if source_fps is None: raise ValueError("Could not determine the video's source frame rate.")
            fps = source_fps if video_fps == 0 else Fraction(str(video_fps))
            frame_dir.mkdir(exist_ok=True)

            # Uses source fps or custom fps for extracting frames
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(image_path), "-vf", f"fps={fps}", "-fps_mode", "passthrough",
                "-start_number", "0", str(frame_dir / "frame_%04d.png")], check=True, capture_output=True)
            extracted = sorted(frame_dir.glob("frame_*.png"))
            if not extracted: raise ValueError("No video frames were decoded.")

            frame_rate = float(fps)
            delays_ms = [max(1, round((index + 1) * 1000 / frame_rate) - round(index * 1000 / frame_rate))
                for index in range(len(extracted))]
            return delays_ms, f"ffmpeg ({frame_rate:g} fps)"

        # Get animated image delay
        with Image.open(image_path) as img:
            expected_frames = getattr(img, "n_frames", 1)
            delays_ms = []
            for frame_index in range(expected_frames):
                img.seek(frame_index)
                img.load()
                delays_ms.append(int(img.info.get("duration", 100) or 100))

        # Extract animated image frames using ffmpeg if available
        # FFmpeg 9 seemed to only write a single frame for every tested avif for some reason 
        if deps["ffmpeg"] and image_path.suffix.lower() != ".avif":
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(image_path), "-fps_mode", "passthrough", 
                    str(frame_dir / "frame_%04d.png")], check=True, capture_output=True)
                extracted = sorted(frame_dir.glob("frame_*.png"))
                if len(extracted) == expected_frames:
                    for index, frame in enumerate(extracted):
                        frame.rename(frame_dir / f"frame_{index:04d}.png")
                    return delays_ms, "ffmpeg"

            except (OSError, subprocess.SubprocessError): pass

        # Pillow fallback for extracting frames if avif or if ffmpeg fails for some reason
        shutil.rmtree(frame_dir)
        frame_dir.mkdir()
        delays_ms = []
        with Image.open(image_path) as img:
            for frame_index in range(getattr(img, "n_frames", 1)):
                img.seek(frame_index)
                img.convert("RGBA").save(frame_dir / f"frame_{frame_index:04d}.png", format="PNG")
                delays_ms.append(int(img.info.get("duration", 100) or 100))
        return delays_ms, "pillow"

    # Encodes animations using a directory of frames and list of delays
    @staticmethod
    def assemble_frames(des_format: str, quality: int, delays: list[int], out_path: Path,
    options: dict[str, bool | int | str], frame_dir: Path) -> str:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frames = [frame_dir / f"frame_{i:04d}.png" for i in range(len(delays))]

        if(des_format == "gif"):
            if(deps["gifski"] and options["use_gifski"] and len(frames) > 1):
                fps = MainWindow.get_fps(delays, options)
                cmd = ["gifski", "--quality", str(quality), "--fps", str(fps)]
                if options["gifski_speed"] == "Fast": cmd += ["--fast"]
                elif options["gifski_speed"] == "Extra": cmd += ["--extra"]
                cmd += ["-o", str(out_path)] + frames
                subprocess.run(cmd, check=True)
                return "gifski"

            elif(deps["ffmpeg"] and options["use_ffmpeg"] and len(frames) > 1):
                fps = MainWindow.get_fps(delays, options)
                input_pattern = str(frame_dir / "frame_%04d.png")
                dither = "sierra2_4a" if options["dither"] else "none"
                subprocess.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern, "-vf",
                    "palettegen=stats_mode=diff", "-update", "1", str(frame_dir / "palette.png")], check=True)
                subprocess.run(['ffmpeg','-y','-framerate', str(fps),'-i', input_pattern, '-i', str(frame_dir / "palette.png"),
                    '-lavfi', f'paletteuse=dither={dither}', '-r', str(fps), str(out_path)], check=True)
                return "ffmpeg"

            # Use pillow for the gif encode. Uses local color table for every frame by default
            # which is not supported by both gifski and ffmpeg
            else:
                imgs = [Image.open(f) for f in frames]
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,  disposal=2)
                return "pillow"

        if(des_format == "apng"):
            if(deps["apngasm"] and options["use_apngasm"]):
                cmd = ["apngasm", "-o", str(out_path)]
                
                for frame_path, delay in zip(frames, delays):
                    cmd += [str(frame_path), str(delay)]
                cmd += ["-F"]
                subprocess.run(cmd, check=True)
                return "apngasm"

            else:
                imgs = [Image.open(f) for f in frames]
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
                    disposal=1, compress_level=options["speed"])
                return "pillow"

        if(des_format == "webp"):
            imgs = [Image.open(f) for f in frames]
            webp_quality_options: dict[str, Any] = {"lossless": True} if quality == 100 else {"quality": quality}
            imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0, method=options["speed"],
                exact=options["exact"], allow_mixed=options["use_mixed"], **webp_quality_options)
            return "pillow"
            
        if(des_format == "avif"):
            speed = options["speed"]
            subsampling = str(options["subsampling"])

            if(deps["ffmpeg"] and options["use_ffmpeg"]):
                fps = MainWindow.get_fps(delays, options)
                pixel_format = subsampling
                crf = str(options["crf"])
                input_pattern = str(frame_dir / "frame_%04d.png")

                subprocess.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern, "-vf", "scale=in_range=full:out_range=full",
                "-c:v", "libsvtav1", "-preset", str(speed), "-crf", crf, "-pix_fmt", pixel_format, "-color_range", "2",
                "-f", "avif", "-loop", "0", str(out_path)], check=True)
                return "ffmpeg"

            else:
                imgs = [Image.open(f) for f in frames]
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays,
                    speed=speed, subsampling=subsampling, quality=quality)
                return "pillow"
        
        else:
            raise ValueError(f"Invalid output format: {des_format}")

    # Use a unique filename suffix to avoid rewriting output files
    @staticmethod
    def unique_output_path(output_dir: Path, stem: str, extension: str, reserved: set[Path]) -> Path:
        candidate = output_dir / f"{stem}.{extension}"
        suffix = 1
        while candidate.exists() or candidate in reserved:
            candidate = output_dir / f"{stem}-{suffix}.{extension}"
            suffix += 1

        reserved.add(candidate)
        return candidate

    def on_make_convert_clicked(self) -> None:
        image_paths = self.image_grid.get_file_paths()
        if not image_paths: return

        if self.output_dir is None:
            self.on_choose_output_folder_clicked()
            if self.output_dir is None: return

        des_format = self.format_dropdown.currentText().lower()
        quality = self.quality_spinbox.value()
        options = self.middle_bar.snapshot()
        video_fps = self.middle_bar.video_fps_spinbox.value()
        self.make_convert_button.setEnabled(False)

        self.worker = ConversionWorker(image_paths, des_format, quality, options, self.output_dir, video_fps, self)
        _ = self.worker.log_message.connect(self.log_output.appendPlainText)
        _ = self.worker.finished.connect(self.on_conversion_finished)
        self.worker.start()

    def on_conversion_finished(self) -> None:
        worker = self.worker
        failures = worker.failures if worker is not None else []
        self.make_convert_button.setEnabled(True)
        self.worker = None
        if worker is not None: worker.deleteLater()
        if failures:
            QMessageBox.warning(self, "Some conversions failed", "The following files could not be converted:\n\n" + "\n".join(failures),)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        super().closeEvent(event)

def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()