Simple and efficient animated image converter gui for gif, webp, avif, and apng. Accepts all image and video inputs including static images. Processing video inputs requires ffmpeg and ffprobe to be installed and available on your system PATH. Uses PySide6 for a native Qt gui window on both Linux and Windows

Each conversion is as efficient as I could make it, like preferring png image sequences for encoding, preferring native tools instead of pillow, and ffmpeg for encoding avif, so feel free to make suggestions

Pyside6 and Pillow are required pip dependencies, while gifski, apngasm, img2webp, ffmpeg, and ffprobe are optional dependencies. 

Roadmap:
- Releasing compiled executables for linux and windows
- Submitting to the AUR

I am unfamiliar with pyside6 so qt_ui.py is written by Claude