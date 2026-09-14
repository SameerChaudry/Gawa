Simple and efficient animated image converter gui for gif, webp, avif, and apng. Uses pyside6 for a native qt gui window on both linux and windows

Each conversion is as efficient as I could make it, like preferring image sequence and native tools instead of pillow, and ffmpeg for encoding apng/avif, so feel free to make suggestions

I am unfamiliar with pyside6 so qt_ui.py is written by Claude

Roadmap:
- Progress indicator

- Additional toggles for more customizability during conversions
- FFmpeg as an optional dependency for significantly improving certain conversions
- Displaying encoding methods comparisons in-app for easier informed decisions
- Including compiled builds with bundled dependencies
- Submitting to the AUR

- Video to animated image converter
- Maybe eventually porting to C++