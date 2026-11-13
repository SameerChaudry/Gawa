# Responsible for frame timing, canvas normalization, in-memory loading, encoding, and output naming

from __future__ import annotations
import json
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable
from PIL import Image
from gawa.config import HIDE_CMD, Options, deps

# Calculates an fps value using a list of delays or a custom delay value
def get_fps(delays: list[int], options: Options) -> float:
    if options.get("delay_speed_enabled") and options.get("delay_speed_mode") == "Custom fps":
        return float(options["delay_speed_value"])

    valid_delays = [delay for delay in delays if delay > 0]
    if not valid_delays: valid_delays = [100]

    delay_mode = options["delay_mode"]
    if delay_mode == "Average":  delay_ms = sum(valid_delays) / len(valid_delays)
    elif delay_mode == "Mode":   delay_ms = statistics.mode(valid_delays)
    elif delay_mode == "Custom fps": return float(options["custom_fps"])
    else: raise ValueError(f"Unknown delay mode: {delay_mode}")

    return max(1.0, 1000 / max(1.0, delay_ms))

# Applies the sidebar's delays speed setting to the extracted frame delays
def adjust_delays(delays: list[int], options: Options) -> list[int]:
    if not options.get("delay_speed_enabled"): return delays
    value = float(options["delay_speed_value"])
    mode = options["delay_speed_mode"]
    if mode == "Multiplier": return [max(1, round(delay * value)) for delay in delays]
    if mode == "Custom fps":
        if value <= 0: raise ValueError("Custom fps must be greater than zero")
        return [max(1, round((index + 1) * 1000 / value) - round(index * 1000 / value))
            for index in range(len(delays))]
    raise ValueError(f"Unknown delay adjustment mode: {mode}")

# Places frames on the output canvas and applies the resize, fit, and centering settings
def normalize_frame_sequence(frame_dir: Path, frame_count: int, resize_size: tuple[int, int] | None,
fit_to_canvas: bool, center_frames: bool, use_ffmpeg: bool) -> set[str]:
    frames = [frame_dir / f"frame_{index:04d}.png" for index in range(frame_count)]
    frame_sizes: list[tuple[int, int]] = []
    for frame_path in frames:
        with Image.open(frame_path) as frame:
            frame_sizes.append(frame.size)

    source_canvas = (max(width for width, _ in frame_sizes), max(height for _, height in frame_sizes))
    output_canvas = source_canvas
    if resize_size is not None:
        width, height = resize_size
        if width == 0:
            width = max(1, round(source_canvas[0] * height / source_canvas[1])) if height else source_canvas[0]
        if height == 0:
            height = max(1, round(source_canvas[1] * width / source_canvas[0])) if width else source_canvas[1]
        output_canvas = (width, height)

    if all(size == source_canvas for size in frame_sizes) and output_canvas == source_canvas:
        return set()

    composition_canvas = output_canvas if fit_to_canvas else source_canvas
    filter_chain: list[str] = []
    if fit_to_canvas:
        filter_chain.append(f"scale={output_canvas[0]}:{output_canvas[1]}:force_original_aspect_ratio=decrease")

    pad_x = "(ow-iw)/2" if center_frames else "0"
    pad_y = "(oh-ih)/2" if center_frames else "0"
    filter_chain.append(f"pad={composition_canvas[0]}:{composition_canvas[1]}:{pad_x}:{pad_y}:color=black@0")
    if composition_canvas != output_canvas:
        filter_chain.append(f"scale={output_canvas[0]}:{output_canvas[1]}")

    with tempfile.TemporaryDirectory(prefix="gawa-normalized-", dir=frame_dir) as temp_name:
        normalized_dir = Path(temp_name)
        if use_ffmpeg:
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-start_number", "0", "-i",
                    str(frame_dir / "frame_%04d.png"), "-vf", ",".join(filter_chain), "-start_number", "0",
                    str(normalized_dir / "frame_%04d.png")], check=True, capture_output=True, creationflags=HIDE_CMD)
                normalized_frames = sorted(normalized_dir.glob("frame_*.png"))
                if len(normalized_frames) != frame_count:
                    raise RuntimeError(f"Expected {frame_count} normalized frames, got {len(normalized_frames)}")
                for index, frame_path in enumerate(normalized_frames):
                    shutil.move(str(frame_path), frames[index])
                return {"ffmpeg"}
            except (OSError, RuntimeError, subprocess.SubprocessError): pass

        for frame_path in frames:
            with Image.open(frame_path) as image:
                frame = image.convert("RGBA")
                if fit_to_canvas:
                    scale = min(output_canvas[0] / frame.width, output_canvas[1] / frame.height)
                    fitted_size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
                    if fitted_size != frame.size:
                        frame = frame.resize(fitted_size, Image.Resampling.LANCZOS)

                canvas = Image.new("RGBA", composition_canvas, (0, 0, 0, 0))
                x = (composition_canvas[0] - frame.width) // 2 if center_frames else 0
                y = (composition_canvas[1] - frame.height) // 2 if center_frames else 0
                canvas.paste(frame, (x, y))
                if composition_canvas != output_canvas:
                    canvas = canvas.resize(output_canvas, Image.Resampling.LANCZOS)
                canvas.save(frame_path, format="PNG")

    return {"pillow"}

