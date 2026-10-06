Simple and efficient animated image converter gui for gif, webp, avif, and apng. Accepts most image and video inputs including static images. Processing video inputs requires ffmpeg and ffprobe to be installed and available on your system PATH. Uses PySide6 for a native Qt gui window on both Linux and Windows. Compiled builds for Linux and Windows are in [Releases](https://github.com/SameerChaudry/Gawa/releases)

Each conversion is as efficient as I could make it, like using png image sequences for encoding, allowing native efficient tools like gifski, apngasm, and ffmpeg to be used instead of pillow. Feel free to suggest improvements

Pyside6 and Pillow are required pip dependencies, while gifski, apngasm, ffmpeg, and ffprobe are optional dependencies. 

I am unfamiliar with pyside6 and dbus so parts of the Qt and dbus code is written by AI
