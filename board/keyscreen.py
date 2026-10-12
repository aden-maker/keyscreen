"""KeyScreen board runtime for LubanCat 1H: touch display acting as a dynamic USB keyboard.

    python3 keyscreen.py                 # board: fullscreen, evdev touch, /dev/hidg0
    python3 keyscreen.py --sim           # desktop: window, mouse = finger, HID logged
    python3 keyscreen.py --sim --headless  # CI / tests: no window

One process: a pygame renderer on the main thread (wallpaper, key legends, module bar),
touch input (evdev ABS_MT or mouse), USB HID reports, a SQLite touch log and an
aiohttp HTTP/WS API on :8765 running on a background asyncio loop.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("KEYSCREEN_HOME", Path(__file__).resolve().parent / "data"))
WALL = ROOT / "wallpapers"
W, H = 1920, 1080
BAR_H = 90

# label, HID usage, width units. Modifiers use usage 0xE0..0xE7 and go to byte 0.
LAYOUT = [
    [("Esc", 0x29, 1), ("1", 0x1E, 1), ("2", 0x1F, 1), ("3", 0x20, 1), ("4", 0x21, 1), ("5", 0x22, 1), ("6", 0x23, 1), ("7", 0x24, 1), ("8", 0x25, 1), ("9", 0x26, 1), ("0", 0x27, 1), ("-", 0x2D, 1), ("=", 0x2E, 1), ("Bksp", 0x2A, 2)],
    [("Tab", 0x2B, 1.5), ("Q", 0x14, 1), ("W", 0x1A, 1), ("E", 0x08, 1), ("R", 0x15, 1), ("T", 0x17, 1), ("Y", 0x1C, 1), ("U", 0x18, 1), ("I", 0x0C, 1), ("O", 0x12, 1), ("P", 0x13, 1), ("[", 0x2F, 1), ("]", 0x30, 1), ("\\", 0x31, 1.5)],
    [("Caps", 0x39, 1.75), ("A", 0x04, 1), ("S", 0x16, 1), ("D", 0x07, 1), ("F", 0x09, 1), ("G", 0x0A, 1), ("H", 0x0B, 1), ("J", 0x0D, 1), ("K", 0x0E, 1), ("L", 0x0F, 1), (";", 0x33, 1), ("'", 0x34, 1), ("Enter", 0x28, 2.25)],
    [("Shift", 0xE1, 2.25), ("Z", 0x1D, 1), ("X", 0x1B, 1), ("C", 0x06, 1), ("V", 0x19, 1), ("B", 0x05, 1), ("N", 0x11, 1), ("M", 0x10, 1), (",", 0x36, 1), (".", 0x37, 1), ("/", 0x38, 1), ("RShift", 0xE5, 2.75)],
    [("Ctrl", 0xE0, 1.5), ("Win", 0xE3, 1.25), ("Alt", 0xE2, 1.25), ("Space", 0x2C, 6.5), ("RAlt", 0xE6, 1.25), ("Fn", 0, 1.25), ("RCtrl", 0xE4, 2)],
]
DEFAULT_PROFILE = {"wallpaper": None, "theme": "#38bdf8", "opacity": 170, "legends": {}, "offsets": {}, "modules": ["clock", "app", "wpm"]}


def build_keys(offsets: dict) -> list[dict]:
    unit = W / 15
    keys, top = [], BAR_H + 20
    row_h = (H - top - 20) / len(LAYOUT)
    for r, row in enumerate(LAYOUT):
        x = 0.0
        for label, code, w in row:
            dx, dy = offsets.get(label, [0, 0])
            keys.append({"label": label, "code": code, "rect": [x + 4 + dx, top + r * row_h + 4 + dy, w * unit - 8, row_h - 8]})
            x += w * unit
    return keys


class Store:
    """Profiles, wallpapers and the touch log. Thread-safe; the API and renderer share it."""

    def __init__(self) -> None:
        WALL.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pfile = ROOT / "profiles.json"
        self.profiles = json.loads(self.pfile.read_text()) if self.pfile.exists() else {"default": dict(DEFAULT_PROFILE)}
        self.active = "default"
        self.db = sqlite3.connect(ROOT / "touch.db", check_same_thread=False)
        self.db.execute("create table if not exists touch(t real, x real, y real, key text, dx real, dy real, duration real, hit integer, profile text)")
        self.dirty = True
        self.listeners: list = []
        self.keys = build_keys({})
        self.relayout()

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
        with self.lock:
            self.db.execute("insert into touch values(?,?,?,?,?,?,?,?,?)", (rec["t"], rec["x"], rec["y"], rec["key"], rec["dx"], rec["dy"], rec["duration"], int(rec["hit"]), self.active))
            self.db.commit()
        self.emit({"type": "touch", **rec})

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
        return sorted(p.name for p in WALL.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"))


class Hid:
    """8-byte boot keyboard reports to /dev/hidg0; falls back to a log in simulation."""

    def __init__(self, path: str = "/dev/hidg0") -> None:
        self.f = None
        try:
            self.f = open(path, "wb", buffering=0)
        except OSError:
            print(f"[hid] {path} unavailable, logging reports", file=sys.stderr)
        self.mods = 0
        self.sent: list[bytes] = []

    def report(self, keys: list[int]) -> None:
        r = bytes([self.mods, 0] + (keys + [0] * 6)[:6])
        self.sent = (self.sent + [r])[-50:]
        if self.f:
            try:
                self.f.write(r)
            except OSError as e:
                print(f"[hid] write failed: {e}", file=sys.stderr)

    def tap(self, code: int) -> None:
        if not code:
            return
        if 0xE0 <= code <= 0xE7:
            self.mods ^= 1 << (code - 0xE0)  # sticky modifier: tap Shift, then a letter
            self.report([])
            return
        self.report([code])
        self.report([])
        if self.mods:
            self.mods = 0
            self.report([])


def hit_test(keys: list[dict], x: float, y: float) -> tuple[dict | None, bool, float, float]:
    best, bd = None, 1e18
    for k in keys:
        rx, ry, rw, rh = k["rect"]
        cx, cy = rx + rw / 2, ry + rh / 2
        if rx <= x <= rx + rw and ry <= y <= ry + rh:
            return k, True, x - cx, y - cy
        d = (x - cx) ** 2 + (y - cy) ** 2
        if d < bd:
            best, bd = k, d
    if best is None or bd > (W / 15) ** 2:
        return None, False, 0, 0
    rx, ry, rw, rh = best["rect"]
    return best, False, x - (rx + rw / 2), y - (ry + rh / 2)


class Engine:
    """Touch down/up to key press; shared by evdev, mouse and the API's /touch/inject."""

    def __init__(self, store: Store, hid: Hid) -> None:
        self.store, self.hid = store, hid
        self.down: dict[int, tuple[float, float, float]] = {}
        self.pressed: str | None = None
        self.typed: list[float] = []
        self.latency_ms: list[float] = []

    def touch_down(self, slot: int, x: float, y: float) -> None:
        self.down[slot] = (time.time(), x, y)

    def touch_up(self, slot: int) -> dict | None:
        if slot not in self.down:
            return None
        t0, x, y = self.down.pop(slot)
        if y < BAR_H:
            self.store.emit({"type": "bar", "x": x})
            return None
        start = time.perf_counter()
        key, hit, dx, dy = hit_test(self.store.keys, x, y)
        if key and hit:
            self.hid.tap(key["code"])
            self.pressed = key["label"]
            self.typed = [t for t in self.typed if t > time.time() - 60] + [time.time()]
            self.store.dirty = True
        self.latency_ms = (self.latency_ms + [(time.perf_counter() - start) * 1000])[-200:]
        rec = {"t": t0, "x": round(x, 1), "y": round(y, 1), "key": key["label"] if key else None, "dx": round(dx, 1), "dy": round(dy, 1), "duration": round(time.time() - t0, 3), "hit": hit}
        self.store.log_touch(rec)
        return rec


