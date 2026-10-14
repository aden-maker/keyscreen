"""Agnes desk pet: flat chibi drawn from primitives every frame on a tiny rig (lean, bob, squash, limb angles),
so motions read well while the art stays simple. Physics: gravity, throw, wall bounce, landing squash.

Modes: idle walk run air drag land dizzy sit sleep think wave dance spin cheer."""

from __future__ import annotations

import math
import random
import time

from pygame import gfxdraw

HAIR, HAIR2, SKIN, DRESS, DRESS2 = (190, 156, 255), (160, 124, 238), (255, 232, 220), (255, 138, 190), (255, 205, 228)
SOCK, SHOE, EYE, EYE2, MOUTH, CHEEK, RIB = (255, 255, 255), (232, 98, 150), (52, 58, 120), (96, 140, 235), (200, 80, 110), (255, 186, 200), (255, 120, 170)
WHALE, WHALE2, BELLY, SPRAY = (77, 107, 254), (58, 84, 222), (214, 226, 255), (150, 210, 255)
KEY = (30, 40, 96)  # transparent key; AA edges blend into it, giving a soft dark outline
SW, SH, CX, FY = 320, 300, 160, 292  # local surface, feet at (CX, FY)
HIP, SHO, HEAD, HR = 62, 108, 162, 54
TAP_LINES = ["诶嘿~", "戳我干嘛啦 (>_<)", "Agnes 在这里哦~", "今天也要加油！", "要好好打字哦～", "嗯？有事找我吗？", "按住我可以拖着走哦"]
GRAB_LINES = ["哇！放我下来～", "飞起来啦！", "要去哪里呀？", "呜哇——"]


def circ(s, c, p, r):
    x, y, r = int(p[0]), int(p[1]), max(1, int(r))
    gfxdraw.filled_circle(s, x, y, r, c)
    gfxdraw.aacircle(s, x, y, r, c)


def poly(s, c, pts):
    pts = [(int(a), int(b)) for a, b in pts]
    gfxdraw.filled_polygon(s, pts, c)
    gfxdraw.aapolygon(s, pts, c)


def cap(s, c, p1, p2, w):
    r = w / 2
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    L = math.hypot(dx, dy) or 1
    nx, ny = -dy / L * r, dx / L * r
    poly(s, c, [(p1[0] + nx, p1[1] + ny), (p2[0] + nx, p2[1] + ny), (p2[0] - nx, p2[1] - ny), (p1[0] - nx, p1[1] - ny)])
    circ(s, c, p1, r)
    circ(s, c, p2, r)


def ell(s, c, cx, cy, rx, ry):
    cx, cy, rx, ry = int(cx), int(cy), max(1, int(rx)), max(1, int(ry))
    gfxdraw.filled_ellipse(s, cx, cy, rx, ry, c)
    gfxdraw.aaellipse(s, cx, cy, rx, ry, c)


def limb_end(p, ang, L):
    a = math.radians(ang)
    return (p[0] + math.sin(a) * L, p[1] + math.cos(a) * L)


