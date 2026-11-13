# Gawa's entry point. The application code lives in the gawa directory

from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from gawa.window import MainWindow

def main(argv: list[str] | None = None) -> None:
    startup_paths = list(sys.argv[1:] if argv is None else argv)
    app = QApplication([sys.argv[0]])
    window = MainWindow()
    window.import_startup_paths(startup_paths)
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().with_name("gawa.svg"))))
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
