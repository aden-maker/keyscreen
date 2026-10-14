"""KeyScreen desktop companion: web panel (wallpapers, layout, heatmap) + foreground-app auto profile.

    python3 panel.py --board http://<board-ip>:8765 [--port 43125] [--no-watch]
"""

from __future__ import annotations

import argparse
import json
import math
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


PRETTY = {"code": "VS Code", "cursor": "Cursor", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "notepad": "记事本",
          "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "photoshop": "Photoshop", "wechat": "微信", "weixin": "微信",
          "qq": "QQ", "explorer": "资源管理器", "windowsterminal": "终端", "pycharm64": "PyCharm", "steam": "Steam", "bilibili": "哔哩哔哩"}
FG_PS = r"""Add-Type @"
using System;using System.Runtime.InteropServices;
public class FG{[DllImport("user32.dll")]public static extern IntPtr GetForegroundWindow();[DllImport("user32.dll")]public static extern int GetWindowThreadProcessId(IntPtr h,out int p);}
"@
$last=""
while($true){$p=0;[void][FG]::GetWindowThreadProcessId([FG]::GetForegroundWindow(),[ref]$p);try{$n=(Get-Process -Id $p).ProcessName}catch{$n=""}
if($n -ne $last){[Console]::Out.WriteLine($n);[Console]::Out.Flush();$last=$n};Start-Sleep -Milliseconds 700}"""


LANG_KLID = {"ru": "00000419", "fr": "0000040C", "de": "00000407"}  # Windows layouts shipped with every install
KL_PS = r"""Add-Type @"
using System;using System.Runtime.InteropServices;
public class KL{[DllImport("user32.dll")]public static extern IntPtr LoadKeyboardLayout(string id,uint f);[DllImport("user32.dll")]public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")]public static extern IntPtr GetKeyboardLayout(int t);[DllImport("user32.dll")]public static extern int GetWindowThreadProcessId(IntPtr h,IntPtr p);
[DllImport("user32.dll")]public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);}
"@
$w=[KL]::GetForegroundWindow();[Console]::Out.WriteLine([KL]::GetKeyboardLayout([KL]::GetWindowThreadProcessId($w,[IntPtr]::Zero)).ToInt64())
$h=if("MODE" -eq "load"){[KL]::LoadKeyboardLayout("VAL",1)}else{[IntPtr][long]"VAL"};[void][KL]::PostMessage($w,0x50,[IntPtr]::Zero,$h)"""


def host_layout(lang: str, home: list) -> None:
    """Switch the foreground Windows app to the layout matching the board's legends; 'en' restores the user's own."""
    import base64
    target = LANG_KLID.get(lang) or (home[0] if home else None)
    ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if not target or not Path(ps).exists():
        return
    enc = base64.b64encode(KL_PS.replace("MODE", "load" if lang in LANG_KLID else "hkl").replace("VAL", str(target)).encode("utf-16-le")).decode()
    out = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], capture_output=True, text=True, timeout=20).stdout.split()
    if out and not home and lang in LANG_KLID:
        home.append(out[0])


def lang_sync(board: str, stop: threading.Event) -> None:
    last, home = "en", []
    while not stop.wait(1.5):
        try:
            lang = json.load(urllib.request.urlopen(board + "/api/state", timeout=3))["profile"].get("lang", "en")
            if lang != last:
                host_layout(lang, home)
                print(f"[lang] {last} -> {lang}")
            last = lang
        except Exception:
            pass


