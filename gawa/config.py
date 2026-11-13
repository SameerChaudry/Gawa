# Contains tool availability, constants, and object types for use by other parts

from __future__ import annotations
import shutil
import subprocess
import sys

OptionValue = bool | int | float | str
Options = dict[str, OptionValue]

FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

deps = {
    "gifski":   shutil.which("gifski") is not None,
    "apngasm":  shutil.which("apngasm") is not None,
    "ffmpeg":   FFMPEG_PATH is not None,
    "ffprobe":  FFPROBE_PATH is not None,
}

HIDE_CMD = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