# Load, copy, and close each image instead of keeping all frame images open at once
def load_frames(frames: list[Path]) -> list[Image.Image]:
    loaded: list[Image.Image] = []
    for frame_path in frames:
        with Image.open(frame_path) as image:
            image.load()
            loaded.append(image.copy())
    return loaded

# Encodes animations using a directory of frames and a list of delays
def assemble_frames(des_format: str, quality: int, delays: list[int], out_path: Path, options: Options,
frame_dir: Path, log_message: Callable[[str], None] | None = None) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = [frame_dir / f"frame_{i:04d}.png" for i in range(len(delays))]

    def log_fallback(encoder: str, error: Exception) -> None:
        out_path.unlink(missing_ok=True)
        if log_message is not None: log_message(f"{encoder} failed: {error}. Falling back to Pillow.")

    if(des_format == "gif"):
        if(deps["gifski"] and options["use_gifski"] and len(frames) > 1):
            fps = get_fps(delays, options)
            cmd = ["gifski", "--quality", str(quality), "--fps", str(fps)]
            if options["gifski_speed"] == "Fast": cmd += ["--fast"]
            elif options["gifski_speed"] == "Extra": cmd += ["--extra"]
            cmd += ["-o", str(out_path)] + frames
            try:
                subprocess.run(cmd, check=True, creationflags=HIDE_CMD)
                return "gifski"
            except (OSError, subprocess.SubprocessError) as error:
                log_fallback("Gifski", error)

        elif(deps["ffmpeg"] and options["use_ffmpeg"] and len(frames) > 1):
            fps = get_fps(delays, options)
            input_pattern = str(frame_dir / "frame_%04d.png")
            dither = "sierra2_4a" if options["dither"] else "none"
            try:
                subprocess.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern, "-vf","palettegen=stats_mode=diff",
                    "-update", "1", str(frame_dir / "palette.png")], check=True, creationflags=HIDE_CMD)
                subprocess.run(['ffmpeg','-y','-framerate', str(fps),'-i', input_pattern, '-i', str(frame_dir / "palette.png"),
                    '-lavfi', f'paletteuse=dither={dither}', '-r', str(fps), str(out_path)], check=True, creationflags=HIDE_CMD)
                return "ffmpeg"
            except (OSError, subprocess.SubprocessError) as error:
                log_fallback("FFmpeg GIF encoder", error)

        # Use pillow for the gif encode. Uses local color table for every frame by default
        # which is not supported by both gifski and ffmpeg
        imgs = load_frames(frames)
        imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,  disposal=2)
        return "pillow"

    if(des_format == "apng"):
        if(deps["apngasm"] and options["use_apngasm"]):
            spec_path = frame_dir / "animation.json"
            try:
                with spec_path.open("w", encoding="utf-8") as spec_file:
                    json.dump({"frames": [{frame_path.name: f"{delay}/1000"}
                        for frame_path, delay in zip(frames, delays)]}, spec_file)
                cmd = ["apngasm", "-o", str(out_path), "-f", str(spec_path), "-F"]
                subprocess.run(cmd, check=True, creationflags=HIDE_CMD)
                return "apngasm"
            except (OSError, subprocess.SubprocessError) as error:
                log_fallback("apngasm", error)

        imgs = load_frames(frames)
        imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0,
            disposal=1, compress_level=options["speed"])
        return "pillow"

    if(des_format == "webp"):
        imgs = load_frames(frames)
        webp_quality_options: dict[str, Any] = {"lossless": True} if quality == 100 else {"quality": quality}
        imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays, loop=0, method=options["speed"],
            exact=options["exact"], allow_mixed=options["use_mixed"], **webp_quality_options)
        return "pillow"

    if(des_format == "avif"):
        speed = options["speed"]
        subsampling = str(options["subsampling"])

        if(deps["ffmpeg"] and options["use_ffmpeg"]):
            fps = get_fps(delays, options)
            pixel_format = subsampling
            crf = str(options["crf"])
            input_pattern = str(frame_dir / "frame_%04d.png")

            try:
                subprocess.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern, "-vf", "scale=in_range=full:out_range=full",
                "-c:v", "libsvtav1", "-preset", str(speed), "-crf", crf, "-pix_fmt", pixel_format, "-color_range", "2",
                "-f", "avif", "-loop", "0", str(out_path)], check=True, creationflags=HIDE_CMD)
                return "ffmpeg"
            except (OSError, subprocess.SubprocessError) as error:
                log_fallback("FFmpeg AVIF encoder", error)

        imgs = load_frames(frames)
        imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=delays,
            speed=speed, subsampling=subsampling, quality=quality)
        return "pillow"

    else: raise ValueError(f"Invalid output format: {des_format}")

# Use a unique filename suffix to avoid rewriting output files
def unique_output_path(output_dir: Path, stem: str, extension: str, reserved: set[Path]) -> Path:
    candidate = output_dir / f"{stem}.{extension}"
    suffix = 1
    while candidate.exists() or candidate in reserved:
        candidate = output_dir / f"{stem}-{suffix}.{extension}"
        suffix += 1

    reserved.add(candidate)
    return candidate
