"""quiet(): subprocess kwargs that stop console windows flashing up on Windows. Use **quiet() on every call."""
import subprocess
import sys


def quiet():
    if not sys.platform.startswith("win"):
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0            # SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": info}
