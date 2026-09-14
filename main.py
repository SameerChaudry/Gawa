# The app is split into just main.py and qt_ui
# main.py handles the backend while qt_ui handles the gui

from __future__ import annotations
import subprocess
import shutil
import sys
from typing import Any
from PIL import Image
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox
from qt_ui import Ui_MainWindow
import statistics

deps = {
    "gifski":   shutil.which("gifski") is not None,
    "apngasm":  shutil.which("apngasm") is not None,
    "img2webp": shutil.which("img2webp") is not None,
    "ffmpeg":   shutil.which("ffmpeg") is not None
}

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.output_dir: Path | None = None

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

    def get_fps(self, delays: list[int]) -> int:
        valid_delays = [delay for delay in delays if delay > 0]
        if not valid_delays:
            valid_delays = [100]

        delay_mode = self.middle_bar.value("delay_mode")

        if delay_mode == "Average":
            delay_ms = sum(valid_delays) / len(valid_delays)
        elif delay_mode == "Mode":
            delay_ms = statistics.mode(valid_delays)
        elif delay_mode == "Custom":
            delay_ms = self.middle_bar.value("delay_ms")
        else:
            raise ValueError(f"Unknown delay mode: {delay_mode}")

        return max(1, round(1000 / max(1, int(delay_ms))))

    def dump_frames(self, image_path: Path) -> list[int]:
        frame_dir = Path("gawa_frames")
        if frame_dir.exists(): shutil.rmtree(frame_dir)
        frame_dir.mkdir()
        delays_ms = []

        with Image.open(image_path) as img:
            frame_count = getattr(img, "n_frames", 1)
            for frame_index in range(frame_count):
                img.seek(frame_index)
                frame = img.convert("RGBA")
                frame.save(frame_dir / f"frame_{frame_index:04d}.png", format="PNG")
                delays_ms.append(int(img.info.get("duration", 0) or 0))

        return delays_ms

    def assemble_frames(self, des_format, quality, delays, out_path: Path) -> None:
        frame_dir = Path("gawa_frames")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frames = [frame_dir / f"frame_{i:04d}.png" for i in range(len(delays))]

        if(des_format == "gif"):
            if(deps["gifski"] and self.middle_bar.value("use_gifski")):
                fps = self.get_fps(delays)
                frame_paths = [str(frame_dir / f"frame_{i:04d}.png") for i in range(len(delays))]
                cmd = ["gifski", "--quality", str(quality), "--fps", str(fps), "-o", str(out_path)] + frames
                subprocess.run(cmd, check=True)

            else:
                imgs = [Image.open(f) for f in frames]
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0, 
                disposal=2, include_color_table=self.middle_bar.value("local_color_table"))

        if(des_format == "apng"):
            if(deps["apngasm"] and self.middle_bar.value("use_apngasm")):
                cmd = ["apngasm", "-o", str(out_path)]
                
                for frame_path, delay in zip(frames, delays):
                    cmd += [str(frame_path), str(delay)]
                cmd += ["-F"]
                subprocess.run(cmd, check=True)

            else:
                imgs = [Image.open(f) for f in frames]
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
                disposal=1, compress_level=self.middle_bar.value("speed"))

        if(des_format == "webp"):
            if(deps["img2webp"] and self.middle_bar.value("use_img2webp")):
                cmd = ["img2webp", "-loop", "0"]
                speed = self.middle_bar.value("speed")
                mixed = self.middle_bar.value("use_mixed")

                if mixed:
                    cmd += ["-mixed", "-q", str(quality)]
                elif quality == 100: cmd += ["-lossless"]
                else: cmd += ["-lossy", "-q", str(quality)]

                # img2webp's method range matches the speed control (0..6).
                cmd += ["-m", str(speed)]
                if self.middle_bar.value("sharp") and (quality < 100 or mixed):
                    cmd += ["-sharp_yuv"]
                
                for i, frame_path in enumerate(frames): cmd += ["-d", str(delays[i]), str(frame_path)]
                cmd += ["-o", str(out_path)]
                subprocess.run(cmd, check=True)

            else:
                imgs = [Image.open(f) for f in frames]
                webp_quality_options: dict[str, Any] = {"lossless": True} if quality == 100 else {"quality": quality}
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
                method=self.middle_bar.value("speed"), **webp_quality_options)

        if(des_format == "avif"):
            speed = self.middle_bar.value("speed")
            subsampling = str(self.middle_bar.value("subsampling"))

            if(deps["ffmpeg"] and self.middle_bar.value("use_ffmpeg")):
                fps = self.get_fps(delays)
                pixel_format = subsampling
                crf = str(self.middle_bar.value("crf"))
                input_pattern = str(frame_dir / "frame_%04d.png")

                subprocess.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern, "-vf", "scale=in_range=full:out_range=full",
                "-c:v", "libsvtav1", "-preset", str(speed), "-crf", crf, "-pix_fmt", pixel_format, "-color_range", "2",
                "-f", "avif", "-loop", "0", str(out_path)], check=True)

            else:
                imgs = [Image.open(f) for f in frames]
                avif_quality_options: dict[str, Any] = {"lossless": True} if quality == 100 else {"quality": quality}
                imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
                method=speed, subsampling=subsampling, **avif_quality_options)

        shutil.rmtree(frame_dir)

    def unique_output_path(self, stem: str, extension: str, reserved: set[Path]) -> Path:
        """Choose a non-overwriting output name, suffixing duplicates as -1, -2, ..."""
        if self.output_dir is None:
            raise RuntimeError("Output directory has not been selected")

        candidate = self.output_dir / f"{stem}.{extension}"
        suffix = 1
        while candidate.exists() or candidate in reserved:
            candidate = self.output_dir / f"{stem}-{suffix}.{extension}"
            suffix += 1

        reserved.add(candidate)
        return candidate

    def on_make_convert_clicked(self) -> None:
        image_paths = self.image_grid.get_file_paths()
        if not image_paths:
            return

        if self.output_dir is None:
            self.on_choose_output_folder_clicked()
            if self.output_dir is None:
                return

        des_format = self.format_dropdown.currentText().lower()
        quality = self.quality_spinbox.value()
        output_extension = "png" if des_format == "apng" else des_format
        reserved_outputs: set[Path] = set()
        failures: list[str] = []

        for image_path in image_paths:
            output_path = self.unique_output_path(image_path.stem, output_extension, reserved_outputs)
            try:
                delays = self.dump_frames(image_path)
                self.assemble_frames(des_format, quality, delays, output_path)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                failures.append(f"{image_path.name}: {error}")
            finally:
                shutil.rmtree(Path("gawa_frames"), ignore_errors=True)

        if failures:
            QMessageBox.warning(
                self,
                "Some conversions failed",
                "The following files could not be converted:\n\n" + "\n".join(failures),
            )

def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()