# The app is split into just main.py and qt_ui
# main.py handles the backend while qt_ui handles the gui

from __future__ import annotations
import subprocess
import shutil
import sys
import re
from PIL import Image
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox
from qt_ui import Ui_MainWindow

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)

        # underscore assignment just tells basedpyright that the returned connection object is useless
        _ = self.add_files_button.clicked.connect(self.on_add_files_clicked)
        _ = self.remove_button.clicked.connect(self.on_remove_clicked)
        _ = self.remove_all_button.clicked.connect(self.on_remove_all_clicked)
        _ = self.make_convert_button.clicked.connect(self.on_make_convert_clicked)

    def on_add_files_clicked(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Select images", "", "Images (*.gif *.webp *.avif *.apng *.png)")
        for path_str in file_paths:
            self.image_grid.add_image(Path(path_str))

    def on_remove_clicked(self) -> None:
        self.image_grid.remove_selected()

    def on_remove_all_clicked(self) -> None:
        self.image_grid.remove_all()

    def dump_frames(self, image_path):
        frame_dir = Path("frames")
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

    def assemble_frames(self, des_format, quality, delays) -> None:
        frame_dir = Path("frames")
        output_dir = Path("converted")
        output_dir.mkdir(exist_ok=True)
        frames = [frame_dir / f"frame_{i:04d}.png" for i in range(len(delays))]
        out_path = output_dir / f"converted.{des_format}"

        if(des_format == "gif"):
            fps = round(1000 / round(sum(delays) / len(delays)))
            frame_paths = [str(frame_dir / f"frame_{i:04d}.png") for i in range(len(delays))]
            cmd = ["gifski", "--quality", str(quality), "--fps", str(fps), "-o", str(out_path)] + frames
            subprocess.run(cmd, check=True)

        if(des_format == "apng"):
            out_path = output_dir / "converted.png"
            cmd = ["apngasm", "-o", str(out_path)]
            for frame_path, delay in zip(frames, delays):
                cmd += [str(frame_path), str(delay)]
            cmd += ["-F"]
            subprocess.run(cmd, check=True)

        if(des_format == "webp"):
            cmd = ["img2webp", "-loop", "0", "-lossy", "-q", str(quality)]
            for i, frame_path in enumerate(frames):
                cmd += ["-d", str(delays[i]), str(frame_path)]
            cmd += ["-o", str(out_path)]
            subprocess.run(cmd, check=True)

        if(des_format == "avif"):
            cmd = ["avifenc", "-q", str(quality), "--timescale", "1000", "-j", "all", "-s", "8"]
            for i, delay in enumerate(delays):
                cmd += ["--duration", str(delay), str(frame_dir / f"frame_{i:04d}.png")]
            cmd += ["-o", str(out_path)]
            subprocess.run(cmd, check=True)

        shutil.rmtree(frame_dir)

    def on_make_convert_clicked(self) -> None:
        des_format = self.format_dropdown.currentText().lower()
        quality = self.quality_spinbox.value()

        for image_path in self.image_grid.get_file_paths():
            delays = self.dump_frames(image_path)
            self.assemble_frames(des_format, quality, delays)

def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()