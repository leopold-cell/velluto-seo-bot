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


def download_and_caption(video_url: str, onscreen: str, punchline: str,
                         out_path: str, duration: int = 8) -> str:
    """Download the clip and burn a doctor.running-style overlay: ONE big caption
    (`onscreen`) held the whole clip, plus an optional end `punchline`. Returns the
    captioned path, or the *_raw.mp4 download if captioning can't run (so the caller
    detects a missing ffmpeg via the '_raw.mp4' suffix)."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    raw = out_path.replace(".mp4", "_raw.mp4")
    if not _download(video_url, raw):
        return ""

    font = _font()
    if not shutil.which("ffmpeg") or not font:
        print("   ⚠️  ffmpeg/font missing — using clip WITHOUT burned captions (install ffmpeg!)")
        return raw

    tmp = tempfile.mkdtemp()
    try:
        filters = []
        # Main caption: big, centered in the upper third, held the ENTIRE clip. This is
        # the doctor.running signature — the joke lives in the text, not the footage.
        mf = os.path.join(tmp, "main.txt")
        open(mf, "w", encoding="utf-8").write(_wrap(onscreen, 20))
        filters.append(
            f"drawtext=fontfile={font}:textfile={mf}:fontcolor=white:fontsize=62:"
            f"line_spacing=10:borderw=4:bordercolor=black@0.9:"
            f"box=1:boxcolor=black@0.35:boxborderw=22:"
            f"x=(w-text_w)/2:y=h*0.16"
        )
        # Optional punchline: appears in the final ~2s, centered lower third.
        punchline = (punchline or "").strip()
        if punchline:
            start = max(0.5, duration - 2.0)
            pf = os.path.join(tmp, "punch.txt")
            open(pf, "w", encoding="utf-8").write(_wrap(punchline, 22))
            filters.append(
                f"drawtext=fontfile={font}:textfile={pf}:fontcolor=yellow:fontsize=54:"
                f"line_spacing=8:borderw=4:bordercolor=black@0.9:"
                f"box=1:boxcolor=black@0.35:boxborderw=18:"
                f"x=(w-text_w)/2:y=h*0.66:enable='gte(t,{start:.2f})'"
            )

        cmd = ["ffmpeg", "-y", "-i", raw, "-vf", ",".join(filters),
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               out_path]
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
