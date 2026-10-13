"""KeyScreen board runtime for LubanCat 1H: touch display acting as a dynamic USB keyboard.

    python3 keyscreen.py                 # board: fullscreen, evdev touch, /dev/hidg0
    python3 keyscreen.py --sim           # desktop: window, mouse = finger, HID logged
    python3 keyscreen.py --sim --headless  # CI / tests: no window

One process: a pygame renderer on the main thread (wallpaper, keycaps, press effects, module bar),
touch input (evdev ABS_MT or mouse), USB HID reports, a SQLite touch log and an
aiohttp HTTP/WS API + web client (/ui/) on :8765 running on a background asyncio loop.

Keyboard behaviour follows a membrane keyboard: make code on finger down, break code on finger up
(the host does typematic repeat), 6-key rollover boot reports. Keys are drawn as legends only,
filling the bottom half of the screen. Touch -> HID write happens on the touch thread; rendering never blocks it.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import io
import json
import math
import os
import queue
import random
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("KEYSCREEN_HOME", HERE / "data"))
WALL = ROOT / "wallpapers"
FXDIR = ROOT / "effects"
WEB = next((p for p in (HERE.parent / "web", HERE.parent / "desktop" / "web") if (p / "index.html").exists()), None)
W, H = 1920, 1080
BAR_H = 90
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
VID_EXT = (".mp4", ".webm", ".mov", ".mkv")
ANIM_EXT = (".gif", ".webp") + VID_EXT  # animated wallpapers: decoded once by ffmpeg (or PIL) into a raw frame cache
ANIM = ROOT / "anim"
AW, AH = W // 2, H // 2  # animated frames are cached at half size and scaled up when drawn (~2 MB per frame)
ANIM_FPS = float(os.environ.get("KEYSCREEN_ANIM_FPS", 15))
ANIM_MAX_S = float(os.environ.get("KEYSCREEN_ANIM_SECONDS", 6))


# label, HID usage, width units. Modifiers use usage 0xE0..0xE7 and go to byte 0.
LAYOUT = [
    [("Esc", 0x29, 1), ("1", 0x1E, 1), ("2", 0x1F, 1), ("3", 0x20, 1), ("4", 0x21, 1), ("5", 0x22, 1), ("6", 0x23, 1), ("7", 0x24, 1), ("8", 0x25, 1), ("9", 0x26, 1), ("0", 0x27, 1), ("-", 0x2D, 1), ("=", 0x2E, 1), ("Bksp", 0x2A, 2)],
    [("Tab", 0x2B, 1.5), ("Q", 0x14, 1), ("W", 0x1A, 1), ("E", 0x08, 1), ("R", 0x15, 1), ("T", 0x17, 1), ("Y", 0x1C, 1), ("U", 0x18, 1), ("I", 0x0C, 1), ("O", 0x12, 1), ("P", 0x13, 1), ("[", 0x2F, 1), ("]", 0x30, 1), ("\\", 0x31, 1.5)],
    [("Caps", 0x39, 1.75), ("A", 0x04, 1), ("S", 0x16, 1), ("D", 0x07, 1), ("F", 0x09, 1), ("G", 0x0A, 1), ("H", 0x0B, 1), ("J", 0x0D, 1), ("K", 0x0E, 1), ("L", 0x0F, 1), (";", 0x33, 1), ("'", 0x34, 1), ("Enter", 0x28, 2.25)],
    [("Shift", 0xE1, 2.25), ("Z", 0x1D, 1), ("X", 0x1B, 1), ("C", 0x06, 1), ("V", 0x19, 1), ("B", 0x05, 1), ("N", 0x11, 1), ("M", 0x10, 1), (",", 0x36, 1), (".", 0x37, 1), ("/", 0x38, 1), ("RShift", 0xE5, 2.75)],
    [("Ctrl", 0xE0, 1.5), ("Win", 0xE3, 1.25), ("Alt", 0xE2, 1.25), ("Space", 0x2C, 6.5), ("RAlt", 0xE6, 1.25), ("Fn", 0, 1.25), ("RCtrl", 0xE4, 2)],
]
# The keyboard fills the bottom half of the screen; the top half is reserved for widgets.
KB_X, KB_Y, KB_W, KB_H = 0, H / 2, W, H / 2
UNIT_X, UNIT_Y = KB_W / 15, KB_H / len(LAYOUT)
UNIT = min(UNIT_X, UNIT_Y)  # scale for effects
GAP = 8
RADIUS = int(UNIT * 0.12)
EFFECTS = ["none", "glow", "ripple", "burst", "image"]
DEFAULT_PROFILE = {"wallpaper": None, "theme": "#38bdf8", "opacity": 170, "legends": {}, "offsets": {}, "modules": ["clock", "app", "wpm"],
                   "effect": "ripple", "effect_color": "", "effect_ms": 450, "effect_image": None, "key_effects": {}}


def build_keys(offsets: dict) -> list[dict]:
    keys = []
    for r, row in enumerate(LAYOUT):
        x = KB_X
        for label, code, w in row:
            dx, dy = offsets.get(label, [0, 0])
            keys.append({"label": label, "code": code, "rect": [round(x + GAP / 2 + dx, 1), round(KB_Y + r * UNIT_Y + GAP / 2 + dy, 1), round(w * UNIT_X - GAP, 1), round(UNIT_Y - GAP, 1)]})
            x += w * UNIT_X
    return keys


class Store:
    """Profiles, wallpapers, effect images and the touch log. Thread-safe; the API and renderer share it."""

    def __init__(self) -> None:
        for d in (WALL, FXDIR, ANIM):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.anim_status: dict[str, str] = {}  # name -> converting | ready | error: ...
        self.pfile = ROOT / "profiles.json"
        self.profiles = json.loads(self.pfile.read_text()) if self.pfile.exists() else {"default": dict(DEFAULT_PROFILE)}
        self.active = "default"
        self.db = sqlite3.connect(str(ROOT / "touch.db"), check_same_thread=False)
        self.db.execute("create table if not exists touch(t real, x real, y real, key text, dx real, dy real, duration real, hit integer, profile text)")
        self.dirty = True
        self.listeners: list = []
        self.keys = build_keys({})
        self.relayout()
        self.logq: queue.Queue = queue.Queue()
        threading.Thread(target=self._writer, daemon=True).start()

    def profile(self, name: str | None = None) -> dict:
        with self.lock:
            return {**DEFAULT_PROFILE, **self.profiles.get(name or self.active, {})}

    def save(self) -> None:
        with self.lock:
            self.pfile.write_text(json.dumps(self.profiles, ensure_ascii=False, indent=1))
            self.relayout()

    def relayout(self) -> None:
        self.keys = build_keys(self.profile()["offsets"])
        self.dirty = True

    def put_profile(self, name: str, patch: dict) -> dict:
        with self.lock:
            p = {**DEFAULT_PROFILE, **self.profiles.get(name, {})}
            for k, v in patch.items():
                if k in DEFAULT_PROFILE:
                    p[k] = v
            self.profiles[name] = p
            self.save()
        self.emit({"type": "profile", "name": name})
        return p

    def activate(self, name: str) -> None:
        with self.lock:
            self.profiles.setdefault(name, dict(DEFAULT_PROFILE))
            self.active = name
            self.relayout()
        self.emit({"type": "active", "name": name})

    def adjust_key(self, label: str, dx: float, dy: float, profile: str | None = None) -> list:
        name = profile or self.active
        with self.lock:
            p = self.profiles.setdefault(name, dict(DEFAULT_PROFILE))
            offs = dict(p.get("offsets", {}))
            ox, oy = offs.get(label, [0, 0])
            offs[label] = [max(-40, min(40, ox + dx)), max(-40, min(40, oy + dy))]
            p["offsets"] = offs
            self.save()
        return offs[label]

    def log_touch(self, rec: dict) -> None:
        self.logq.put((rec, self.active))  # sqlite commit (fsync on SD) must never run on the touch thread

    def _writer(self) -> None:
        while True:
            batch = [self.logq.get()]
            while not self.logq.empty():
                batch.append(self.logq.get())
            with self.lock:
                self.db.executemany("insert into touch values(?,?,?,?,?,?,?,?,?)", [(r["t"], r["x"], r["y"], r["key"], r["dx"], r["dy"], r["duration"], int(r["hit"]), prof) for r, prof in batch])
                self.db.commit()
            for r, _ in batch:
                self.emit({"type": "touch", **r})

    def stats(self, since: float = 0) -> dict:
        with self.lock:
            rows = self.db.execute("select key, count(*), sum(hit), avg(dx), avg(dy), avg(duration) from touch where t>=? group by key order by count(*) desc", (since,)).fetchall()
            total, hits = self.db.execute("select count(*), coalesce(sum(hit),0) from touch where t>=?", (since,)).fetchone()
        keys = [{"key": k, "count": n, "miss_rate": round(1 - (h or 0) / n, 3), "avg_dx": round(ax or 0, 1), "avg_dy": round(ay or 0, 1), "avg_ms": round((d or 0) * 1000, 1)} for k, n, h, ax, ay, d in rows]
        return {"total": total, "miss_rate": round(1 - hits / total, 3) if total else 0, "keys": keys}

    def emit(self, ev: dict) -> None:
        for q in list(self.listeners):
            q(ev)

    def wallpapers(self) -> list[str]:
        return sorted(p.name for p in WALL.iterdir() if p.suffix.lower() in IMG_EXT + VID_EXT)

    # --- animated wallpapers -------------------------------------------------------------------
    @staticmethod
    def is_anim(name: str | None) -> bool:
        return bool(name) and Path(name).suffix.lower() in ANIM_EXT

    def anim_meta(self, name: str) -> dict | None:
        m = ANIM / (name + ".json")
        try:
            return json.loads(m.read_text()) if m.exists() and (ANIM / (name + ".rgb")).exists() else None
        except (OSError, ValueError):
            return None

    def ensure_anim(self, name: str) -> str:
        """Return the cache status for an animated wallpaper, starting a background conversion if needed."""
        if self.anim_meta(name):
            self.anim_status[name] = "ready"
        elif self.anim_status.get(name) != "converting" and not self.anim_status.get(name, "").startswith("error"):
            self.anim_status[name] = "converting"
            threading.Thread(target=self._convert, args=(name,), daemon=True).start()
        return self.anim_status[name]

    def drop_anim(self, name: str) -> None:
        self.anim_status.pop(name, None)
        for p in (ANIM / (name + ".rgb"), ANIM / (name + ".json"), ANIM / (name + ".rgb.tmp")):
            if p.exists():
                p.unlink()

    def _convert(self, name: str) -> None:
        src, tmp = WALL / name, ANIM / (name + ".rgb.tmp")
        n = max(1, int(ANIM_FPS * ANIM_MAX_S))
        try:
            if shutil.which("ffmpeg"):
                vf = f"fps={ANIM_FPS},scale={AW}:{AH}:force_original_aspect_ratio=increase,crop={AW}:{AH}"
                r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", str(tmp)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900)
                if r.returncode:
                    raise RuntimeError(r.stderr.decode(errors="replace").strip().splitlines()[-1:] or "ffmpeg failed")
            elif src.suffix.lower() in (".gif", ".webp"):
                self._pil_convert(src, tmp, n)
            else:
                raise RuntimeError("video wallpapers need ffmpeg on the board")
            frames = tmp.stat().st_size // (AW * AH * 3)
            if frames < 1:
                raise RuntimeError("no frames decoded")
            tmp.rename(ANIM / (name + ".rgb"))
            (ANIM / (name + ".json")).write_text(json.dumps({"w": AW, "h": AH, "fps": ANIM_FPS, "frames": frames}))
            self.anim_status[name] = "ready"
        except Exception as e:
            self.anim_status[name] = f"error: {str(e)[:160]}"
            print(f"[anim] {name}: {e}", file=sys.stderr)
        finally:
            if tmp.exists():
                tmp.unlink()
        if self.profile()["wallpaper"] == name:
            self.dirty = True
        self.emit({"type": "wallpapers", "ready": name, "status": self.anim_status[name]})

    @staticmethod
    def _pil_convert(src: Path, out: Path, n: int) -> None:
        from PIL import Image, ImageSequence

        im, step, acc, count = Image.open(str(src)), 1000 / ANIM_FPS, 0.0, 0
        with open(out, "wb") as f:
            for fr in ImageSequence.Iterator(im):
                acc += fr.info.get("duration") or 100
                if acc < step:
                    continue
                rgb = fr.convert("RGB")
                s = max(AW / rgb.width, AH / rgb.height)
                rgb = rgb.resize((math.ceil(rgb.width * s), math.ceil(rgb.height * s)), Image.BILINEAR)
                x, y = (rgb.width - AW) // 2, (rgb.height - AH) // 2
                data = rgb.crop((x, y, x + AW, y + AH)).tobytes()
                while acc >= step and count < n:  # resample the GIF's own timing to ANIM_FPS
                    f.write(data)
                    acc -= step
                    count += 1
                if count >= n:
                    break

    def effect_images(self) -> list[str]:
        return sorted(p.name for p in FXDIR.iterdir() if p.suffix.lower() in IMG_EXT)


class Hid:
    """6KRO boot keyboard reports to /dev/hidg0; falls back to a log in simulation.

    Keys are held while the finger is down. A modifier tapped on its own latches for the next key
    (one-shot, tap again to cancel); a modifier held while another key is pressed works as a normal chord.
    """

    def __init__(self, path: str = "/dev/hidg0") -> None:
        self.f = None
        try:
            self.f = open(path, "wb", buffering=0)
        except OSError:
            print(f"[hid] {path} unavailable, logging reports", file=sys.stderr)
        self.mods = self.oneshot = 0
        self.chorded = 0
        self.keys: list[int] = []
        self.sent: list[bytes] = []
        self.lock = threading.Lock()

    def _send(self) -> None:
        r = bytes([self.mods | self.oneshot, 0] + (self.keys + [0] * 6)[:6])
        self.sent = (self.sent + [r])[-50:]
        if self.f:
            try:
                self.f.write(r)
            except OSError as e:
                print(f"[hid] write failed: {e}", file=sys.stderr)

    def press(self, code: int) -> None:
        with self.lock:
            if 0xE0 <= code <= 0xE7:
                bit = 1 << (code - 0xE0)
                self.mods |= bit
                self.chorded &= ~bit
            else:
                if code in self.keys or len(self.keys) >= 6:
                    return
                self.keys.append(code)
                self.chorded |= self.mods
            self._send()

    def release(self, code: int) -> None:
        with self.lock:
            if 0xE0 <= code <= 0xE7:
                bit = 1 << (code - 0xE0)
                self.mods &= ~bit
                if not self.chorded & bit:
                    self.oneshot ^= bit
            else:
                if code not in self.keys:
                    return
                self.keys.remove(code)
                if not self.keys:
                    self.oneshot = 0
            self._send()


def hit_test(keys: list[dict], x: float, y: float) -> tuple[dict | None, bool, float, float]:
    """The visual gap belongs to the key (like the plate under a membrane keycap); beyond one pitch is free space."""
    best, bd = None, 1e18
    g = GAP / 2
    for k in keys:
        rx, ry, rw, rh = k["rect"]
        cx, cy = rx + rw / 2, ry + rh / 2
        if rx - g <= x <= rx + rw + g and ry - g <= y <= ry + rh + g:
            return k, True, x - cx, y - cy
        d = (x - cx) ** 2 + (y - cy) ** 2
        if d < bd:
            best, bd = k, d
    if best is None or bd > UNIT_X ** 2:
        return None, False, 0, 0
    rx, ry, rw, rh = best["rect"]
    return best, False, x - (rx + rw / 2), y - (ry + rh / 2)


class Engine:
    """Touch down/up to key make/break; shared by evdev, mouse and the API's /touch/inject."""

    def __init__(self, store: Store, hid: Hid) -> None:
        self.store, self.hid = store, hid
        self.active: dict[int, dict] = {}
        self.pressed_view: tuple = ()
        self.typed: list[float] = []
        self.latency_ms: collections.deque = collections.deque(maxlen=200)
        self.on_press = lambda label, x, y: None
        self.widgets = None  # set by Renderer; owns the top area (pet + Agnes chat box)
        self.n_touch = self.n_miss = 0

    def touch_down(self, slot: int, x: float, y: float, ts: float | None = None) -> None:
        if slot in self.active:
            self.touch_up(slot)
        t0 = ts or time.time()
        if y < BAR_H:
            self.active[slot] = {"bar": True, "x": x}
            return
        if y < KB_Y and self.widgets is not None:
            self.active[slot] = {"bar": True, "x": x, "widget": True}
            try:
                self.widgets.tap(x, y)
            except Exception as e:
                print(f"[widgets] tap failed: {e!r}", file=sys.stderr)
            return
        key, hit, dx, dy = hit_test(self.store.keys, x, y)
        rec = {"t": t0, "x": round(x, 1), "y": round(y, 1), "key": key["label"] if key else None, "dx": round(dx, 1), "dy": round(dy, 1), "hit": hit, "code": key["code"] if key and hit else 0}
        if key and hit and self.widgets is not None:
            try:
                if self.widgets.key(key["label"], x):  # chat box focused: the key goes to Agnes, not to the PC
                    rec["code"] = 0
            except Exception as e:
                print(f"[widgets] key failed: {e!r}", file=sys.stderr)
        self.active[slot] = rec
        if rec["code"]:
            self.hid.press(rec["code"])
            self.latency_ms.append((time.time() - t0) * 1000)
        if key and hit:
            self.pressed_view = tuple(r["key"] for r in self.active.values() if r.get("hit"))
            self.typed = [t for t in self.typed if t > t0 - 60] + [t0]
            self.on_press(key["label"], x, y)

    def touch_up(self, slot: int) -> dict | None:
        rec = self.active.pop(slot, None)
        if rec is None:
            return None
        if rec.get("bar"):
            if not rec.get("widget"):
                self.store.emit({"type": "bar", "x": rec["x"]})
            return None
        self.n_touch += 1
        self.n_miss += 0 if rec["hit"] else 1
        if rec["code"]:
            self.hid.release(rec.pop("code"))
        rec.pop("code", None)
        self.pressed_view = tuple(r["key"] for r in self.active.values() if r.get("hit"))
        rec["duration"] = round(time.time() - rec["t"], 3)
        if rec["key"] is None:
            self.store.emit({"type": "free", "x": rec["x"], "y": rec["y"]})  # space above the keyboard, reserved for widgets
            return rec
        self.store.log_touch(rec)
        return rec


