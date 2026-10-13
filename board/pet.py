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
        self.surf = pg.Surface((SW, SH), pg.SRCALPHA)
        self._img, self._rt = self.surf, 0.0
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
        t, m, mt = self.t, self.mode, self.mt
        p = dict(lean=0.0, bob=0.0, sy=1.0, legL=3.0, legR=-3.0, armL=8.0, armR=-6.0, face="open", sit=0.0, nod=0.0, hem=0.0, look=0.0)
        if m == "idle":
            s = math.sin(t * 2.2)
            p.update(bob=s * 2, armL=8 + 4 * s, armR=-6 - 4 * s, look=math.sin(t * 0.7) * 0.6)
        elif m in ("walk", "run"):
            run = m == "run"
            ph = t * (15 if run else 9)
            s = math.sin(ph)
            a = 50 if run else 26
            p.update(legL=a * s, legR=-a * s, armL=-(60 if run else 22) * s + (30 if run else 0), armR=(60 if run else 22) * s + (30 if run else 0),
                     bob=abs(s) * (11 if run else 5), lean=14 if run else 4, hem=abs(s) * (5 if run else 2), face="happy" if run else "open")
        elif m in ("air", "cheer"):
            if self.vy < 0 or m == "cheer":
                p.update(armL=165, armR=155, legL=-25, legR=12, face="happy", hem=4)
            else:
                w = math.sin(t * 24)
                p.update(armL=145 + 25 * w, armR=145 - 25 * w, legL=18 * w, legR=-18 * w, face="surprise", hem=8)
            if self.drag is None and self.vy < 0 and mt < 0.08:
                p.update(sy=0.86)
        elif m == "drag":
            sw = self.swing
            p.update(armL=172, armR=160, legL=sw + 14 * math.sin(t * 8), legR=sw - 14 * math.sin(t * 8), lean=sw * 0.35,
                     face="surprise" if abs(self.swing_v) > 60 else "happy", hem=6)
        elif m == "land":
            k = 1 - min(1, mt / 0.16)
            p.update(sy=1 - 0.18 * k, armL=40, armR=40, legL=8, legR=-8)
        elif m == "dizzy":
            p.update(lean=7 * math.sin(t * 7), face="dizzy", armL=25, armR=-20)
        elif m in ("sit", "sleep"):
            sleep = m == "sleep"
            p.update(sit=1, legL=82, legR=76, armL=25, armR=35, bob=math.sin(t * 1.6) * 1.5, face="sleep" if sleep else "open",
                     nod=(math.sin(t * 1.2) * 4 + 4) if sleep else 0)
        elif m == "think":
            p.update(armR=150, armL=10, lean=3 * math.sin(t * 1.5), face="focus", look=-0.6)
        elif m == "wave":
            p.update(armR=145 + 28 * math.sin(t * 14), armL=6, face="happy", bob=math.sin(t * 3) * 2)
        elif m == "dance":
            b = math.sin(t * 8)
            p.update(lean=10 * b, armL=125 if b > 0 else 30, armR=30 if b > 0 else 125, legL=16 * b, legR=-16 * b,
                     bob=abs(math.cos(t * 8)) * 9, face="happy", hem=abs(b) * 4)
        elif m == "spin":
            p.update(armL=90, armR=90, face="happy", hem=6)
        if self.mode != "sleep" and self.blink_at - 0.12 < time.time() < self.blink_at and p["face"] in ("open", "focus"):
            p["face"] = "blink"
        if time.time() > self.blink_at:
            self.blink_at = time.time() + random.uniform(2, 5)
        return p

    # ---------- drawing ----------
    def _render(self) -> None:
        s, p = self.surf, self.pose()
        s.fill((0, 0, 0, 0))
        lean, sy, bob, sit = math.radians(p["lean"]), p["sy"], p["bob"], p["sit"]
        drop = 40 * sit

        def pt(dx, h):
            h2 = h - drop if h > 20 else h
            shift = (h2 - (HIP - drop)) * math.tan(lean) if h2 > HIP - drop else 0
            return (CX + dx + shift, FY - h2 * sy - bob)

        hipL, hipR = pt(-9, HIP), pt(9, HIP)
        shoL, shoR = pt(-19, SHO - 6), pt(19, SHO - 6)
        hx, hy = pt(0, HEAD)
        hy += p["nod"]
        darker = lambda c: tuple(max(0, int(v * 0.86)) for v in c)
        # far limbs
        e = limb_end(hipL, p["legL"], 44)
        cap(s, darker(SOCK), hipL, e, 13)
        circ(s, darker(SHOE), (e[0] + 3, e[1] + 2), 8)
        e = limb_end(shoL, p["armL"], 38)
        cap(s, darker(SKIN), shoL, e, 11)
        circ(s, darker(SKIN), e, 7)
        # twin tails (chains of circles, swaying)
        for side in (-1, 1):
            base = (hx + side * 46, hy - 18)
            for i in range(7):
                d = i * 14
                ang = math.radians(side * 18 + self.tail + math.sin(self.t * 3 + side) * 6 + i * side * 2)
                circ(s, HAIR2 if side < 0 else HAIR, (base[0] + math.sin(ang) * d + side * i * 2, base[1] + math.cos(ang) * d), 19 - i * 1.5)
        # dress
        hem = 40 + p["hem"]
        poly(s, DRESS, [pt(-17, SHO), pt(17, SHO), (hipR[0] + hem - 9, hipR[1] + 10), (hipL[0] - hem + 9, hipL[1] + 10)])
        poly(s, DRESS2, [(hipL[0] - hem + 9, hipL[1] + 4), (hipR[0] + hem - 9, hipR[1] + 4), (hipR[0] + hem - 9, hipR[1] + 10), (hipL[0] - hem + 9, hipL[1] + 10)])
        poly(s, SOCK, [pt(-9, SHO + 1), pt(9, SHO + 1), pt(0, SHO - 12)])
        circ(s, EYE2, pt(0, SHO - 8), 4)
        # near limbs
        e = limb_end(hipR, p["legR"], 44)
        cap(s, SOCK, hipR, e, 13)
        circ(s, SHOE, (e[0] + 3, e[1] + 2), 8)
        # head
        circ(s, HAIR2, (hx, hy - 4), HR + 6)
        circ(s, SKIN, (hx, hy), HR)
        ell(s, HAIR, hx, hy - 30, HR + 2, 32)
        for bx in (-30, -8, 14, 34):
            circ(s, HAIR, (hx + bx, hy - 12), 15)
        ah = math.sin(self.t * 4) * 6
        cap(s, HAIR, (hx - 2, hy - 54), (hx + 10 + ah, hy - 76), 6)
        cap(s, HAIR, (hx + 10 + ah, hy - 76), (hx + 24 + ah, hy - 70), 5)
        for dx in (-1, 1):  # ribbon
            poly(s, RIB, [(hx - 44, hy - 40), (hx - 44 + dx * 22, hy - 54), (hx - 44 + dx * 20, hy - 28)])
        circ(s, (255, 170, 205), (hx - 44, hy - 40), 6)
        # face (drawn facing right; flipped later)
        f, lx = p["face"], 6 + p["look"] * 4
        for i, ex in enumerate((-19, 21)):
            cx, cy = hx + ex + lx, hy + 10
            if f in ("blink", "sleep"):
                cap(s, EYE, (cx - 9, cy + 4), (cx + 9, cy + 4), 4)
            elif f == "happy":
                for k in range(-9, 9, 3):
                    circ(s, EYE, (cx + k, cy + 6 - math.sqrt(max(0, 81 - k * k)) * 0.7), 2)
            elif f == "dizzy":
                cap(s, EYE, (cx - 8, cy - 6), (cx + 8, cy + 8), 4)
                cap(s, EYE, (cx - 8, cy + 8), (cx + 8, cy - 6), 4)
            else:
                up = -4 if f == "focus" else 0
                ell(s, EYE, cx, cy, 10, 14 if f != "surprise" else 11)
                ell(s, EYE2, cx, cy + 4 + up, 7, 8)
                circ(s, (255, 255, 255), (cx - 3, cy - 5 + up), 4)
        ell(s, CHEEK, hx - 30 + lx, hy + 26, 9, 5)
        ell(s, CHEEK, hx + 34 + lx, hy + 26, 9, 5)
        mx, my = hx + 2 + lx, hy + 30
        if f in ("surprise", "dizzy"):
            ell(s, MOUTH, mx, my + 2, 5, 6)
        elif f == "happy":
            poly(s, MOUTH, [(mx - 7, my - 2), (mx + 7, my - 2), (mx, my + 6)])
        else:
            cap(s, MOUTH, (mx - 5, my), (mx + 5, my), 3)
        # near arm last so waves read in front of the body
        e = limb_end(shoR, p["armR"], 38)
        cap(s, SKIN, shoR, e, 11)
        circ(s, SKIN, e, 7)

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
        lh = font.get_height() + 4
        w = max(font.size(l)[0] for l in lines) + 40
        h = len(lines) * lh + 26
        x = int(min(max(16, self.x - w / 2), 1900 - w))
        y = max(96, int(self.y - 268 - h))
        box = pg.Surface((w, h + 16), pg.SRCALPHA)
        pg.draw.rect(box, (255, 255, 255, 235), (0, 0, w, h), border_radius=22)
        tip = max(24, min(w - 24, int(self.x - x)))
        pg.draw.polygon(box, (255, 255, 255, 235), [(tip - 12, h - 1), (tip + 12, h - 1), (tip, h + 15)])
        for i, l in enumerate(lines):
            box.blit(font.render(l, True, (80, 50, 90)), (20, 13 + i * lh))
        return [canvas.blit(box, (x, y))]