def evdev_loop(engine: Engine, stop: threading.Event) -> None:
    try:
        import evdev  # apt install python3-evdev on the board
    except ImportError:
        print("[touch] python-evdev missing; touch disabled", file=sys.stderr)
        return
    dev = next((evdev.InputDevice(p) for p in evdev.list_devices() if evdev.ecodes.ABS_MT_POSITION_X in dict(evdev.InputDevice(p).capabilities().get(evdev.ecodes.EV_ABS, []))), None)
    if dev is None:
        print("[touch] no multitouch device found", file=sys.stderr)
        return
    ax = dev.absinfo(evdev.ecodes.ABS_MT_POSITION_X)
    ay = dev.absinfo(evdev.ecodes.ABS_MT_POSITION_Y)
    print(f"[touch] {dev.name} {ax.max}x{ay.max}", file=sys.stderr)
    slot, pos, tid = 0, {}, {}
    for ev in dev.read_loop():
        if stop.is_set():
            return
        if ev.type != evdev.ecodes.EV_ABS:
            continue
        c = ev.code
        if c == evdev.ecodes.ABS_MT_SLOT:
            slot = ev.value
        elif c == evdev.ecodes.ABS_MT_POSITION_X:
            pos.setdefault(slot, [0, 0])[0] = (ev.value - ax.min) * W / (ax.max - ax.min)
        elif c == evdev.ecodes.ABS_MT_POSITION_Y:
            pos.setdefault(slot, [0, 0])[1] = (ev.value - ay.min) * H / (ay.max - ay.min)
        elif c == evdev.ecodes.ABS_MT_TRACKING_ID:
            if ev.value == -1:
                engine.touch_up(slot)
                tid.pop(slot, None)
            else:
                tid[slot] = "pending"
        if tid.get(slot) == "pending" and slot in pos:
            engine.touch_down(slot, *pos[slot])
            tid[slot] = "down"