def board_post(board: str, path: str, body: dict) -> None:
    req = urllib.request.Request(board + path, data=json.dumps(body, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()


def foreground_stream(stop: threading.Event):
    """Yields foreground app names. Under WSL the PC's apps are Windows processes, so ask PowerShell."""
    if "microsoft" in Path("/proc/version").read_text().lower() if Path("/proc/version").exists() else False:
        import base64
        ps = next((p for p in ("powershell.exe", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe") if subprocess.run(["which", p], capture_output=True).returncode == 0 or Path(p).exists()), None)
        if ps:
            enc = base64.b64encode(FG_PS.encode("utf-16-le")).decode()
            proc = subprocess.Popen([ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in proc.stdout:
                if stop.is_set():
                    proc.kill()
                    return
                yield line.strip().lower()
            return
    while not stop.wait(1.0):
        yield foreground_app()


def watch(board: str, stop: threading.Event) -> None:
    last, said = None, 0.0
    while not stop.is_set():
        try:
            for app in foreground_stream(stop):
                if not app or app == last or app in ("powershell", "conhost", "searchhost", "shellexperiencehost", "lockapp"):
                    continue
                last = app
                try:
                    profiles = json.load(urllib.request.urlopen(board + "/api/state", timeout=3))["profiles"]
                    target = app if app in profiles else "default"
                    urllib.request.urlopen(urllib.request.Request(f"{board}/api/active/{target}", method="POST"), timeout=3)
                    name = PRETTY.get(app, app)
                    if time.time() - said > 4:
                        board_post(board, "/api/pet/say", {"text": f"你切到了 {name}～" + (f"已换成 {target} 键位" if target != "default" else ""), "secs": 4})
                        said = time.time()
                    print(f"[watch] {app} -> profile {target}")
                except Exception as e:
                    print(f"[watch] board unreachable: {e}")
        except Exception as e:
            print(f"[watch] foreground detection failed: {e}")
        stop.wait(5)


def supervise_device(board: str, hub: str, stop: threading.Event) -> None:
    """Keeps the MHS device bridge (keyscreen-01 on AgnesHub) alive; WSL restarts used to leave the hub empty."""
    here = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "agnes-harness/packages/mhs/python/src")}
    subprocess.run(["pkill", "-f", "board/mhs_device.py"], capture_output=True)
    Path("/tmp/keyscreen-demo").mkdir(exist_ok=True)
    while not stop.is_set():
        with open("/tmp/keyscreen-demo/device.log", "a") as log:
            p = subprocess.Popen([sys.executable, str(here / "board/mhs_device.py"), hub, "--board", board], stdout=log, stderr=log, env=env, cwd=str(here))
            print(f"[device] keyscreen-01 bridge pid {p.pid} -> {hub}")
            while p.poll() is None and not stop.wait(2):
                pass
        if not stop.is_set():
            print(f"[device] bridge exited ({p.returncode}); restarting in 3 s")
            stop.wait(3)


def weather(city: str) -> dict:
    """wttr.in j1 -> the board's weather card: current, today's high/low, next five 3-hour slots."""
    try:
        u = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=zh-cn"
        j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "curl/8"}), timeout=15).read())
    except Exception:
        return {}
    cur = j["current_condition"][0]
    zh = lambda e: next((v[0]["value"] for k, v in e.items() if k.startswith("lang_zh") and v), e["weatherDesc"][0]["value"])
    days = j.get("weather") or []
    now_h = time.localtime().tm_hour
    hourly = [{"label": "现在", "code": int(cur["weatherCode"]), "temp": int(cur["temp_C"]), "hour": now_h}]
    for di, day in enumerate(days[:2]):
        for h in day.get("hourly", []):
            hr = int(h["time"]) // 100
            if (di == 0 and hr > now_h) or di == 1:
                hourly.append({"label": f"{hr}时", "code": int(h["weatherCode"]), "temp": int(h["tempC"]), "hour": hr})
    return {"city": city, "temp": int(cur["temp_C"]), "desc": zh(cur).strip(), "code": int(cur["weatherCode"]),
            "hi": int(days[0]["maxtempC"]) if days else None, "lo": int(days[0]["mintempC"]) if days else None,
            "hourly": hourly[:6]}


def next_event() -> str:
    """desktop/schedule.txt: one event per line, `HH:MM text` (daily) or `YYYY-MM-DD HH:MM text`."""
    f = Path(__file__).resolve().parent / "schedule.txt"
    if not f.exists():
        return ""
    now, today, best = time.strftime("%H:%M"), time.strftime("%Y-%m-%d"), None
    for line in f.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=2)
        if not parts or line.lstrip().startswith("#"):
            continue
        if re.match(r"\d{4}-\d{2}-\d{2}$", parts[0]):
            if parts[0] != today or len(parts) < 3:
                continue
            parts = parts[1:]
        else:
            parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and re.match(r"\d{1,2}:\d{2}$", parts[0]) and parts[0].zfill(5) >= now:
            best = min(best or (parts[0].zfill(5), parts[1]), (parts[0].zfill(5), parts[1]))
    return f"{best[0]} {best[1]}" if best else ""


def info_loop(board: str, city: str, stop: threading.Event) -> None:
    """Info line every minute; once an hour Agnes turns weather + next event into one cute sentence for the pet."""
    cache = Path("/tmp/keyscreen-demo/weather.json")
    try:
        wd = json.loads(cache.read_text(encoding="utf-8"))  # offline at the venue: show the last good forecast
    except Exception:
        wd = {}
    w_at, told = 0.0, 0.0
    while not stop.is_set():
        if time.time() - w_at > (600 if wd else 60):
            new, w_at = weather(city), time.time()
            if new:
                wd = new
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(wd, ensure_ascii=False), encoding="utf-8")
        ev = next_event()
        w = f"{wd['desc']} {wd['temp']}°C" if wd else ""
        line = f"下一项 {ev}" if ev else ""
        try:
            if wd:  # every loop, so a rebooted board gets its card back within a minute
                board_post(board, "/api/widgets/weather", wd)
            board_post(board, "/api/widgets/info", {"text": line})
            if line and time.time() - told > 3600:
                told = time.time()
                r = ask_agnes(f"现在 {time.strftime('%H:%M')}。天气：{w or '未知'}；下一项日程：{ev or '无'}。"
                              "用一句不超过 30 字、可爱的二次元口吻提醒我。只输出这句话，不要调用工具。", timeout=120)
                if r.get("ok") and r.get("text"):
                    board_post(board, "/api/pet/say", {"text": r["text"].splitlines()[-1][:80], "secs": 15})
        except Exception as e:
            print(f"[info] {e}")
        stop.wait(60)


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


