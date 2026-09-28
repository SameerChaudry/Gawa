# Animation encoderBenchmark (GIF / APNG / AVIF / WebP)

Source: 263 frames, 254x450, 25 fps (40 ms/frame), extracted from a slightly lossy webp. Frames are fully opaque. All encodes use only the extracted PNG frames as input

These are just the results from testing 263 254x450 png frames of a flat color animation using different encoding options for each of the 4 formats. Don't take these too literally as these are provided just for reference,Because different encoders support different inputs, work better for specific kinds of content, have certain limitations, etc

**VMAF:** VMAF is a tool made by Netflix to objectively compare the quality of video content with a score from 0 to 100. Each output is decodedBack to per-frame PNGs (Pillow), converted to libsvtav1 y4m at 25 fps, and compared to the reference y4m with the standalone `vmaf` CLI (`vmaf_v0.6.1`), over all 263 frames.
**Ceiling:** feeding the reference frames through this same pipeline scores min 97.43 / mean 99.77 (not 100), so read those as the best achievable values here. I have not pinned down why identical input doesn't reach 100.

Environment: Pillow 12.1.1, ffmpeg 6.1.1 , apngasm 3.1.10, gifski 1.13.1. Each enocde was done sequentially on a single cpu core for consistency
## GIF

| Encoder | Quality used | Speed used | Time taken | File size | Minimum Vmaf | Mean Vmaf | Features |
|---|---|---|---|---|---|---|---|
| pillow | n/a | n/a | 1.27 s | 7,597,287B | 94.70 | 99.57 | Single color table for all frame, no dithering, `disposal=2` |
| pillow local_color_table | n/a | n/a | 0.87 s | 4,041,885B | 94.81 | 99.14 | `include_color_table=True` (local table on every frame, verified with gifsicle), `disposal=2` |
| gifski | 80 | `--fast` | 6.91 s | 4,511,557 B | 95.68 | 99.40 | `-Q 80 -r 25 --fast` |
| gifski | 80 | default | 8.41 s | 4,421,060B | 95.58 | 99.40 | `-Q 80 -r 25`, gifski handles palettes/disposal itself |
| gifski | 80 | `--extra` | 14.56 s | 4,326,746 B | 94.83 | 99.35 | `-Q 80 -r 25 --extra` |

## APNG

| Encoder | Quality used | Speed used | Time taken | File size | Minimum Vmaf | Mean Vmaf | Features |
|---|---|---|---|---|---|---|---|
| pillow | n/a (lossless) | compress_level 0 | 1.21 s | 120,421,425B | 97.43 | 99.77 | `Disposal.OP_BACKGROUND`, `Blend.OP_SOURCE` |
| pillow | n/a (lossless) | compress_level 6 | 3.26 s | 16,991,147B | 97.43 | 99.77 | `Disposal.OP_BACKGROUND`, `Blend.OP_SOURCE` |
| pillow | n/a (lossless) | compress_level 9 | 12.62 s | 16,764,872B | 97.43 | 99.77 | `Disposal.OP_BACKGROUND`, `Blend.OP_SOURCE` |
| apngasm 3.1.10 | n/a (lossless) | default | 25.00 s | 14,181,980B | 97.43 | 99.77 | Default settings, since it doesn't have much customization |

## AVIF

