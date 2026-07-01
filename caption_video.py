"""
Burn a doctor.running-style text overlay onto a Reel clip — robustly.

The overlay is rendered as a PNG with Pillow (clean typography, wrapping, a
semi-transparent panel, black-stroked text) and composited onto the video with
ffmpeg. ffmpeg is taken from the system if present, otherwise from the pip-bundled
imageio-ffmpeg binary — so no `apt install` is required on the VPS.

download_and_caption(video_url, onscreen, punchline, out_path, duration)
  → captioned local mp4 path, or the *_raw.mp4 download if the overlay can't be
    burned (caller detects the '_raw.mp4' suffix and refuses to post it).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import textwrap

import requests

_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _font_path() -> str:
    return next((f for f in _FONTS if os.path.exists(f)), "")


def _ffmpeg() -> str:
    """System ffmpeg if present, else the pip-bundled imageio-ffmpeg binary."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def _download(url: str, dest: str) -> bool:
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return os.path.getsize(dest) > 0
    except Exception as e:
        print(f"   ⚠️  video download failed: {e}")
        return False


# ── overlay rendering (Pillow) ───────────────────────────────────────────────

_CANVAS = (1080, 1920)   # 9:16; ffmpeg scales the overlay to the clip size


def _draw_block(draw, text, font, cx, top, max_w, fill, stroke=6, pad=28):
    """Draw a centered, wrapped text block with a translucent panel behind it.
    Returns the bottom y of the drawn block."""
    from PIL import ImageDraw  # noqa: F401  (draw is already an ImageDraw)

    # Wrap to fit max_w by measuring progressively.
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)

    asc, desc = font.getmetrics()
    lh = asc + desc + 12
    block_h = lh * len(lines)
    widths = [draw.textlength(ln, font=font) for ln in lines]
    panel_w = min(_CANVAS[0] - 40, int(max(widths) + pad * 2))

    # translucent panel
    x0 = int(cx - panel_w / 2)
    draw.rounded_rectangle([x0, int(top - pad), x0 + panel_w, int(top + block_h + pad)],
                           radius=28, fill=(0, 0, 0, 110))
    y = top
    for ln, w in zip(lines, widths):
        draw.text((cx - w / 2, y), ln, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += lh
    return y + pad


def _render_overlay(onscreen: str, punchline: str, out_png: str) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        print(f"   ⚠️  Pillow missing ({e}) — cannot render caption overlay")
        return False
    fp = _font_path()
    if not fp:
        print("   ⚠️  no bold TTF font found — cannot render caption overlay")
        return False

    W, H = _CANVAS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    main_font = ImageFont.truetype(fp, 82)
    punch_font = ImageFont.truetype(fp, 66)

    # Main caption — upper third, held the whole clip (the joke).
    _draw_block(draw, (onscreen or "").strip(), main_font, W / 2, int(H * 0.14),
                int(W * 0.86), fill=(255, 255, 255, 255))
    # Punchline — lower third, yellow (static; reliability over timed reveal).
    if (punchline or "").strip():
        _draw_block(draw, punchline.strip(), punch_font, W / 2, int(H * 0.68),
                    int(W * 0.84), fill=(255, 214, 10, 255))

    img.save(out_png)
    return True


def download_and_caption(video_url: str, onscreen: str, punchline: str,
                         out_path: str, duration: int = 8, music_path: str = "") -> str:
    """Download the clip and composite a doctor.running-style text overlay onto it.
    Returns the captioned path, or the *_raw.mp4 download if the overlay can't be
    burned (so the caller can detect it via the '_raw.mp4' suffix)."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    raw = out_path.replace(".mp4", "_raw.mp4")
    if not _download(video_url, raw):
        return ""

    ffmpeg = _ffmpeg()
    if not ffmpeg:
        print("   ⚠️  no ffmpeg (system or imageio-ffmpeg) — clip WITHOUT captions. "
              "Fix: `pip install imageio-ffmpeg` or `apt install ffmpeg`.")
        return raw

    png = out_path.replace(".mp4", "_overlay.png")
    if not _render_overlay(onscreen, punchline, png):
        return raw

    # Scale the overlay to the clip size, then composite it over the whole clip.
    # Optionally add a license-free music track as the audio (Instagram's own music
    # library is NOT available via the API — audio must be baked into the file).
    use_music = bool(music_path) and os.path.isfile(music_path)
    # -loop 1 makes the overlay PNG an endless stream so -shortest keys off the video/
    # music (a single-frame image is ~0s and would otherwise truncate the whole clip).
    cmd = [ffmpeg, "-y", "-i", raw, "-loop", "1", "-i", png]
    if use_music:
        cmd += ["-i", music_path]
    cmd += ["-filter_complex", "[1:v][0:v]scale2ref[ov][base];[base][ov]overlay=0:0[v]",
            "-map", "[v]"]
    if use_music:
        # Music track (input 2) as the audio.
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-shortest", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=240)
        print(f"   ✓ caption overlay burned → {out_path}")
        return out_path
    except subprocess.CalledProcessError as e:
        msg = e.stderr[-300:].decode("utf-8", "ignore") if e.stderr else str(e)
        print(f"   ⚠️  caption ffmpeg failed: {msg}")
        return raw
    except Exception as e:
        print(f"   ⚠️  caption error: {e}")
        return raw
    finally:
        try:
            os.remove(png)
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    u = sys.argv[1] if len(sys.argv) > 1 else ""
    p = download_and_caption(u, "me pretending this is a recovery ride for the 4th day straight",
                             "it is not", os.path.join("output", "reels", "caption_test.mp4"), 5)
    print("→", p)
