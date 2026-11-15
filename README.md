Simple and efficient animated image converter gui for gif, webp, avif, and apng. Accepts most image and video inputs including static images. Processing video inputs requires ffmpeg and ffprobe to be installed and available on your system PATH. Uses PySide6 for a native Qt gui window on both Linux and Windows. Compiled builds for Linux and Windows are in [Releases](https://github.com/SameerChaudry/Gawa/releases) and the project uses [Unlicense](https://unlicense.org/), but giving credit for using it is appreciated

One of the main goals is for each conversion to be as efficient as possible. Like using png image sequences for encoding and allowing efficient tools like gifski, apngasm, and ffmpeg to be used instead of pillow. Feel free to suggest improvements

Pyside6 and Pillow are required pip dependencies (unless you use the compiled executable), while gifski, apngasm, ffmpeg, and ffprobe are optional dependencies

I am unfamiliar with pyside6 and dbus so parts of the Qt and dbus code is written by AI

## Features
- Convert images, animations, or videos to a gif, apng, webp, or avif using multiple configuration options
- Import a folder with any combination of images, animations, or videos to make a single animation using all of them in alphabetical order. For instance: '00_image.png', 01_anim.gif, '02_video.mp4', '03_image.jpg', '04_anim.avif' in a folder will be encoded in this order
- Import files/folders by passing file/folder paths from the command line on launch, dragging them onto the window, or using the UI buttons
- Uses ffmpeg for frame extraction and allows using img2webp, apngasm, or ffmpeg for better efficiency for certain formats if available in PATH
- An image grid to preview your input files and an in-app log to track progress and report errors

## Building
Only Nuitka is needed for compiling but using ccache, ordered-set, and zstandard is recommended for faster compile times and significantly smaller executable. Nuitka, ordered-set, and zstandard are pip packages while ccache is a native tool

Run build.py using the .venv python instead of global python, which is .venv/bin/python on linux and .venv\Scripts\python on windows (from the project's root directory). gcc works well as a nuitka backend compiler for linux but using zig fails to compile on windows so use msvc instead. If you get permission denied errors on Windows when building, try going to the properties menu of the project folder and disabling read-only for all files

## Notes
- Previews for videos use a frame at 5% of the video duration
- You don't need any dependencies to run the compiled binaries
- Cached frames are only for the current session. Restarting Gawa will not use cached frames from earlier sessions
- FFmpeg is used by default for extracting and normalizing frames where possible if available in PATH, and both ffmpeg and ffprobe are required for processing video inputs
- 'Video fps' determines the fps at which frames are extracted from videos, instead of extracting all frames and dropping them to meet the fps value (unless 0 is used which uses source fps). But frame delays get adjusted to preserve the original video duration regardless of the fps value chosen

## Ram usage (for pillow)
Fixing Pillow's 'Too many open files' issue required copying all frames into memory instead. But ram use won't keep climbing on every conversion while Gawa is open. The general trend seems to be no more than ~2x ram use of the biggest (not in terms of file/folder size) single source in your processing batch. Ofcourse, the usage might work differently if you use gifski, ffmpeg, apngasm instead of the pillow fallback which haven't been tested but might be more efficient

I used 2 sources for stress testing: 60 3000x1775 frames and 1922 480x270 frames. When doing the 1922 frames, ram use went from ~80mb to ~900mb after 1st conversion and ~1.6gb after 2nd conversion. But every conversion after that hovered around 1.6gb regardless of how many times you redo the conversion, even with different encoder settings. The 60 high res frames followed a similar pattern of ~80mb idle -> ~1.4gb 1st conversion -> 2.9gb for every conversion after that. Since only the source with the most image data in a batch affects ram usage, converting both of those sources together showed the same pattern as just doing the 60 frames by themselves