class Renderer:
    def __init__(self, store: Store, engine: Engine, sim: bool, headless: bool) -> None:
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
        import pygame

        self.pg = pygame
        pygame.init()
        flags = 0 if sim else pygame.FULLSCREEN | pygame.NOFRAME
        size = (W // 2, H // 2) if sim and not headless else (W, H)
        self.screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption("KeyScreen sim — mouse = finger")
        pygame.mouse.set_visible(sim)
        self.canvas = pygame.Surface((W, H))
        self.scale = W / size[0]
        self.store, self.engine = store, engine
        self.font = pygame.font.Font(None, 44)
        self.small = pygame.font.Font(None, 34)
        self.wall_cache: tuple[str | None, object] = ("", None)
        self.app = "default"
        self.frame_lock = threading.Lock()
        self.png: bytes = b""

    def wallpaper(self, name: str | None):
        if self.wall_cache[0] == name:
            return self.wall_cache[1]
        surf = None
        if name and (WALL / name).exists():
            try:
                surf = self.pg.transform.smoothscale(self.pg.image.load(str(WALL / name)).convert(), (W, H))
            except Exception as e:  # corrupt upload must not kill the keyboard
                print(f"[render] bad wallpaper {name}: {e}", file=sys.stderr)
        self.wall_cache = (name, surf)
        return surf

    def draw(self) -> None:
        pg, c, p = self.pg, self.canvas, self.store.profile()
        wall = self.wallpaper(p["wallpaper"])
        if wall:
            c.blit(wall, (0, 0))
        else:
            for y in range(0, H, 8):
                pg.draw.rect(c, (12, 18 + y // 40, 40 + y // 30), (0, y, W, 8))
        accent = pg.Color(p["theme"]) if isinstance(p["theme"], str) and p["theme"].startswith("#") else pg.Color("#38bdf8")
        key_layer = pg.Surface((W, H), pg.SRCALPHA)
        for k in self.store.keys:
            rx, ry, rw, rh = k["rect"]
            on = k["label"] == self.engine.pressed
            pg.draw.rect(key_layer, (*accent[:3], 200) if on else (10, 14, 24, p["opacity"]), (rx, ry, rw, rh), border_radius=14)
            pg.draw.rect(key_layer, (*accent[:3], 255), (rx, ry, rw, rh), 2, border_radius=14)
            label = p["legends"].get(k["label"], k["label"])
            t = self.font.render(str(label), True, (240, 244, 250))
            key_layer.blit(t, (rx + 14, ry + 10))
        c.blit(key_layer, (0, 0))
        bar = pg.Surface((W, BAR_H), pg.SRCALPHA)
        bar.fill((0, 0, 0, 170))
        wpm = len(self.engine.typed) / 5
        items = {"clock": time.strftime("%H:%M"), "app": f"profile: {self.store.active}", "wpm": f"{wpm:.0f} WPM"}
        x = 30
        for m in p["modules"]:
            t = self.small.render(items.get(m, m), True, accent)
            bar.blit(t, (x, 28))
            x += t.get_width() + 60
        c.blit(bar, (0, 0))
        if self.scale != 1:
            self.screen.blit(pg.transform.smoothscale(c, self.screen.get_size()), (0, 0))
        else:
            self.screen.blit(c, (0, 0))
        pg.display.flip()
        buf = io.BytesIO()
        pg.image.save(pg.transform.smoothscale(c, (W // 2, H // 2)), buf, "frame.png")
        with self.frame_lock:
            self.png = buf.getvalue()

    def loop(self, stop: threading.Event) -> None:
        pg, clock, last = self.pg, self.pg.time.Clock(), 0.0
        while not stop.is_set():
            for e in pg.event.get():
                if e.type == pg.QUIT or (e.type == pg.KEYDOWN and e.key == pg.K_ESCAPE and e.mod & pg.KMOD_CTRL):
                    stop.set()
                elif e.type == pg.MOUSEBUTTONDOWN:
                    self.engine.touch_down(99, e.pos[0] * self.scale, e.pos[1] * self.scale)
                elif e.type == pg.MOUSEBUTTONUP:
                    self.engine.touch_up(99)
            now = time.time()
            if self.store.dirty or now - last > 1:
                self.store.dirty, last = False, now
                self.draw()
            clock.tick(60)


def make_app(store: Store, engine: Engine, renderer: Renderer):
    from aiohttp import web, WSMsgType

    r = web.RouteTableDef()
    ok = lambda **kw: web.json_response({"ok": True, **kw})

    @r.get("/api/state")
    async def state(_):
        return ok(active=store.active, profile=store.profile(), profiles=list(store.profiles), wallpapers=store.wallpapers(), keys=store.keys, size=[W, H],
                  latency_ms=round(sum(engine.latency_ms) / len(engine.latency_ms), 3) if engine.latency_ms else None)

    @r.get("/api/wallpapers")
    async def walls(_):
        return ok(wallpapers=store.wallpapers())

    @r.post("/api/wallpapers")
    async def upload(req):
        reader = await req.multipart()
        saved = []
        async for part in reader:
            if not part.filename:
                continue
            name = Path(part.filename).name.replace(" ", "_")
            if Path(name).suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
                return web.json_response({"ok": False, "error": "only png/jpg/bmp"}, status=400)
            data = await part.read(decode=False)
            if len(data) > 20 * 1024 * 1024:
                return web.json_response({"ok": False, "error": "file > 20MB"}, status=413)
            (WALL / name).write_bytes(data)
            saved.append(name)
        store.emit({"type": "wallpapers", "saved": saved})
        return ok(saved=saved)

    @r.get("/api/wallpapers/{name}")
    async def wall_file(req):
        p = WALL / Path(req.match_info["name"]).name
        return web.FileResponse(p) if p.exists() else web.json_response({"ok": False, "error": "not found"}, status=404)

    @r.get("/api/profile/{app}")
    async def get_profile(req):
        return ok(profile=store.profile(req.match_info["app"]))

    @r.put("/api/profile/{app}")
    async def put_profile(req):
        body = await req.json()
        if body.get("wallpaper") and body["wallpaper"] not in store.wallpapers():
            return web.json_response({"ok": False, "error": f"unknown wallpaper {body['wallpaper']}"}, status=400)
        p = store.put_profile(req.match_info["app"], body)
        if body.get("activate"):
            store.activate(req.match_info["app"])
        return ok(profile=p)

    @r.post("/api/active/{app}")
    async def activate(req):
        store.activate(req.match_info["app"])
        return ok(active=store.active)

    @r.post("/api/keys/adjust")
    async def adjust(req):
        b = await req.json()
        if b.get("key") not in {k["label"] for k in store.keys}:
            return web.json_response({"ok": False, "error": "unknown key"}, status=400)
        return ok(offset=store.adjust_key(b["key"], float(b.get("dx", 0)), float(b.get("dy", 0)), b.get("profile")))

    @r.post("/api/touch/inject")
    async def inject(req):
        b = await req.json()
        engine.touch_down(int(b.get("slot", 7)), float(b["x"]), float(b["y"]))
        return ok(record=engine.touch_up(int(b.get("slot", 7))))

    @r.get("/api/touch/stats")
    async def stats(req):
        return ok(**store.stats(float(req.query.get("since", 0))))

    @r.get("/api/touch/points")
    async def points(req):
        with store.lock:
            rows = store.db.execute("select x,y,hit from touch order by t desc limit ?", (int(req.query.get("limit", 2000)),)).fetchall()
        return ok(points=rows)

    @r.get("/api/screenshot")
    async def shot(_):
        with renderer.frame_lock:
            data = renderer.png
        return web.Response(body=data, content_type="image/png")

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
        resp.headers.update({"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
        return resp

    app = web.Application(middlewares=[cors], client_max_size=25 * 1024 * 1024)
    app.add_routes(r)
    return app


def serve_api(app, host: str, port: int) -> None:
    from aiohttp import web

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, host, port).start())
    print(f"[api] http://{host}:{port}", file=sys.stderr)
    loop.run_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="window + mouse touch, no evdev")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    store, stop = Store(), threading.Event()
    engine = Engine(store, Hid())
    renderer = Renderer(store, engine, a.sim, a.headless)
    threading.Thread(target=serve_api, args=(make_app(store, engine, renderer), a.host, a.port), daemon=True).start()
    if not a.sim:
        threading.Thread(target=evdev_loop, args=(engine, stop), daemon=True).start()
    try:
        renderer.loop(stop)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
