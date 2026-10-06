import hashlib
import os
import re
import subprocess
import sys


def open_path(path):
    """Open a file/folder in the OS file manager."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def safe_name(name: str, default: str = "folder") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "").strip(" .")
    return cleaned or default


def _md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def dedupe_by_content(by_folder):
    """Keep the first of byte-identical files per folder (files stay on disk). Returns (by_folder, removed)."""
    removed, out = 0, {}
    for folder, items in by_folder.items():
        by_size = {}
        for it in items:
            try:
                by_size.setdefault(os.path.getsize(it["file_path"]), []).append(it)
            except OSError:
                pass
        drop = set()
        for group in by_size.values():
            if len(group) < 2:
                continue        # a unique size can't be a duplicate - skip hashing
            seen = set()
            for it in group:
                try:
                    digest = _md5(it["file_path"])
                except OSError:
                    continue
                if digest in seen:
                    drop.add(id(it))
                else:
                    seen.add(digest)
        out[folder] = [it for it in items if id(it) not in drop]
        removed += len(drop)
    return out, removed