| Encoder | Quality used | Speed used | Time taken | File size | Minimum Vmaf | Mean Vmaf | Features |
|---|---|---|---|---|---|---|---|
| pillow | 80 | 10 | 2.73 s | 1,988,156B | 94.06 | 99.37 | default encoder libaom |
| pillow | 80 | 7 | 3.74 s | 1,911,662B | 95.49 | 99.47 | default encoder libaom |
| pillow | 80 | 6 | 57.41 s | 1,341,807B | 94.82 | 99.37 | default encoder libaom |
| pillow | 80 | 5 | 93.33 s | 1,314,421B | 95.04 | 99.39 | default encoder libaom |
| pillow | 80 | 3 | 165.40 s | 1,278,588B | 95.08 | 99.37 | default encoder libaom |
| pillow | 80 | 1 | 1131.68 s | 1,275,503B | 95.32 | 99.43 | default encoder libaom |
| ffmpeg | crf 40 | preset 13 | 2.69 s | 502,165B | 89.00 | 96.14 | libsvtav1 |
| ffmpeg | crf 40 | preset 10 | 3.86 s | 445,145B | 89.88 | 96.22 | libsvtav1 |
| ffmpeg | crf 40 | preset 7 | 8.40 s | 381,308B | 90.81 | 96.62 | libsvtav1 |
| ffmpeg | crf 40 | preset 5 | 21.01 s | 355,182B | 91.15 | 97.25 | libsvtav1 |
| ffmpeg | crf 40 | preset 3 | 50.75 s | 329,977B | 92.04 | 97.41 | libsvtav1 |
| ffmpeg | crf 40 | preset 1 | 117.74 s | 320,056B | 92.05 | 97.52 | libsvtav1 |
| ffmpeg | crf 35 | preset 13 | 2.80 s | 693,558B | 91.97 | 97.73 | libsvtav1 |
| ffmpeg | crf 35 | preset 10 | 4.22 s | 617,924B | 90.70 | 97.75 | libsvtav1 |
| ffmpeg | crf 35 | preset 7 | 9.78 s | 522,474B | 92.16 | 97.88 | libsvtav1 |
| ffmpeg | crf 35 | preset 5 | 24.28 s | 491,246B | 92.94 | 98.31 | libsvtav1 |
| ffmpeg | crf 35 | preset 3 | 53.70 s | 449,496B | 93.53 | 98.43 | libsvtav1 |
| ffmpeg | crf 35 | preset 1 | 134.37 s | 438,944B | 93.56 | 98.45 | libsvtav1 |

## WebP

Pillow uses itsBundled libwebp 1.6.0. img2webp wasBuilt from libwebp v1.6.0 source (the apt 1.3.2Build has no `-exact`), soBoth use the same encoder version. img2webp defaults to lossless, so `-lossy -q 80` is passed for every frame. "Sharp rgb" is interpreted as `-sharp_yuv` (sharper RGB->YUV conversion).

| Encoder | Quality used | Speed used | Time taken | File size | Minimum Vmaf | Mean Vmaf | Features |
|---|---|---|---|---|---|---|---|
| pillow | 80 | method 0 | 1.45 s | 2,718,914B | 95.16 | 99.31 | lossy |
| pillow | 80 | method 4 | 3.63 s | 1,942,206B | 95.10 | 99.29 | lossy |
| pillow | 80 | method 6 | 81.84 s | 1,929,432B | 95.19 | 99.37 | lossy |
| pillow | 80 | method 4 | 3.63 s | 1,942,206B | 95.10 | 99.29 | lossy, `exact=True` |
| img2webp | 80 | method 0 | 1.71 s | 2,727,236B | 94.88 | 99.30 | `-lossy` |
| img2webp | 80 | method 4 | 3.31 s | 1,950,890B | 95.17 | 99.29 | `-lossy` |
| img2webp | 80 | method 6 | 76.16 s | 1,940,968B | 95.12 | 99.37 | `-lossy` |
| img2webp | 80 | method 4 | 3.37 s | 1,936,826B | 95.00 | 99.29 | `-lossy -exact` |
| img2webp | 80 | method 4 | 3.30 s | 1,950,890B | 95.17 | 99.29 | `-lossy -mixed` |
| img2webp | 80 | method 4 | 5.48 s | 1,972,926B | 95.01 | 99.26 | `-lossy -sharp_yuv` |
| img2webp | 80 | method 4 | 5.73 s | 1,950,252B | 94.98 | 99.27 | `-lossy -exact -mixed -sharp_yuv` |

## Notes

- **GIF sizes:** The global-palette pillow GIF is nearly 2x the local-table one. On a single test frame the shared palette produced ~23.3k palette-index changes along rows vs ~13.7k for the per-frame palette (29.8 KB vs 15.5 KB), which suggests the near-white background's compression noise gets spread across several similar palette entries and LZW compresses it poorly. Dithering the shared palette made it worse (~9.9 MB), and dropping `disposal=2` barely changed it (~7.4 MB)
- **Pillow AVIF speed 1:** Took about 19 minutes and produced 1,275,503B, only 0.2% smaller than speed 3 (1,278,588B) in about 7x the time. Mean VMAF is 99.43, second to speed 7's 99.47; all Pillow AVIF speeds sit within about 0.1 mean VMAF of each other.
- **WebP exact/mixed:** The frames are fully opaque, so Pillow `exact` gives a byte-identical size to plain method 4, and img2webp `-mixed` matched plain method 4 exactly in size, which suggests lossy was chosen for every frame given the identical sizes. img2webp `-exact` did change the size (1,936,826B, about 0.7% smaller) even on opaque frames.
- **ffmpeg crf 35:** Roughly 1.4x larger than crf 40 at the same preset, with mean VMAF up about 0.9 to 1.6.