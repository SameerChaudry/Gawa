Simple and efficient animated image converter gui for gif, webp, avif, and apng. Accepts most image and video inputs including static images. Processing video inputs requires ffmpeg and ffprobe to be installed and available on your system PATH. Uses PySide6 for a native Qt gui window on both Linux and Windows. Compiled builds for Linux and Windows are in [Releases](https://github.com/SameerChaudry/Gawa/releases)

One of the main goals is for each conversion to be as efficient as possible. Like using png image sequences for encoding and allowing efficient tools like gifski, apngasm, and ffmpeg to be used instead of pillow. Feel free to suggest improvements

Pyside6 and Pillow are required pip dependencies, while gifski, apngasm, ffmpeg, and ffprobe are optional dependencies. 

I am unfamiliar with pyside6 and dbus so parts of the Qt and dbus code is written by AI

## Features:
- Convert images, animations, or videos to a gif, apng, webp, or avif using multiple configuration options
- Import a folder with any combination of images, animations, or videos to make a single animation using all of them in alphabetical order. For instance: '00_image.png', 01_anim.gif, '02_video.mp4', '03_image.jpg', '04_anim.avif' in a folder will be encoded in this order
- Passing file/folder paths from the command line imports them on launch
- Uses ffmpeg for frame extraction and allows using img2webp, apngasm, or ffmpeg for better efficiency for certain formats if available in PATH
- An image grid to preview your input files and an in-app log to track progress and report errors

## Building:
Only Nuitka is needed for compiling but using ccache, ordered-set, and zstandard is recommended for faster compile times and significantly smaller executable. Nuitka, ordered-set, and zstandard are pip packages while ccache is a native tool

Run build.py using the .venv python instead of global python, which is .venv/bin/python on linux and .venv\Scripts\python on windows (from the project's root directory). gcc works well as a nuitka backend compiler for linux but using zig fails to compile on windows so use msvc instead. If you get permission denied errors on Windows when building, try going to the properties menu of the project folder and disabling read-only for all files