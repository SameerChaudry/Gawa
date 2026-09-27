# The app is split into just main.py and qt_ui
# main.py handles the backend while qt_ui handles the gui

from __future__ import annotations
import subprocess
import shutil
import sys
from typing import Any
from PIL import Image
from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox
from qt_ui import Ui_MainWindow
import statistics

deps = {
    "gifski":   shutil.which("gifski") is not None,
    "apngasm":  shutil.which("apngasm") is not None,
    "img2webp": shutil.which("img2webp") is not None,
    "ffmpeg":   shutil.which("ffmpeg") is not None,
}

# Runs the conversion loop in a separate thread to avoid locking up the main thread
class ConversionWorker(QThread):
    log_message = Signal(str)

    def __init__(self, image_paths: list[Path], des_format: str, quality: int, options: dict[str, bool | int | str],
        output_dir: Path, parent: QObject | None = None) -> None:

        super().__init__(parent)
        self.image_paths = image_paths
        self.des_format = des_format
        self.quality = quality
        self.options = options
        self.output_dir = output_dir
        self.failures: list[str] = []

    def run(self) -> None:
        output_extension = "png" if self.des_format == "apng" else self.des_format
        reserved_outputs: set[Path] = set()
        frame_dir = Path("gawa_frames")

        for index, image_path in enumerate(self.image_paths, start=1):
            if self.isInterruptionRequested():
                self.log_message.emit("Conversion cancelled.")
                break

            output_path = MainWindow.unique_output_path(
                self.output_dir, image_path.stem, output_extension, reserved_outputs)
            self.log_message.emit(f"[{index}/{len(self.image_paths)}] Extracting {image_path.name}")

            try:
                delays, extracter = MainWindow.dump_frames(image_path, frame_dir)
                self.log_message.emit(f"Extracted {len(delays)} frames using {extracter}")
                self.log_message.emit(f"Converting {image_path.name}")
                encoder = MainWindow.assemble_frames(
                    self.des_format, self.quality, delays, output_path, self.options)
                self.log_message.emit(f"Saved to {output_path} using {encoder}")

            except (OSError, ValueError, subprocess.SubprocessError) as error:
                failure = f"{image_path.name}: {error}"
                self.failures.append(failure)
                self.log_message.emit(f"Failed {failure}")
                
            finally:
                shutil.rmtree(frame_dir, ignore_errors=True)

        if not self.failures and not self.isInterruptionRequested():
            self.log_message.emit("Conversion complete.")

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.output_dir: Path | None = None
        self.worker: ConversionWorker | None = None

        # underscore assignment just tells basedpyright that the returned connection object is useless
        _ = self.remove_button.clicked.connect(self.on_remove_clicked)
        _ = self.add_files_button.clicked.connect(self.on_add_files_clicked)
        _ = self.remove_all_button.clicked.connect(self.on_remove_all_clicked)
        _ = self.output_folder_button.clicked.connect(self.on_choose_output_folder_clicked)
        _ = self.make_convert_button.clicked.connect(self.on_make_convert_clicked)
        _ = self.format_dropdown.currentTextChanged.connect(self.on_format_changed)
        self.on_format_changed(self.format_dropdown.currentText())

    def on_add_files_clicked(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Select images", "", "Images (*.gif *.webp *.avif *.apng *.png)")
        for path_str in file_paths:
            self.image_grid.add_image(Path(path_str))

    def on_remove_clicked(self) -> None:
        self.image_grid.remove_selected()

    def on_remove_all_clicked(self) -> None:
        self.image_grid.remove_all()

    def on_choose_output_folder_clicked(self) -> None:
        start_dir = str(self.output_dir or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start_dir)
        if not folder:
            return

        self.output_dir = Path(folder)
        self.output_folder_button.setText(self.output_dir.name or str(self.output_dir))
        self.output_folder_button.setToolTip(str(self.output_dir))

    def on_format_changed(self, format_name: str) -> None:
        self.middle_bar.rebuild(format_name.lower(), deps)

    # Calculates an fps value using a list of delays or a custom delay value
    @staticmethod
    def get_fps(delays: list[int], options: dict[str, bool | int | str]) -> int:
        valid_delays = [delay for delay in delays if delay > 0]
        if not valid_delays:
            valid_delays = [100]

        delay_mode = options["delay_mode"]

        if delay_mode == "Average":
            delay_ms = sum(valid_delays) / len(valid_delays)
        elif delay_mode == "Mode":
            delay_ms = statistics.mode(valid_delays)
        elif delay_mode == "Custom":
            delay_ms = options["delay_ms"]
        else:
            raise ValueError(f"Unknown delay mode: {delay_mode}")

        return max(1, round(1000 / max(1, int(delay_ms))))

    # Extracts frames as pngs
    @staticmethod
    def dump_frames(image_path: Path, frame_dir: Path) -> tuple[list[int], str]:
        if frame_dir.exists(): shutil.rmtree(frame_dir)
        frame_dir.mkdir()
        with Image.open(image_path) as img:
            expected_frames = getattr(img, "n_frames", 1)
            delays_ms = []
            for frame_index in range(expected_frames):
                img.seek(frame_index)
                img.load()
                delays_ms.append(int(img.info.get("duration", 100) or 100))

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

        # Pillow fallback for when ffmpeg can't decode webp or has some other issue
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
    options: dict[str, bool | int | str]) -> str:
        frame_dir = Path("gawa_frames")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frames = [frame_dir / f"frame_{i:04d}.png" for i in range(len(delays))]

        if(des_format == "gif"):
            if(deps["gifski"] and options["use_gifski"]):
                fps = MainWindow.get_fps(delays, options)
                cmd = ["gifski", "--quality", str(quality), "--fps", str(fps), "-o", str(out_path)] + frames
                subprocess.run(cmd, check=True)
                return "gifski"

            else:
                imgs = [Image.open(f) for f in frames]
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0, 
                disposal=2, include_color_table=options["local_color_table"])
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
            if(deps["img2webp"] and options["use_img2webp"]):
                cmd = ["img2webp", "-loop", "0"]
                speed = options["speed"]
                mixed = options["use_mixed"]

                if mixed: cmd += ["-mixed", "-q", str(quality)]
                elif quality == 100: cmd += ["-lossless"]
                else: cmd += ["-lossy", "-q", str(quality)]

                cmd += ["-m", str(speed)]
                if options["sharp"] and (quality < 100 or mixed): cmd += ["-sharp_yuv"]
                
                for i, frame_path in enumerate(frames): cmd += ["-d", str(delays[i]), str(frame_path)]
                cmd += ["-o", str(out_path)]
                subprocess.run(cmd, check=True)
                return "img2webp"

            else:
                imgs = [Image.open(f) for f in frames]
                webp_quality_options: dict[str, Any] = {"lossless": True} if quality == 100 else {"quality": quality}
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
                method=options["speed"], **webp_quality_options)
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
                avif_quality_options: dict[str, Any] = {"lossless": True} if quality == 100 else {"quality": quality}
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
                method=speed, subsampling=subsampling, **avif_quality_options)
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
        self.make_convert_button.setEnabled(False)

        self.worker = ConversionWorker(image_paths, des_format, quality, options, self.output_dir, self)
        _ = self.worker.log_message.connect(self.log_output.appendPlainText)
        _ = self.worker.finished.connect(self.on_conversion_finished)
        self.worker.start()

    def on_conversion_finished(self) -> None:
        worker = self.worker
        failures = worker.failures if worker is not None else []
        self.make_convert_button.setEnabled(True)
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        if failures:
            QMessageBox.warning(self, "Some conversions failed",
                "The following files could not be converted:\n\n" + "\n".join(failures),)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
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