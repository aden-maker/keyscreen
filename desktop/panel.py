"""KeyScreen desktop companion: web panel (wallpapers, layout, heatmap) + foreground-app auto profile.

    python3 panel.py --board http://<board-ip>:8765 [--port 43125] [--no-watch]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def foreground_app() -> str | None:
    try:
        if sys.platform == "win32":
            import win32gui, win32process, psutil  # pip install pywin32 psutil
            _, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
            return Path(psutil.Process(pid).name()).stem.lower()
        if sys.platform == "darwin":
            out = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first process whose frontmost is true'], capture_output=True, text=True, timeout=2)
            return out.stdout.strip().lower() or None
        wid = subprocess.run(["xdotool", "getactivewindow", "getwindowpid"], capture_output=True, text=True, timeout=2).stdout.strip()
        return Path(open(f"/proc/{wid}/comm").read().strip()).stem.lower() if wid else None
    except Exception:
        return None


def watch(board: str, stop: threading.Event) -> None:
    last = None
    while not stop.wait(1.0):
        app = foreground_app()
        if not app or app == last:
            continue
        try:
            profiles = json.load(urllib.request.urlopen(board + "/api/state", timeout=3))["profiles"]
            target = app if app in profiles else "default"
            urllib.request.urlopen(urllib.request.Request(f"{board}/api/active/{target}", method="POST"), timeout=3)
            print(f"[watch] {app} -> profile {target}")
            last = app
        except Exception as e:
            print(f"[watch] board unreachable: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="http://127.0.0.1:8765")
    ap.add_argument("--port", type=int, default=43125)
    ap.add_argument("--no-watch", action="store_true")
    a = ap.parse_args()
    web = Path(__file__).resolve().parent / "web"
    (web / "config.js").write_text(f"window.BOARD = {json.dumps(a.board)};\n")
    if not a.no_watch:
        threading.Thread(target=watch, args=(a.board, threading.Event()), daemon=True).start()
    handler = lambda *x, **k: SimpleHTTPRequestHandler(*x, directory=str(web), **k)
    print(f"[panel] http://127.0.0.1:{a.port}  board={a.board}")
    ThreadingHTTPServer(("0.0.0.0", a.port), handler).serve_forever()


if __name__ == "__main__":
    main()