def offline_reply(board: str, prompt: str) -> str:
    """Agnes unreachable (no network / quota): handle the four on-screen presets with local rules so the demo goes on."""
    def call(method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(board + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"}, method=method)
        return json.load(urllib.request.urlopen(req, timeout=5))
    tag = "（离线模式）"
    try:
        want = next((c for c, words in (("ru", ("俄语", "俄文")), ("fr", ("法语", "法文")), ("de", ("德语", "德文")), ("en", ("英语", "英文")),
                                        ("next", ("set_language", "换语言", "切换语言"))) if any(w in prompt for w in words)), None)
        if want:
            r = call("POST", "/api/lang", {"lang": want})
            return tag + f"键盘已切换为{r['name']}布局～"
        if "校准" in prompt or "adjust_key" in prompt:
            ks = [k for k in call("GET", "/api/touch/stats?since=0")["keys"] if k["count"] >= 10 and k["key"] != "Fn"]
            ks = sorted(ks, key=lambda k: -math.hypot(k["avg_dx"], k["avg_dy"]))[:2]
            clamp = lambda v: max(-15.0, min(15.0, v / 2))
            for k in ks:
                call("POST", "/api/keys/adjust", {"key": k["key"], "dx": clamp(k["avg_dx"]), "dy": clamp(k["avg_dy"])})
            return tag + ("已按平均偏移的一半微调：" + "、".join(f"{k['key']}({clamp(k['avg_dx']):+.0f},{clamp(k['avg_dy']):+.0f})" for k in ks)
                          if ks else "按键数据还不够，多打几个字再来～")
        if "分析" in prompt or "总结" in prompt:
            s = call("GET", "/api/touch/stats?since=0")
            worst = max((k for k in s["keys"] if k["count"] >= 10), key=lambda k: math.hypot(k["avg_dx"], k["avg_dy"]), default=None)
            return tag + f"共 {s['total']} 次按键，误触率 {s['miss_rate'] * 100:.1f}%" + (
                f"，最容易按偏的是 {worst['key']}（平均偏 {worst['avg_dx']:+.0f},{worst['avg_dy']:+.0f} px），可以试试「校准按键」。" if worst else "。")
        if "壁纸" in prompt or "配色" in prompt:
            walls = call("GET", "/api/wallpapers")["wallpapers"]
            if walls:
                code = "代码" in prompt
                p = call("GET", "/api/profile/default")["profile"]
                cur = walls.index(p.get("wallpaper")) if p.get("wallpaper") in walls else -1
                p.update(wallpaper=walls[(cur + 1) % len(walls)], theme="#38bdf8" if code else "#ff8ac6")
                call("PUT", "/api/profile/default", p)
                return tag + f"换成了「{p['wallpaper']}」，主题色{'天蓝' if code else '樱花粉'}～"
    except Exception as e:
        return tag + f"本地处理失败：{str(e)[:60]}"
    return tag + "Agnes 暂时连不上（网络或额度问题），快捷指令「校准按键 / 分析打字 / 换壁纸」在离线时也能用哦～"


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
        res = ask_agnes(it["prompt"], timeout=90)
        text = res.get("text") or res.get("error") or "(无回复)"
        if not res.get("ok") or not res.get("text"):
            print(f"[chat] Agnes unavailable ({res.get('error')}), local fallback")
            text, res = offline_reply(board, it["prompt"]), {"ok": True}
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
    ap.add_argument("--hub", default=os.environ.get("HUB", "ws://127.0.0.1:4180"), help="AgnesHub for the keyscreen-01 bridge; '' to not run it")
    ap.add_argument("--city", default=os.environ.get("KS_CITY", "南京"))
    a = ap.parse_args()
    ev = threading.Event()
    if a.hub:
        threading.Thread(target=supervise_device, args=(a.board, a.hub, ev), daemon=True).start()
    threading.Thread(target=info_loop, args=(a.board, a.city, ev), daemon=True).start()
    web = Path(__file__).resolve().parent / "web"
    (web / "config.js").write_text(f"window.BOARD = {json.dumps(a.board)};\n")
    if not a.no_watch:
        threading.Thread(target=watch, args=(a.board, threading.Event()), daemon=True).start()
    threading.Thread(target=chat_bridge, args=(a.board, threading.Event()), daemon=True).start()
    threading.Thread(target=lang_sync, args=(a.board, threading.Event()), daemon=True).start()
    handler = lambda *x, **k: Handler(*x, directory=str(web), **k)
    print(f"[panel] http://127.0.0.1:{a.port}  board={a.board}")
    ThreadingHTTPServer(("0.0.0.0", a.port), handler).serve_forever()


if __name__ == "__main__":
    main()
