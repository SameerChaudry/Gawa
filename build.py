# Build Gawa standalone executables for windows or linux. Run from the project folder with the venv's Python

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent
IS_WINDOWS = sys.platform == "win32"

WINDOWS_ARGS = [
    "--msvc=latest",
    f"--windows-icon-from-ico={ROOT / 'gawa.ico'}",
    "--windows-console-mode=disable",
]

def main() -> int:
    # The venv's python interpreter currently being used
    python = sys.executable
    print(f"Using Python interpreter: {python}")
    if sys.prefix == sys.base_prefix:
        print("""WARNING: This does not appear to be a virtual-environment Python. Run this script with your project's venv interpreter
            so Nuitka and the application dependencies come from the expected environment""",file=sys.stderr)

    args = [python, "-m", "nuitka", "--onefile", "--enable-plugin=pyside6", f"--include-data-files={ROOT / 'gawa.svg'}=gawa.svg",
        "--output-dir=dist/onefile", "--output-filename=Gawa"]
    if IS_WINDOWS: args += WINDOWS_ARGS
    if os.environ.get("CI"): args.append("--assume-yes-for-downloads")
    args.append(str(ROOT / "main.py"))

    print(f"Building for {'Windows' if IS_WINDOWS else 'Linux'}...")
    result = subprocess.run(args, cwd=ROOT)
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())