"""PIL thumbnails for previews (built on worker threads) and ffmpeg helpers for video frames and still detection."""
import os
import re
import shutil
import subprocess
import tempfile

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

from core.winproc import quiet

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def video_frame_path(video_path):
    """Extract one JPEG frame ~0.5s in. Returns a temp path or None."""
    if not FFMPEG_AVAILABLE:
        return None
    fd, out = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-ss", "0.5", "-i", video_path, "-frames:v", "1",
                        "-q:v", "3", out], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15, check=True, **quiet())
        if os.path.getsize(out) > 0:
            return out
    except Exception:
        pass
    try:
        os.remove(out)
    except OSError:
        pass
    return None


def _open_thumb(path, size):
    with Image.open(path) as im:
        im.thumbnail((size, size))
        return im.convert("RGB")


def make_thumb(file_path, media_type, size=240):
    """PIL thumbnail for an image or video frame; None for audio/unreadable."""
    if not HAVE_PIL or not os.path.exists(file_path):
        return None
    try:
        if media_type == "image":
            return _open_thumb(file_path, size)
        if media_type == "video":
            frame = video_frame_path(file_path)
            if frame:
                try:
                    return _open_thumb(frame, size)
                finally:
                    try:
                        os.remove(frame)
                    except OSError:
                        pass
    except Exception:
        return None
    return None


_ERROR_PAGE_STARTS = (b"<!doctype", b"<html", b"<head", b"<body", b"<?xml", b"{", b"[")


def looks_like_error_page(path):
    """True for an empty file or one that starts like an HTML/JSON/XML error page."""
    try:
        if os.path.getsize(path) == 0:
            return True
        with open(path, "rb") as f:
            head = f.read(64).lstrip().lower()
        return head.startswith(_ERROR_PAGE_STARTS)
    except OSError:
        return False


def is_static_video(path, min_seconds=1.0):
    """True if nearly every frame is identical (a photo made into a loop); False when unsure."""
    if not FFMPEG_AVAILABLE:
        return False
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-i", path, "-an",
             "-vf", "freezedetect=n=-50dB:d=1", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, **quiet())
    except Exception:
        return False
    out = proc.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m:
        return False
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if duration < min_seconds:
        return False
    starts = [float(x) for x in re.findall(r"freeze_start:\s*([0-9.]+)", out)]
    frozen = sum(float(x) for x in re.findall(r"freeze_duration:\s*([0-9.]+)", out))
    if len(starts) > len(re.findall(r"freeze_duration:", out)):   # froze right up to the end of the file
        frozen += max(0.0, duration - starts[-1])
    return frozen >= 0.9 * duration


def extract_still(video_path, out_path):
    """Save one full-resolution frame of a video as a JPEG. True on success."""
    if not FFMPEG_AVAILABLE:
        return False
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0.5",
                        "-i", video_path, "-frames:v", "1", "-q:v", "2", out_path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=True, **quiet())
        if os.path.getsize(out_path) > 0:
            return True
    except Exception:
        pass
    try:
        os.remove(out_path)
    except OSError:
        pass
    return False
