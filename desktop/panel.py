"""KeyScreen desktop companion: web panel (wallpapers, layout, heatmap) + foreground-app auto profile.

    python3 panel.py --board http://<board-ip>:8765 [--port 43125] [--no-watch]
"""

from __future__ import annotations

import argparse
import json
import os
import re
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


ROOT = Path(__file__).resolve().parents[3]  # repo root: scripts/agh.sh, work/keyscreen
AGH = ROOT / "scripts" / "agh.sh"


def ask_agnes(prompt: str, timeout: int = 240) -> dict:
    """Run one Agnes turn through AGH (print mode). The model acts on the keyboard via the MHS device."""
    env = {**os.environ, "HOME": os.environ.get("HOME") or str(Path.home()), "AGNES_HUB_ORIGIN": os.environ.get("AGNES_HUB_ORIGIN", "http://127.0.0.1:4180")}
    for k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)
    t0 = time.time()
    try:
        out = subprocess.run(["bash", str(AGH), "-p", prompt, "--cwd", str(ROOT / "work" / "keyscreen"), "--mode", "text"],
                             capture_output=True, text=True, timeout=timeout, env=env, cwd=str(ROOT / "work" / "keyscreen"))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Agnes 超时", "steps": [], "text": ""}
    steps, text = [], []
    for line in (out.stdout + out.stderr).splitlines():
        if re.match(r"^\s+at ", line) or "sk-" in line:
            continue
        if line.startswith("- tool "):
            steps.append(line[7:])
        else:
            text.append(line)
    return {"ok": out.returncode == 0, "text": "\n".join(text).strip(), "steps": steps, "seconds": round(time.time() - t0, 1),
            **({} if out.returncode == 0 else {"error": f"agh 退出码 {out.returncode}"})}


def chat_bridge(board: str, stop: threading.Event) -> None:
    """Carries the board's on-screen chat to Agnes: poll the queue, run AGH, post the reply back."""
    def post(path: str, body: dict) -> None:
        req = urllib.request.Request(board + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
    while not stop.wait(1.0):
        try:
            it = json.load(urllib.request.urlopen(board + "/api/chat/pending", timeout=3)).get("item")
        except Exception:
            continue
        if not it:
            continue
        print(f"[chat] #{it['id']} {it['prompt'][:60]}")
        res = ask_agnes(it["prompt"])
        text = res.get("text") or res.get("error") or "(无回复)"
        try:
            post("/api/chat/reply", {"id": it["id"], "text": text, "ok": bool(res.get("ok"))})
        except Exception as e:
            print(f"[chat] reply failed: {e}")


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/api/agnes":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            res = ask_agnes(str(body.get("prompt", ""))[:2000]) if body.get("prompt") else {"ok": False, "error": "empty prompt"}
        except Exception as e:  # never let the panel die on a bad request
            res = {"ok": False, "error": str(e)}
        data = json.dumps(res, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args) -> None:
        if "/api/agnes" in str(args[0] if args else ""):
            super().log_message(fmt, *args)


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
    threading.Thread(target=chat_bridge, args=(a.board, threading.Event()), daemon=True).start()
    handler = lambda *x, **k: Handler(*x, directory=str(web), **k)
    print(f"[panel] http://127.0.0.1:{a.port}  board={a.board}")
    ThreadingHTTPServer(("0.0.0.0", a.port), handler).serve_forever()


if __name__ == "__main__":
    main()
