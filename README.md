Simple and efficient animated image converter gui for gif, webp, avif, and apng. Uses pyside6 for a native qt gui window on both linux and windows

Each conversion is as efficient as I could make it (if all dependencies are in PATH), like preferring an image sequence for encodind,  preferring native tools instead of pillow, and ffmpeg for encoding avif, so feel free to make suggestions

I am unfamiliar with pyside6 so qt_ui.py is written by Claude

Pyside6 and Pillow are required dependencies, while gifski, apngasm, img2webp, ffmpeg, and ffprobe are optional dependencies

Roadmap:
- Bit of extra polish/bug fixes/error handling
- Releasing compiled executables for linux and windows after finishing basic features
- Submitting to the AUR