def evdev_loop(engine: Engine, stop: threading.Event) -> None:
    try:
        import evdev  # apt install python3-evdev on the board
    except ImportError:
        print("[touch] python-evdev missing; touch disabled", file=sys.stderr)
        return
    E = evdev.ecodes
    # The panel's USB can drop (cable, power dip) and re-enumerate; keep waiting and re-open it instead of dying.
    warned = False
    while not stop.is_set():
        try:
            dev = next((evdev.InputDevice(p) for p in evdev.list_devices() if E.ABS_MT_POSITION_X in dict(evdev.InputDevice(p).capabilities().get(E.EV_ABS, []))), None)
        except OSError:
            dev = None
        if dev is None:
            if not warned:
                print("[touch] no multitouch device; waiting for hot-plug", file=sys.stderr)
                warned = True
            stop.wait(1.0)
            continue
        warned = False
        try:
            _touch_session(dev, engine, stop, E)
        except OSError as e:
            print(f"[touch] device lost ({e}); releasing keys, waiting for re-plug", file=sys.stderr)
        finally:
            for s in list(getattr(engine, "active", {}) or {}):
                try:
                    engine.touch_up(s)
                except Exception:
                    pass
            try:
                dev.close()
            except Exception:
                pass
        stop.wait(0.5)


