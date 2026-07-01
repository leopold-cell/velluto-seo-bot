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
    """Prefer the pip-bundled imageio-ffmpeg binary (pinned v7 — the version every
    filter here is tested against). Old system ffmpeg (Ubuntu's 4.x) mishandled
    -loop/-shortest (98s bug) and the -t composite, so only fall back to it if the
    bundled one is unavailable. Override with FFMPEG_BIN if needed."""
    env = os.getenv("FFMPEG_BIN", "").strip()
    if env and os.path.isfile(env):
        return env
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or ""


def _duration(ffmpeg: str, path: str) -> float:
    """Seconds of the video, parsed from ffmpeg's banner. 0.0 if unknown."""
    try:
        out = subprocess.run([ffmpeg, "-i", path], capture_output=True, timeout=60).stderr
        txt = out.decode("utf-8", "ignore")
        import re
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return 0.0


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

    # Native style: plain white text, no panel — just a thin dark outline so it stays
    # readable on bright roads (like Instagram's own caption tool).
    y = top
    for ln, w in zip(lines, widths):
        draw.text((cx - w / 2, y), ln, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=(0, 0, 0, 220))
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

    # Main caption — upper third, held the whole clip (the joke). Plain white.
    _draw_block(draw, (onscreen or "").strip(), main_font, W / 2, int(H * 0.14),
                int(W * 0.86), fill=(255, 255, 255, 255))
    # Punchline — lower third, also plain white (native look).
    if (punchline or "").strip():
        _draw_block(draw, punchline.strip(), punch_font, W / 2, int(H * 0.68),
                    int(W * 0.84), fill=(255, 255, 255, 255))

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
    # Standardise EVERY reel to `duration` seconds. -stream_loop -1 loops a short clip
    # (and the music) so it fills the full length; longer clips/tracks are simply
    # trimmed by -t. -t caps all output streams deterministically across ffmpeg versions.
    vdur = _duration(ffmpeg, raw)
    cut = float(duration) if duration and duration > 0 else (vdur if vdur > 0 else 0.0)
    # Format-robust: normalise ANY source (portrait/landscape, any resolution) to a
    # 1080x1920 9:16 frame, then overlay the 1080x1920 caption PNG at 0:0. Avoids the
    # scale2ref fragility that broke compositing on differently-sized clips.
    vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
          "crop=1080:1920,setsar=1,fps=30[base];[base][1:v]overlay=0:0[v]")
    cmd = [ffmpeg, "-y", "-stream_loop", "-1", "-i", raw, "-i", png]
    if use_music:
        cmd += ["-stream_loop", "-1", "-i", music_path]
    cmd += ["-filter_complex", vf, "-map", "[v]"]
    if use_music:
        # Music track (input 2) as the audio.
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "160k"]
    if cut > 0:
        cmd += ["-t", f"{cut:.3f}"]
    else:
        cmd += ["-shortest"]   # fallback if both probe and duration are unknown
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=240)
        print(f"   ✓ caption overlay burned → {out_path}")
        return out_path
    except subprocess.CalledProcessError as e:
        msg = e.stderr[-800:].decode("utf-8", "ignore") if e.stderr else str(e)
        print(f"   ⚠️  caption ffmpeg FAILED (using {ffmpeg}, music={use_music}):\n{msg}")
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
