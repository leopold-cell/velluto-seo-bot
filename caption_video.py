"""
Burn on-screen captions (hook + beats) onto a Reel clip via ffmpeg.

download_and_caption(video_url, hook, beats, out_path) → captioned local mp4 path
(or the raw download if ffmpeg/font is unavailable, so the pipeline never breaks).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap

import requests

_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _font() -> str:
    return next((f for f in _FONTS if os.path.exists(f)), "")


def _wrap(s: str, width: int) -> str:
    return "\n".join(textwrap.wrap((s or "").strip(), width)) or (s or "").strip()


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


def download_and_caption(video_url: str, hook: str, beats: list[str],
                         out_path: str, duration: int = 8) -> str:
    """Download the clip and burn hook + beats onto it. Returns the captioned path,
    or the raw download if captioning can't run."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    raw = out_path.replace(".mp4", "_raw.mp4")
    if not _download(video_url, raw):
        return ""

    font = _font()
    if not shutil.which("ffmpeg") or not font:
        print("   ⚠️  ffmpeg/font missing — using clip without burned captions")
        return raw

    tmp = tempfile.mkdtemp()
    try:
        filters = []
        # Hook: top, first ~2.6s, large.
        hf = os.path.join(tmp, "hook.txt")
        open(hf, "w", encoding="utf-8").write(_wrap(hook, 18))
        filters.append(
            f"drawtext=fontfile={font}:textfile={hf}:fontcolor=white:fontsize=58:"
            f"line_spacing=8:box=1:boxcolor=black@0.45:boxborderw=18:"
            f"x=(w-text_w)/2:y=110:enable='lt(t,2.6)'"
        )
        # Beats: sequenced, lower third.
        beats = [b for b in (beats or []) if b.strip()]
        if beats:
            seg = max(1.6, (duration - 2.6) / len(beats))
            t = 2.6
            for i, b in enumerate(beats):
                bf = os.path.join(tmp, f"b{i}.txt")
                open(bf, "w", encoding="utf-8").write(_wrap(b, 22))
                filters.append(
                    f"drawtext=fontfile={font}:textfile={bf}:fontcolor=white:fontsize=46:"
                    f"line_spacing=6:box=1:boxcolor=black@0.45:boxborderw=14:"
                    f"x=(w-text_w)/2:y=h-text_h-180:enable='between(t,{t:.2f},{t+seg:.2f})'"
                )
                t += seg

        cmd = ["ffmpeg", "-y", "-i", raw, "-vf", ",".join(filters),
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-c:a", "copy", out_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=240)
            print(f"   ✓ captions burned → {out_path}")
            return out_path
        except subprocess.CalledProcessError as e:
            print(f"   ⚠️  caption ffmpeg failed: {e.stderr[-300:].decode('utf-8','ignore') if e.stderr else e}")
            return raw
        except Exception as e:
            print(f"   ⚠️  caption error: {e}")
            return raw
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