def _touch_session(dev, engine: Engine, stop: threading.Event, E) -> None:
    absinfo = dict(dev.capabilities(absinfo=True)[E.EV_ABS])  # InputDevice.absinfo() needs evdev >= 1.2
    ax, ay = absinfo[E.ABS_MT_POSITION_X], absinfo[E.ABS_MT_POSITION_Y]
    try:
        dev.grab()  # under X the touchscreen is also a pointer; without this every tap fires twice
    except OSError as e:
        print(f"[touch] grab failed ({e}); another process may own the touchscreen", file=sys.stderr)
    print(f"[touch] {dev.name} {ax.max}x{ay.max}", file=sys.stderr)
    slot, pos, downs, ups = 0, {}, set(), set()
    # MT protocol B: a new contact's TRACKING_ID arrives before its X/Y, so act on SYN_REPORT, not on the ID.
    for ev in dev.read_loop():
        if stop.is_set():
            return
        if ev.type == E.EV_ABS:
            c = ev.code
            if c == E.ABS_MT_SLOT:
                slot = ev.value
            elif c == E.ABS_MT_POSITION_X:
                pos.setdefault(slot, [0, 0])[0] = (ev.value - ax.min) * W / (ax.max - ax.min)
            elif c == E.ABS_MT_POSITION_Y:
                pos.setdefault(slot, [0, 0])[1] = (ev.value - ay.min) * H / (ay.max - ay.min)
            elif c == E.ABS_MT_TRACKING_ID:
                if ev.value == -1:
                    ups.add(slot)
                    downs.discard(slot)
                else:
                    downs.add(slot)
        elif ev.type == E.EV_SYN and ev.code == E.SYN_REPORT:
            for s in ups:
                engine.touch_up(s)
            for s in downs:
                if s in pos:
                    engine.touch_down(s, pos[s][0], pos[s][1], ev.timestamp())
            ups.clear()
            downs.clear()