class Pet:
    def __init__(self, pg, x0: int, x1: int, floor: int) -> None:
        self.pg, self.x0, self.x1, self.floor, self.top = pg, x0, x1, floor, 330
        self.x, self.y, self.vx, self.vy = (x0 + x1) / 2, float(floor), 0.0, 0.0
        self.tx, self.dir, self.speed = self.x, 1, 170
        self.mode, self.until, self.t, self.mt = "idle", time.time() + 2, 0.0, 0.0
        self.last_key, self.last_tap, self.blink_at = time.time(), 0.0, time.time() + 2
        self.tail, self.swing, self.swing_v = 0.0, 0.0, 0.0
        self.drag = None  # {slot, dx, dy, t0, x0, y0, hist}
        self.hearts, self.dust = [], []
        self.say_text, self.say_until = "", 0.0
        self.surf = pg.Surface((SW, SH))  # opaque + colorkey: gfxdraw AA on SRCALPHA leaves seams where shapes overlap
        self.surf.set_colorkey(KEY)
        self._img, self._rt, self._bub = self.surf, 0.0, (None, None)
        self.zfont = None

    # ---------- control ----------
    def set_mode(self, m: str, secs: float = 0) -> None:
        self.mode, self.mt = m, 0.0
        if secs:
            self.until = time.time() + secs

    def say(self, text: str, secs: float) -> None:
        self.say_text, self.say_until = text, time.time() + secs

    def on_ground(self) -> bool:
        return self.y >= self.floor - 0.5 and self.vy >= 0 and self.drag is None

    def hit(self, x: float, y: float) -> bool:
        return abs(x - self.x) < 85 and self.y - 250 < y < self.y + 5

    def goto(self, x: float) -> None:
        self.tx = max(self.x0, min(self.x1, x))
        if self.on_ground():
            far = abs(self.tx - self.x) > 420
            self.speed = 430 if far else 170
            self.set_mode("run" if far else "walk")
            self.dir = 1 if self.tx > self.x else -1
        self.last_key = time.time()

    def hop(self, v: float = 620) -> None:
        if self.on_ground():
            self.vy = -v
            self.set_mode("air")

    def act(self, name: str) -> bool:
        self.last_key = time.time()
        if name == "jump":
            self.hop()
        elif name == "run":
            self.goto(self.x0 if self.x - self.x0 > self.x1 - self.x else self.x1)
            self.speed, self.mode = 430, "run"
        elif name in ("wave", "dance", "sit", "spin", "cheer"):
            self.set_mode(name, {"wave": 2, "dance": 4, "sit": 6, "spin": 0.8, "cheer": 0.8}[name])
            if name == "cheer":
                self.hop(380)
                self.mode = "cheer"
        else:
            return False
        return True

    def tap(self) -> None:
        now = time.time()
        if now - self.last_tap < 0.4:
            self.set_mode("spin", 0.8)
            self.say("转圈圈~", 2)
        else:
            self.hop()
            self.say(random.choice(TAP_LINES), 2.5)
        self.last_tap = self.last_key = now
        for _ in range(6):
            self.hearts.append([self.x + random.uniform(-50, 50), self.y - 230, random.uniform(-50, 50), random.uniform(120, 210), 0.0])

    def poke(self) -> None:
        self.last_key = time.time()
        if self.mode in ("idle", "sit", "sleep"):
            self.hop(300)
            self.mode = "cheer"

    # drag: grabbed anywhere on the body, follows the finger, thrown on release
    def grab(self, slot, x, y) -> None:
        self.drag = {"slot": slot, "dx": self.x - x, "dy": self.y - y, "t0": time.time(), "p0": (x, y), "hist": [(time.time(), x, y)]}
        self.vx = self.vy = 0.0
        self.set_mode("drag")
        self.last_key = time.time()

    def drag_to(self, x, y) -> None:
        d = self.drag
        if not d:
            return
        now = time.time()
        d["hist"] = [h for h in d["hist"] if now - h[0] < 0.12] + [(now, x, y)]
        nx = max(60, min(1860, x + d["dx"]))
        ny = max(self.top, min(self.floor, y + d["dy"]))
        if len(d["hist"]) > 1 and abs(nx - self.x) > 1:
            self.dir = 1 if nx > self.x else -1
        self.x, self.y = nx, ny
        if math.hypot(x - d["p0"][0], y - d["p0"][1]) > 18 and not d.get("said"):
            d["said"] = True
            self.say(random.choice(GRAB_LINES), 2)

    def release(self) -> None:
        d, self.drag = self.drag, None
        if not d:
            return
        h = d["hist"]
        moved = math.hypot(h[-1][1] - d["p0"][0], h[-1][2] - d["p0"][1])
        if time.time() - d["t0"] < 0.3 and moved < 18:
            self.set_mode("idle", 1)
            self.tap()
            return
        dt = max(0.016, h[-1][0] - h[0][0])
        self.vx = max(-1600, min(1600, (h[-1][1] - h[0][1]) / dt))
        self.vy = max(-1400, min(1400, (h[-1][2] - h[0][2]) / dt))
        self.set_mode("air")

    # ---------- simulation ----------
    def update(self, dt: float, thinking: bool) -> None:
        now = time.time()
        self.t += dt
        self.mt += dt
        if self.drag:
            h = self.drag["hist"]
            vx = (h[-1][1] - h[0][1]) / max(0.016, h[-1][0] - h[0][0]) if len(h) > 1 else 0
            target = max(-55, min(55, -vx * 0.05))
            self.swing_v += ((target - self.swing) * 45 - self.swing_v * 3.5) * dt
            self.swing += self.swing_v * dt
        else:
            self.swing *= 0.9
            if not self.on_ground() or self.vy < 0:  # airborne
                self.vy += 2100 * dt
                self.x += self.vx * dt
                self.y += self.vy * dt
                if self.x < 60 or self.x > 1860:
                    self.x, self.vx = max(60, min(1860, self.x)), -self.vx * 0.6
                    self.dir = 1 if self.vx > 0 else -1
                if self.y >= self.floor:
                    hard = self.vy > 1150
                    self.y, self.vy, self.vx = float(self.floor), 0.0, 0.0
                    if hard:
                        self.set_mode("dizzy", 1.4)
                        self.say("头好晕…@_@", 1.5)
                    else:
                        self.set_mode("land", 0.16)
                    self.x = max(self.x0, min(self.x1, self.x)) if self.x0 <= self.x <= self.x1 else self.x
                if self.mode not in ("air", "cheer", "spin"):
                    self.mode = "air"
        m = self.mode
        if self.on_ground():
            if m in ("air",):
                self.set_mode("land", 0.16)
            elif m in ("land", "dizzy", "wave", "dance", "sit", "spin", "cheer") and now > self.until:
                self.set_mode("idle", random.uniform(1.5, 4))
            elif thinking and m in ("idle", "sleep", "sit"):
                self.set_mode("think")
            elif not thinking and m == "think":
                self.set_mode("wave", 1.5)
            elif m in ("idle",) and now - self.last_key > 120:
                self.set_mode("sleep")
            elif m == "sleep" and now - self.last_key < 2:
                self.set_mode("wave", 1.2)
            elif m == "idle" and now > self.until:
                r = random.random()
                if r < 0.55:
                    self.goto(random.uniform(self.x0, self.x1))
                elif r < 0.7:
                    self.goto(self.x0 if self.x > (self.x0 + self.x1) / 2 else self.x1)  # zoomies
                elif r < 0.8:
                    self.set_mode("wave", 1.6)
                elif r < 0.9:
                    self.set_mode("sit", random.uniform(3, 6))
                else:
                    self.set_mode("dance", 3)
            if self.mode in ("walk", "run"):
                if self.x < self.x0 - 1 or self.x > self.x1 + 1:
                    self.tx = max(self.x0, min(self.x1, self.x))
                self.dir = 1 if self.tx > self.x else -1
                step = self.speed * dt
                if abs(self.tx - self.x) <= step:
                    self.x = self.tx
                    self.set_mode("idle", random.uniform(2, 5))
                else:
                    self.x += step * self.dir
                    if self.mode == "run" and random.random() < dt * 14:
                        self.dust.append([self.x - self.dir * 30, self.floor - 6, 0.0])
            elif self.x < self.x0 - 1 or self.x > self.x1 + 1:
                self.goto(self.x)
        if self.mode == "spin":
            self.dir = 1 if int(self.mt / 0.09) % 2 else -1
        tail_target = (-25 if self.mode == "run" else -10 if self.mode == "walk" else 0) + self.swing * 0.6 - max(-30, min(30, self.vy * 0.02)) * 0
        self.tail += (tail_target - self.tail) * min(1, dt * 6)
        for h in self.hearts:
            h[0] += h[2] * dt
            h[1] -= h[3] * dt
            h[4] += dt
        self.hearts = [h for h in self.hearts if h[4] < 1.2]
        for d in self.dust:
            d[2] += dt
        self.dust = [d for d in self.dust if d[2] < 0.45]

    # ---------- pose ----------
    def pose(self) -> dict:
        """Angles in degrees: 0 = down, 90 = forward. knee bends the shin backward, elb bends the forearm forward."""
        t, m, mt = self.t, self.mode, self.mt
        p = dict(lean=0.0, bob=0.0, sy=1.0, legL=3.0, legR=-3.0, kneeL=4.0, kneeR=4.0, armL=10.0, armR=-8.0, elbL=15.0, elbR=15.0,
                 face="open", sit=0.0, nod=0.0, hem=0.0, look=0.0, tilt=0.0)
        if m == "idle":
            s = math.sin(t * 2.2)
            p.update(sy=1 + 0.012 * s, armL=10 + 3 * s, armR=-8 - 3 * s, look=math.sin(t * 0.7) * 0.6, tilt=math.sin(t * 0.9) * 3)
        elif m in ("walk", "run"):
            run = m == "run"
            ph = t * (14 if run else 8.5)
            s, c = math.sin(ph), math.cos(ph)
            a = 42 if run else 24
            kb, kr = (12, 85) if run else (4, 38)
            sw, off = (55, 20) if run else (20, 0)
            p.update(legL=a * s, legR=-a * s, kneeL=kb + kr * max(0, c), kneeR=kb + kr * max(0, -c),
                     armL=-sw * s + off, armR=sw * s + off, elbL=85 if run else 25, elbR=85 if run else 25,
                     bob=abs(c) * (9 if run else 4), lean=16 if run else 5, hem=abs(s) * (5 if run else 2), face="happy" if run else "open")
        elif m in ("air", "cheer"):
            if self.vy < 0 or m == "cheer":
                p.update(armL=165, armR=150, elbL=10, elbR=10, legL=35, kneeL=85, legR=-5, kneeR=35, face="happy", hem=4)
            else:
                w = math.sin(t * 24)
                p.update(armL=130 + 25 * w, armR=130 - 25 * w, elbL=20, elbR=20, legL=15 * w, legR=-15 * w, kneeL=20, kneeR=20,
                         face="surprise", hem=8)
            if self.drag is None and self.vy < 0 and mt < 0.08:
                p.update(sy=0.86)
        elif m == "drag":
            sw, k = self.swing, math.sin(t * 8)
            p.update(armL=170, armR=158, elbL=5, elbR=5, legL=sw + 12 * k, legR=sw - 12 * k, kneeL=22 + 15 * math.sin(t * 8 + 1),
                     kneeR=22 + 15 * math.sin(t * 8 + 2), lean=sw * 0.35, face="surprise" if abs(self.swing_v) > 60 else "happy", hem=6)
        elif m == "land":
            k = 1 - min(1, mt / 0.16)
            p.update(sy=1 - 0.2 * k, armL=45, armR=45, elbL=30, elbR=30, legL=14, legR=-10, kneeL=50 * k, kneeR=50 * k)
        elif m == "dizzy":
            p.update(lean=7 * math.sin(t * 7), tilt=10 * math.sin(t * 5), face="dizzy", armL=25, armR=-20, elbL=20, elbR=20, kneeL=10, kneeR=10)
        elif m in ("sit", "sleep"):
            sleep = m == "sleep"
            p.update(sit=1, legL=85, legR=80, kneeL=85, kneeR=80, armL=20, armR=30, elbL=40, elbR=50, bob=math.sin(t * 1.6) * 1.5,
                     face="sleep" if sleep else "open", nod=(math.sin(t * 1.2) * 4 + 4) if sleep else 0, tilt=6 if sleep else 0)
        elif m == "think":
            p.update(armR=40, elbR=120, armL=15, lean=3 * math.sin(t * 1.5), tilt=6 + 3 * math.sin(t * 1.5), face="focus", look=-0.6)
        elif m == "wave":
            w = math.sin(t * 12)
            p.update(armR=150 + 25 * w, elbR=25 + 15 * math.sin(t * 12 + 1), armL=8, face="happy", bob=math.sin(t * 3) * 2, tilt=6)
        elif m == "dance":
            b = math.sin(t * 8)
            p.update(lean=10 * b, tilt=8 * b, armL=140 if b > 0 else 40, armR=40 if b > 0 else 140, elbL=40, elbR=40, legL=18 * b, legR=-18 * b,
                     kneeL=20 + 30 * max(0, b), kneeR=20 + 30 * max(0, -b), bob=abs(math.cos(t * 8)) * 9, face="happy", hem=abs(b) * 4)
        elif m == "spin":
            p.update(armL=90, armR=90, elbL=0, elbR=0, face="happy", hem=6)
        if self.mode != "sleep" and self.blink_at - 0.12 < time.time() < self.blink_at and p["face"] in ("open", "focus"):
            p["face"] = "blink"
        if time.time() > self.blink_at:
            self.blink_at = time.time() + random.uniform(2, 5)
        return p

    # ---------- drawing ----------
    def _render(self) -> None:
        """Chubby blue whale: body squash/bob from the rig, fins follow the arms, tail flaps with the legs."""
        s, p = self.surf, self.pose()
        s.fill(KEY)
        t, f, sy = self.t, p["face"], p["sy"]
        bx = CX + 8 + p["lean"] * 0.6
        by = FY - 64 - p["bob"] + 22 * p["sit"] + p["nod"]
        rx, ry = 84 * (2 - sy) ** 0.5, 62 * sy
        tilt = math.radians(p["tilt"] * 0.8)
        rot = lambda dx, dy: (bx + dx * math.cos(tilt) - dy * math.sin(tilt), by + dx * math.sin(tilt) + dy * math.cos(tilt))
        flap = (p["legL"] - p["legR"]) * 0.25 + math.sin(t * 3) * 6
        # tail: tapered stalk curling up behind, two round flukes
        stalk = [rot(-rx * 0.7, -8), rot(-rx - 18, -26 - flap * 0.4), rot(-rx - 30, -44 - flap * 0.8), rot(-rx - 24, -40 - flap * 0.8),
                 rot(-rx - 6, -14), rot(-rx * 0.7, 22)]
        poly(s, WHALE2, stalk)
        tx, ty = rot(-rx - 30, -46 - flap * 0.8)
        for d in (-1, 1):
            a = math.radians(-90 + d * 55 + flap)
            ell(s, WHALE2, tx + math.cos(a) * 16, ty + math.sin(a) * 16, 17, 10)
        # far fin, body, belly
        def fin(ang, col, side):
            a = math.radians(ang * 0.5 - 20)
            x0, y0 = rot(side * 18, ry * 0.45)
            pts = [(x0 + math.cos(a + math.pi / 2 + k * math.pi / 6) * (30 if k in (2, 3, 4) else 12) * (1 if k in (2, 3, 4) else 0.5),
                    y0 + math.sin(a + math.pi / 2 + k * math.pi / 6) * (30 if k in (2, 3, 4) else 12) * (1 if k in (2, 3, 4) else 0.5)) for k in range(7)]
            poly(s, col, [(x0 - 9, y0)] + pts + [(x0 + 9, y0)])
        fin(p["armL"], WHALE2, -1)
        ell(s, WHALE, bx, by, rx, ry)
        ell(s, BELLY, bx + rx * 0.18, by + ry * 0.42, rx * 0.72, ry * 0.5)
        ell(s, WHALE, bx + rx * 0.1, by + ry * 0.14, rx * 0.82, ry * 0.42)
        ell(s, (150, 178, 255), bx - rx * 0.25, by - ry * 0.62, rx * 0.36, ry * 0.12)  # sheen
        # face on the front half
        lx = p["look"] * 4
        ex, ey = bx + rx * 0.42 + lx, by - ry * 0.12
        if f in ("blink", "sleep"):
            cap(s, EYE, (ex - 10, ey), (ex, ey + 5), 4)
            cap(s, EYE, (ex, ey + 5), (ex + 10, ey), 4)
        elif f == "happy":
            cap(s, EYE, (ex - 10, ey + 4), (ex, ey - 5), 4)
            cap(s, EYE, (ex, ey - 5), (ex + 10, ey + 4), 4)
        elif f == "dizzy":
            cap(s, EYE, (ex - 8, ey - 7), (ex + 8, ey + 7), 4)
            cap(s, EYE, (ex - 8, ey + 7), (ex + 8, ey - 7), 4)
        else:
            r = 9 if f == "focus" else 15 if f == "surprise" else 13
            ell(s, EYE, ex, ey, 11, r)
            circ(s, (255, 255, 255), (ex - 3, ey - r * 0.45), 4)
            circ(s, (255, 255, 255), (ex + 4, ey + r * 0.35), 2)
        ell(s, CHEEK, ex + 6, ey + 20, 10, 5)
        mx, my = bx + rx * 0.72 + lx, by + ry * 0.1
        if f in ("surprise", "dizzy"):
            ell(s, MOUTH, mx, my + 3, 5, 6)
        elif f == "happy":
            poly(s, MOUTH, [(mx - 10, my), (mx + 6, my - 2), (mx + 2, my + 7), (mx - 6, my + 7)])
        else:
            cap(s, MOUTH, (mx - 10, my + 1), (mx - 3, my + 5), 3)
            cap(s, MOUTH, (mx - 3, my + 5), (mx + 4, my + 1), 3)
        fin(p["armR"], WHALE2, 1)
        # spout when happy / jumping
        if f in ("happy", "surprise") or self.mode in ("cheer", "air", "dance"):
            sx, sy0 = rot(rx * 0.15, -ry - 4)
            h = 26 + 8 * math.sin(t * 9)
            cap(s, SPRAY, (sx, sy0), (sx, sy0 - h), 5)
            for k in (-1, 0, 1):
                circ(s, SPRAY, (sx + k * 14, sy0 - h - (6 if k else 12) + 3 * math.sin(t * 9 + k)), 6 if k else 7)
        if self.mode == "sleep":
            zx, zy = rot(rx * 0.3, -ry - 20 - (t * 12) % 30)
            cap(s, EYE, (zx, zy), (zx + 10, zy), 2)
            cap(s, EYE, (zx + 10, zy), (zx, zy + 10), 2)
            cap(s, EYE, (zx, zy + 10), (zx + 10, zy + 10), 2)

    def draw(self, canvas) -> list:
        pg = self.pg
        now = time.monotonic()
        calm = self.mode in ("idle", "sleep", "sit", "think")
        if now - self._rt >= (0.066 if calm else 0.033):
            self._rt = now
            self._render()
            self._img = self.surf if self.dir > 0 else pg.transform.flip(self.surf, True, False)
        img = self._img
        rects = []
        lift = max(0, self.floor - self.y)
        sh = pg.Surface((110, 20), pg.SRCALPHA)
        pg.draw.ellipse(sh, (0, 0, 0, max(15, 70 - int(lift / 4))), sh.get_rect())
        rects.append(canvas.blit(sh, (int(self.x - 55), self.floor - 12)))
        rects.append(canvas.blit(img, (int(self.x - CX), int(self.y - FY))))
        for x, y, age in self.dust:
            a, r = max(0, 200 - int(age * 440)), 6 + age * 26
            d = pg.Surface((int(r * 2 + 2),) * 2, pg.SRCALPHA)
            pg.draw.circle(d, (255, 255, 255, a), (int(r + 1),) * 2, int(r))
            rects.append(canvas.blit(d, (int(x - r), int(y - r - age * 20))))
        for hx, hy, _, _, age in self.hearts:
            a = max(0, 255 - int(age * 210))
            h = pg.Surface((26, 24), pg.SRCALPHA)
            c = (255, 120, 180, a)
            pg.draw.circle(h, c, (7, 8), 7)
            pg.draw.circle(h, c, (19, 8), 7)
            pg.draw.polygon(h, c, [(0, 10), (26, 10), (13, 24)])
            rects.append(canvas.blit(h, (int(hx), int(hy))))
        head_y = self.y - (HEAD - 40 * (self.mode in ("sit", "sleep"))) - 60
        if self.mode == "dizzy":
            for i in range(3):
                a = self.t * 6 + i * 2.1
                st = pg.Surface((16, 16), pg.SRCALPHA)
                poly(st, (255, 220, 90), [(8, 0), (10, 6), (16, 8), (10, 10), (8, 16), (6, 10), (0, 8), (6, 6)])
                rects.append(canvas.blit(st, (int(self.x + math.cos(a) * 50 - 8), int(head_y + math.sin(a) * 12))))
        if self.mode == "sleep" and self.zfont:
            for i in range(3):
                z = self.zfont.render("z", True, (235, 235, 255))
                rects.append(canvas.blit(z, (int(self.x + 50 + i * 16), int(head_y - i * 20 - (self.t * 18 % 20)))))
        return rects

    def bubble(self, canvas, font, text: str, thinking: bool) -> list:
        from widgets import wrap
        pg = self.pg
        if thinking:
            text = "·" * (1 + int(self.t * 3) % 3) + " 思考中"
        lines = wrap(font, text, 560)[:3]
        if not lines or not text:
            return []
        if self._bub[0] != text:
            lh = font.get_height() + 4
            w = max(font.size(l)[0] for l in lines) + 40
            box = pg.Surface((w, len(lines) * lh + 26), pg.SRCALPHA)
            pg.draw.rect(box, (255, 255, 255, 255), box.get_rect(), border_radius=22)
            for i, l in enumerate(lines):
                box.blit(font.render(l, True, (80, 50, 90)), (20, 13 + i * lh))
            self._bub = (text, box)
        box = self._bub[1]
        w, h = box.get_size()
        x = int(min(max(16, self.x - w / 2), 1900 - w))
        y = max(96, int(self.y - 268 - h))
        tip = x + max(24, min(w - 24, int(self.x - x)))
        r = canvas.blit(box, (x, y))
        return [r, pg.draw.polygon(canvas, (255, 255, 255), [(tip - 12, y + h - 1), (tip + 12, y + h - 1), (tip, y + h + 15)])]
