Simple and efficient animated image converter gui for gif, webp, avif, and apng. Uses pyside6 for a native qt gui window on both linux and windows

Each conversion is as efficient as I could make it (if all dependencies are in PATH), like preferring an image sequence for encodind,  preferring native tools instead of pillow, and ffmpeg for encoding avif, so feel free to make suggestions

I am unfamiliar with pyside6 so qt_ui.py is written by Claude

Pyside6 and Pillow are required dependencies, while gifski, apngasm, img2webp, and ffmpeg are optional dependencies

Roadmap:
- Progress indicator and asynchronous conversion

- Displaying encoding methods comparisons in-app for easier informed decisions
- Including an in-app log for info about progress, errors, commands used, etc
- Releasing compiled executables for linux and windows after finishing basic features
- Submitting to the AUR

- Video to animated image converter