def hex_color(pg, v, fallback):
    try:
        return pg.Color(v) if isinstance(v, str) and v.startswith("#") else fallback
    except ValueError:
        return fallback


class Renderer:
    """Static layer (wallpaper + keycaps) is cached; each frame only repaints pressed keys, effects and the clock."""

    def __init__(self, store: Store, engine: Engine, sim: bool, headless: bool) -> None:
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
        import pygame

        self.pg = pg = pygame
        pg.init()
        flags = 0 if sim else pg.FULLSCREEN | pg.NOFRAME
        size = (W // 2, H // 2) if sim and not headless else (W, H)
        self.screen = pg.display.set_mode(size, flags)
        pg.display.set_caption("KeyScreen sim — mouse = finger")
        pg.mouse.set_visible(sim)
        self.scale = W / size[0]
        self.canvas = self.screen if self.scale == 1 else pg.Surface((W, H))
        self.bg = pg.Surface((W, H)).convert()  # current wallpaper frame
        self.legends = pg.Surface((W, int(KB_H)), pg.SRCALPHA)  # white legends, drawn over bg at KB_Y
        self.bar_surf = pg.Surface((W, BAR_H), pg.SRCALPHA)
        self.kb_rect, self.bar_rect = pg.Rect(0, int(KB_Y), W, int(KB_H)), pg.Rect(0, 0, W, BAR_H)
        self.anim: dict | None = None
        self.store, self.engine = store, engine
        font_names = "notosanscjksc,notosanscjk,wqyzenhei,wqymicrohei,droidsansfallbackfull,droidsansfallback"
        # pygame's sysfont index misses .ttc files on the vendor image, so look for CJK font files directly.
        cjk = [*sorted(str(p) for p in (HERE / "fonts").glob("*.tt[fc]")),
               "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
               os.environ.get("KEYSCREEN_FONT", "")]
        fp = next((p for p in cjk if p and Path(p).is_file()), None) or pg.font.match_font(font_names)
        print(f"[font] {fp or 'pygame default (no CJK)'}", file=sys.stderr)
        self.font = pg.font.Font(fp, int(UNIT_Y * 0.34)) if fp else pg.font.Font(None, int(UNIT_Y * 0.46))
        self.small = pg.font.Font(fp, 28) if fp else pg.font.Font(None, 34)
        self.wall_cache: tuple = ("", None)
        self.fx_cache: dict = {}
        self.gradient = pg.Surface((W, H)).convert()
        for y in range(0, H, 8):
            pg.draw.rect(self.gradient, (12, 18 + y // 40, 40 + y // 30), (0, y, W, 8))
        self.fx_queue: collections.deque = collections.deque()
        self.live: list = []
        self.prev: list = []
        self.bar_text = None
        self.prof = store.profile()
        self.keymap: dict = {}
        self.shot_lock = threading.Lock()
        self.shot_req, self.shot_done = threading.Event(), threading.Event()
        self.shot_raw = b""
        engine.on_press = self.effect
        self.widgets = None
        if os.environ.get("KEYSCREEN_WIDGETS", "1") != "0":
            try:
                from widgets import Widgets
                mk = (lambda n: pg.font.Font(fp, n)) if fp else (lambda n: pg.font.Font(None, n + 6))
                self.widgets = Widgets(pg, store, engine, BAR_H, int(KB_Y), W, mk)
                engine.widgets = self.widgets
            except Exception as e:
                print(f"[widgets] disabled: {e!r}", file=sys.stderr)

    def effect(self, label: str, x: float | None = None, y: float | None = None) -> None:
        self.fx_queue.append((time.perf_counter(), label, x, y))

    def _cover(self, path: Path):
        pg = self.pg
        img = pg.image.load(str(path)).convert()
        iw, ih = img.get_size()
        s = max(W / iw, H / ih)
        nw, nh = math.ceil(iw * s), math.ceil(ih * s)
        img = pg.transform.smoothscale(img, (nw, nh))
        return img.subsurface(((nw - W) // 2, (nh - H) // 2, W, H)).copy()

    def _load_anim(self, name: str) -> dict | None:
        meta = self.store.anim_meta(name)
        if not meta:
            return None
        data = memoryview((ANIM / (name + ".rgb")).read_bytes())
        sz = AW * AH * 3
        frames = [self.pg.image.frombuffer(data[i * sz:(i + 1) * sz], (AW, AH), "RGB").convert() for i in range(meta["frames"])]
        print(f"[anim] {name}: {len(frames)} frames @ {meta['fps']} fps", file=sys.stderr)
        return {"frames": frames, "fps": meta["fps"], "i": 0, "next": 0.0}

    def wallpaper(self, name: str | None):
        """Static: a W x H surface. Animated: {"frames", "fps", ...} once converted, else its first frame if decodable."""
        anim_ready = self.store.is_anim(name) and self.store.ensure_anim(name) == "ready"
        if self.wall_cache[0] == (name, anim_ready):
            return self.wall_cache[1]
        surf = None
        if name and (WALL / name).exists():
            try:
                surf = self._load_anim(name) if anim_ready else (self._cover(WALL / name) if Path(name).suffix.lower() in IMG_EXT else None)
            except Exception as e:  # corrupt upload must not kill the keyboard
                print(f"[render] bad wallpaper {name}: {e}", file=sys.stderr)
        self.wall_cache = ((name, anim_ready), surf)
        return surf

    def fx_image(self, name: str | None):
        if not name:
            return None
        if name not in self.fx_cache:
            try:
                img = self.pg.image.load(str(FXDIR / name)).convert_alpha()
                k = UNIT * 1.6 / max(img.get_size())
                self.fx_cache[name] = self.pg.transform.smoothscale(img, (max(1, int(img.get_width() * k)), max(1, int(img.get_height() * k))))
            except Exception as e:
                print(f"[render] bad effect image {name}: {e}", file=sys.stderr)
                self.fx_cache[name] = None
        return self.fx_cache[name]

    def keycap(self, k: dict, legend_color, shadow_alpha: int) -> object:
        """Legend only, no keycap body; a soft shadow keeps it readable on any wallpaper."""
        pg = self.pg
        rx, ry, rw, rh = k["rect"]
        s = pg.Surface((int(rw), int(rh)), pg.SRCALPHA)
        label = str(self.prof["legends"].get(k["label"], k["label"]))
        pos = lambda t: ((s.get_width() - t.get_width()) // 2, (s.get_height() - t.get_height()) // 2)
        if shadow_alpha:
            sh = self.font.render(label, True, (0, 0, 0))
            sh.set_alpha(shadow_alpha)
            x, y = pos(sh)
            for dx, dy in ((2, 2), (1, 1), (-1, 1)):
                s.blit(sh, (x + dx, y + dy))
        t = self.font.render(label, True, legend_color)
        s.blit(t, pos(t))
        return s

    def rebuild(self) -> None:
        pg, p = self.pg, self.store.profile()
        self.prof = p
        self.accent = hex_color(pg, p["theme"], pg.Color("#38bdf8"))
        self.fx_color = hex_color(pg, p["effect_color"], self.accent)
        wall = self.wallpaper(p["wallpaper"])
        if isinstance(wall, dict):
            self.anim = wall
            pg.transform.scale(wall["frames"][wall["i"]], (W, H), self.bg)
        else:
            self.anim = None
            self.bg.blit(wall or self.gradient, (0, 0))
        self.keymap = {k["label"]: k for k in self.store.keys}
        self.pressed_caps = {}
        shadow = max(0, min(255, int(p["opacity"])))
        self.legends.fill((0, 0, 0, 0))
        for k in self.store.keys:
            self.legends.blit(self.keycap(k, (240, 244, 250), shadow), (k["rect"][0], k["rect"][1] - KB_Y))
            self.pressed_caps[k["label"]] = self.keycap(k, self.accent, shadow)
        self.bar_text = None
        self.draw_bar()

    def draw_bar(self):
        """Re-renders the module bar surface when its text changes; returns its rect if it did."""
        wpm = len([t for t in self.engine.typed if t > time.time() - 60]) / 5
        items = {"clock": time.strftime("%H:%M"), "app": f"profile: {self.store.active}", "wpm": f"{wpm:.0f} WPM"}
        text = "   ".join(items.get(m, m) for m in self.prof["modules"])
        if text == self.bar_text:
            return None
        self.bar_text = text
        self.bar_surf.fill((0, 0, 0, 0))  # no band: text with a soft shadow straight on the wallpaper
        x = 30
        for m in self.prof["modules"]:
            t = self.small.render(items.get(m, m), True, self.accent)
            sh = self.small.render(items.get(m, m), True, (0, 0, 0))
            sh.set_alpha(150)
            self.bar_surf.blit(sh, (x + 2, (BAR_H - t.get_height()) // 2 + 2))
            self.bar_surf.blit(t, (x, (BAR_H - t.get_height()) // 2))
            x += t.get_width() + 60
        return self.bar_rect

    def restore(self, r) -> None:
        """Repaint a region of the canvas from the layers (wallpaper frame, legends, bar)."""
        c = self.canvas
        c.blit(self.bg, r, r)
        k = r.clip(self.kb_rect)
        if k:
            c.blit(self.legends, k.topleft, k.move(0, -self.kb_rect.y))
        b = r.clip(self.bar_rect)
        if b:
            c.blit(self.bar_surf, b.topleft, b)
        wg = self.widgets
        if wg is not None and wg.layer_on and wg.cache is not None:
            x = r.clip(wg.box)
            if x:
                c.blit(wg.cache, x.topleft, x.move(-wg.box.x, -wg.box.y))

    def draw_fx(self, e, now: float):
        pg = self.pg
        t0, kind, rect, x, y, color, dur, seed, img = e
        p = (now - t0) / dur
        if p >= 1:
            return None
        p = max(0.0, p)  # the touch thread can queue an effect after this frame's `now` was taken
        rx, ry, rw, rh = rect
        cx, cy = rx + rw / 2, ry + rh / 2
        a = max(0, min(255, int(255 * (1 - p) ** 1.4)))
        if kind == "glow":
            m = int(3 + UNIT * 0.18 * p)
            s = pg.Surface((int(rw) + 2 * m, int(rh) + 2 * m), pg.SRCALPHA)
            pg.draw.rect(s, (*color[:3], int(a * 0.8)), s.get_rect(), border_radius=RADIUS + m)
            pos = (rx - m, ry - m)
        elif kind == "ripple":
            R = int(UNIT * (0.3 + 1.2 * p))
            s = pg.Surface((2 * R + 2, 2 * R + 2), pg.SRCALPHA)
            pg.draw.circle(s, (*color[:3], a), (R + 1, R + 1), R, max(2, int(9 * (1 - p))))
            pos = (x - R - 1, y - R - 1)
        elif kind == "burst":
            R = int(UNIT * 1.3)
            s = pg.Surface((2 * R, 2 * R), pg.SRCALPHA)
            rnd = random.Random(seed)
            ease = 1 - (1 - p) ** 2
            for _ in range(14):
                ang, sp = rnd.random() * 2 * math.pi, 0.45 + rnd.random() * 0.55
                d = R * 0.92 * sp * ease
                pg.draw.circle(s, (*color[:3], a), (int(R + math.cos(ang) * d), int(R + math.sin(ang) * d)), max(1, int(7 * (1 - p)) + 1))
            pos = (cx - R, cy - R)
        elif kind == "image" and img is not None:
            k = 0.7 + 0.6 * p
            s = pg.transform.smoothscale(img, (max(1, int(img.get_width() * k)), max(1, int(img.get_height() * k))))
            s.set_alpha(a)
            pos = (cx - s.get_width() / 2, cy - s.get_height() / 2)
        else:
            return None
        r = self.canvas.blit(s, (int(pos[0]), int(pos[1])))
        return r.clip(self.canvas.get_rect())

    def frame(self) -> None:
        pg, now = self.pg, time.perf_counter()
        full = False
        if self.store.dirty:
            self.store.dirty = False
            self.rebuild()
            full = True
        a = self.anim
        if a and now >= a["next"]:
            a["i"] = (a["i"] + 1) % len(a["frames"])
            a["next"] = (a["next"] if now - a["next"] < 0.5 else now) + 1 / a["fps"]
            pg.transform.scale(a["frames"][a["i"]], (W, H), self.bg)
            full = True
        bar = self.draw_bar()
        if full:
            self.restore(self.canvas.get_rect())
            dirty = []
        else:
            for r in self.prev:
                self.restore(r)
            dirty = list(self.prev)
            if bar:
                self.restore(bar)
                dirty.append(bar)
        cur = []
        for label in self.engine.pressed_view:
            k = self.keymap.get(label)
            if k:
                r = pg.Rect(k["rect"]).clip(self.canvas.get_rect())
                self.restore(r)
                cur.append(self.canvas.blit(self.pressed_caps[label], r.topleft))
        p = self.prof
        while self.fx_queue:
            t0, label, x, y = self.fx_queue.popleft()
            k = self.keymap.get(label)
            kind = p["key_effects"].get(label, p["effect"])
            if not k or kind not in EFFECTS or kind == "none":
                continue
            rx, ry, rw, rh = k["rect"]
            img = self.fx_image(p["effect_image"]) if kind == "image" else None
            self.live.append((t0, kind, k["rect"], rx + rw / 2 if x is None else x, ry + rh / 2 if y is None else y,
                              self.fx_color, max(80, min(3000, int(p["effect_ms"]))) / 1000, random.random(), img))
        alive = []
        for e in self.live:
            try:
                r = self.draw_fx(e, now)
            except Exception as ex:  # a bad effect must never take the keyboard down
                print(f"[render] effect {e[1]} failed: {ex}", file=sys.stderr)
                r = None
            if r is not None:
                alive.append(e)
                cur.append(r)
        self.live = alive
        if self.widgets is not None:
            try:
                eng = self.engine
                wpm = len([t for t in eng.typed if t > time.time() - 60]) / 5
                box = self.widgets.prepare(self.accent)
                if box is not None:
                    self.restore(box)
                    if not full:
                        dirty.append(box)
                cur += self.widgets.draw(self.canvas, self.accent, eng.n_miss / max(1, eng.n_touch), wpm)
            except Exception as ex:
                print(f"[widgets] draw failed: {ex!r}", file=sys.stderr)
        self.prev = cur
        if self.scale != 1:
            if full or dirty or cur:
                self.screen.blit(pg.transform.smoothscale(self.canvas, self.screen.get_size()), (0, 0))
                pg.display.flip()
        elif full:
            pg.display.flip()
        elif dirty or cur:
            pg.display.update(dirty + cur)

    def grab(self, timeout: float = 1.0) -> bytes:
        """Called from API threads; the renderer copies a half-size frame between two frames."""
        with self.shot_lock:
            self.shot_done.clear()
            self.shot_req.set()
            return self.shot_raw if self.shot_done.wait(timeout) else b""

    def loop(self, stop: threading.Event) -> None:
        pg, clock = self.pg, self.pg.time.Clock()
        while not stop.is_set():
            for e in pg.event.get():
                if e.type == pg.QUIT or (e.type == pg.KEYDOWN and e.key == pg.K_ESCAPE and e.mod & pg.KMOD_CTRL):
                    stop.set()
                elif e.type == pg.MOUSEBUTTONDOWN:
                    self.engine.touch_down(99, e.pos[0] * self.scale, e.pos[1] * self.scale)
                elif e.type == pg.MOUSEBUTTONUP:
                    self.engine.touch_up(99)
            try:
                self.frame()
            except Exception as ex:
                print(f"[render] frame failed, full redraw: {ex!r}", file=sys.stderr)
                self.live, self.prev, self.store.dirty = [], [], True
            if self.shot_req.is_set():
                self.shot_raw = pg.image.tostring(pg.transform.scale(self.canvas, (W // 2, H // 2)), "RGB")
                self.shot_req.clear()
                self.shot_done.set()
            clock.tick(60)


def make_app(store: Store, engine: Engine, renderer: Renderer):
    from aiohttp import web, WSMsgType

    r = web.RouteTableDef()
    ok = lambda **kw: web.json_response({"ok": True, **kw})
    bad = lambda msg, status=400: web.json_response({"ok": False, "error": msg}, status=status)

    async def save_uploads(req, folder: Path, exts: tuple, limit_mb: int) -> list | web.Response:
        reader = await req.multipart()
        saved = []
        async for part in reader:
            if not part.filename:
                continue
            name = Path(part.filename).name.replace(" ", "_")
            if Path(name).suffix.lower() not in exts:
                return bad("only " + "/".join(e[1:] for e in exts))
            data = await part.read(decode=False)
            if len(data) > limit_mb * 1024 * 1024:
                return bad(f"file > {limit_mb}MB", 413)
            (folder / name).write_bytes(data)
            saved.append(name)
        return saved

    @r.get("/")
    async def index(_):
        raise web.HTTPFound("/ui/")

    @r.get("/ui/")
    async def ui(_):
        return web.FileResponse(WEB / "index.html") if WEB else bad("web client not installed", 404)

    @r.get("/ui/config.js")
    async def ui_config(_):
        return web.Response(text="window.BOARD = location.origin;\n", content_type="application/javascript")

    @r.get("/api/state")
    async def state(_):
        lat = sorted(engine.latency_ms)
        return ok(active=store.active, profile=store.profile(), profiles=list(store.profiles), wallpapers=store.wallpapers(), keys=store.keys, size=[W, H],
                  effects=EFFECTS, effect_images=store.effect_images(), unit_px=round(UNIT, 1), keyboard=[round(KB_X), round(KB_Y), round(KB_W), round(KB_H)],
                  anim={n: store.ensure_anim(n) for n in store.wallpapers() if store.is_anim(n)}, video_ext=list(VID_EXT),
                  latency_ms=round(sum(lat) / len(lat), 3) if lat else None, latency_p95_ms=round(lat[int(len(lat) * 0.95) - 1 if len(lat) > 1 else 0], 3) if lat else None)

    @r.get("/api/wallpapers")
    async def walls(_):
        return ok(wallpapers=store.wallpapers())

    @r.post("/api/wallpapers")
    async def upload(req):
        saved = await save_uploads(req, WALL, IMG_EXT + VID_EXT, 80)
        if not isinstance(saved, list):
            return saved
        status = {}
        for n in saved:
            if store.is_anim(n):
                store.drop_anim(n)  # re-upload under the same name -> reconvert
                status[n] = store.ensure_anim(n)
        store.emit({"type": "wallpapers", "saved": saved})
        return ok(saved=saved, anim=status)

    @r.get("/api/wallpapers/{name}")
    async def wall_file(req):
        p = WALL / Path(req.match_info["name"]).name
        return web.FileResponse(p) if p.exists() else bad("not found", 404)

    @r.delete("/api/wallpapers/{name}")
    async def wall_delete(req):
        p = WALL / Path(req.match_info["name"]).name
        if not p.exists():
            return bad("not found", 404)
        p.unlink()
        store.drop_anim(p.name)
        for name, prof in list(store.profiles.items()):
            if prof.get("wallpaper") == p.name:
                store.put_profile(name, {"wallpaper": None})
        store.emit({"type": "wallpapers", "deleted": p.name})
        return ok(deleted=p.name)

    @r.get("/api/effects")
    async def effects(_):
        return ok(effects=EFFECTS, images=store.effect_images())

    @r.post("/api/effects")
    async def effect_upload(req):
        saved = await save_uploads(req, FXDIR, IMG_EXT, 20)
        if not isinstance(saved, list):
            return saved
        for n in saved:
            renderer.fx_cache.pop(n, None)
        store.emit({"type": "effects", "saved": saved})
        return ok(saved=saved)

    @r.get("/api/effects/{name}")
    async def effect_file(req):
        p = FXDIR / Path(req.match_info["name"]).name
        return web.FileResponse(p) if p.exists() else bad("not found", 404)

    @r.delete("/api/effects/{name}")
    async def effect_delete(req):
        p = FXDIR / Path(req.match_info["name"]).name
        if not p.exists():
            return bad("not found", 404)
        p.unlink()
        renderer.fx_cache.pop(p.name, None)
        for name, prof in list(store.profiles.items()):
            if prof.get("effect_image") == p.name:
                store.put_profile(name, {"effect_image": None})
        store.emit({"type": "effects", "deleted": p.name})
        return ok(deleted=p.name)

    @r.post("/api/effects/preview")
    async def effect_preview(req):
        b = await req.json() if req.can_read_body else {}
        label = b.get("key") or "Space"
        if label not in renderer.keymap:
            return bad("unknown key")
        renderer.effect(label)
        return ok(key=label)

    @r.get("/api/profile/{app}")
    async def get_profile(req):
        return ok(profile=store.profile(req.match_info["app"]))

    @r.put("/api/profile/{app}")
    async def put_profile(req):
        body = await req.json()
        if body.get("wallpaper") and body["wallpaper"] not in store.wallpapers():
            return bad(f"unknown wallpaper {body['wallpaper']}")
        if "effect" in body and body["effect"] not in EFFECTS:
            return bad(f"unknown effect {body['effect']}, use one of {EFFECTS}")
        if body.get("effect_image") and body["effect_image"] not in store.effect_images():
            return bad(f"unknown effect image {body['effect_image']}")
        if "key_effects" in body:
            labels = {k["label"] for k in store.keys}
            if not isinstance(body["key_effects"], dict) or any(k not in labels or v not in EFFECTS for k, v in body["key_effects"].items()):
                return bad("key_effects must map key labels to effects")
        if "effect_ms" in body:
            body["effect_ms"] = max(80, min(3000, int(body["effect_ms"])))
        p = store.put_profile(req.match_info["app"], body)
        if body.get("activate"):
            store.activate(req.match_info["app"])
        return ok(profile=p)

    # -- on-screen Agnes chat: the board queues prompts, desktop/panel.py runs them through AGH and posts replies --
    chat = renderer.widgets.chat if renderer.widgets is not None else None

    @r.post("/api/chat/send")
    async def chat_send(req):
        if chat is None:
            return bad("widgets disabled", 503)
        it = chat.send(str((await req.json()).get("prompt", "")))
        return ok(item=it) if it else bad("empty prompt")

    @r.get("/api/chat/pending")
    async def chat_pending(_):
        return ok(item=chat.pending() if chat else None)

    @r.post("/api/chat/reply")
    async def chat_reply(req):
        b = await req.json()
        return ok() if chat and chat.reply(int(b.get("id", 0)), str(b.get("text", "")), bool(b.get("ok", True))) else bad("unknown id")

    @r.get("/api/chat/history")
    async def chat_history(_):
        return ok(items=chat.items if chat else [], focused=bool(chat and chat.focused))

    @r.post("/api/pet/say")
    async def pet_say(req):
        if renderer.widgets is None:
            return bad("widgets disabled", 503)
        b = await req.json()
        renderer.widgets.pet.say(str(b.get("text", ""))[:200], max(1.0, min(60.0, float(b.get("secs", 6)))))
        return ok()

    @r.post("/api/widgets/info")
    async def widgets_info(req):
        if renderer.widgets is None:
            return bad("widgets disabled", 503)
        renderer.widgets.set_info(str((await req.json()).get("text", "")))
        return ok()

    @r.post("/api/chat/open")
    async def chat_open(req):
        if renderer.widgets is None:
            return bad("widgets disabled", 503)
        renderer.widgets.set_open(bool((await req.json()).get("open", True)))
        return ok(open=renderer.widgets.open)

    @r.post("/api/active/{app}")
    async def activate(req):
        store.activate(req.match_info["app"])
        return ok(active=store.active)

    @r.post("/api/keys/adjust")
    async def adjust(req):
        b = await req.json()
        if b.get("key") not in {k["label"] for k in store.keys}:
            return bad("unknown key")
        return ok(offset=store.adjust_key(b["key"], float(b.get("dx", 0)), float(b.get("dy", 0)), b.get("profile")))

    @r.post("/api/touch/inject")
    async def inject(req):
        b = await req.json()
        slot = int(b.get("slot", 7))
        engine.touch_down(slot, float(b["x"]), float(b["y"]))
        await asyncio.sleep(float(b.get("hold_ms", 0)) / 1000)
        return ok(record=engine.touch_up(slot))

    @r.get("/api/touch/stats")
    async def stats(req):
        return ok(**store.stats(float(req.query.get("since", 0))))

    @r.get("/api/touch/points")
    async def points(req):
        with store.lock:
            rows = store.db.execute("select x,y,hit from touch order by t desc limit ?", (int(req.query.get("limit", 2000)),)).fetchall()
        return ok(points=rows)

    @r.get("/api/screenshot")
    async def shot(req):
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, renderer.grab)
        if not raw:
            return bad("renderer busy", 503)
        jpg = req.query.get("fmt") == "jpg"

        def encode() -> bytes:  # PIL releases the GIL while encoding; pygame's PNG writer would stall the touch thread
            from PIL import Image
            buf = io.BytesIO()
            Image.frombytes("RGB", (W // 2, H // 2), raw).save(buf, "JPEG" if jpg else "PNG", quality=80)
            return buf.getvalue()

        return web.Response(body=await loop.run_in_executor(None, encode), content_type="image/jpeg" if jpg else "image/png")

    @r.get("/api/hid/last")
    async def hid_last(_):
        return ok(reports=[b.hex() for b in engine.hid.sent[-10:]])

    @r.get("/ws/events")
    async def events(req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        loop = asyncio.get_running_loop()
        push = lambda ev: loop.call_soon_threadsafe(asyncio.ensure_future, ws.send_json(ev)) if not ws.closed else None
        store.listeners.append(push)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            store.listeners.remove(push)
        return ws

    @web.middleware
    async def cors(req, handler):
        resp = await handler(req) if req.method != "OPTIONS" else web.Response()
        resp.headers.update({"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
        return resp

    app = web.Application(middlewares=[cors], client_max_size=100 * 1024 * 1024)
    app.add_routes(r)
    if WEB:
        app.router.add_static("/ui", WEB)
    return app


def serve_api(app, host: str, port: int) -> None:
    from aiohttp import web

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, host, port).start())
    print(f"[api] http://{host}:{port}  client: http://<board-ip>:{port}/ui/", file=sys.stderr)
    loop.run_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="window + mouse touch, no evdev")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    sys.setswitchinterval(0.0005)  # let the touch thread take the GIL from the renderer within 0.5 ms
    store, stop = Store(), threading.Event()
    engine = Engine(store, Hid())
    renderer = Renderer(store, engine, a.sim, a.headless)
    threading.Thread(target=serve_api, args=(make_app(store, engine, renderer), a.host, a.port), daemon=True).start()
    if not a.sim:
        threading.Thread(target=evdev_loop, args=(engine, stop), daemon=True).start()
    print(f"[layout] 1u = {UNIT_X:.0f}x{UNIT_Y:.0f} px, keyboard {KB_W:.0f}x{KB_H:.0f} px at ({KB_X:.0f},{KB_Y:.0f})", file=sys.stderr)
    try:
        renderer.loop(stop)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
