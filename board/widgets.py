"""Top-half widgets: a chibi "Agnes" desk pet that wanders the free area, an on-screen chat box so the
keyboard itself can talk to Agnes, and a typing-mood line. Pure pygame drawing, no assets.

Chat flow: taps/keys on the board -> Chat.queue -> GET /api/chat/pending (desktop/panel.py polls, runs AGH)
-> POST /api/chat/reply -> bubble + history. The board never needs the PC's address."""

from __future__ import annotations

import math
import random
import threading
import time

PRESETS = [  # (chip label, prompt)
    ("二次元模式", "用 keyscreen-01 的 list_wallpapers 看键盘上有哪些壁纸，选一张最有二次元/活泼感觉的，用 set_wallpaper 应用到 default profile，主题色选粉色或天蓝色系。一句话说明理由。"),
    ("写代码配色", "我要写代码了。用 keyscreen-01 的 list_wallpapers 选一张最适合长时间写代码的壁纸，set_wallpaper 应用到 default profile，配协调的主题色和不透明度。一句话说明理由。"),
    ("校准按键", "调用 keyscreen-01 的 get_touch_stats（since_minutes=0），在 count≥10 的键中（Fn 除外）选出偏移最明显的 2 个，用 adjust_key 按平均偏移的一半（限 ±15 px）微调，一句话汇报。"),
    ("分析打字", "用 keyscreen-01 的 get_touch_stats（since_minutes=0）用两句话总结我的打字：误触率、最容易按偏的键、一条建议。不要修改设置。"),
]
SHIFT = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*", "9": "(", "0": ")", "-": "_", "=": "+",
         "[": "{", "]": "}", "\\": "|", ";": ":", "'": '"', ",": "<", ".": ">", "/": "?"}


def wrap(font, text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for ch in text.replace("\r", ""):
        if ch == "\n" or font.size(cur + ch)[0] > width:
            lines.append(cur)
            cur = "" if ch == "\n" else ch
        else:
            cur += ch
    return lines + [cur] if cur or not lines else lines


class Chat:
    """Queue + on-screen box. Thread-safe enough: the API threads only append/replace small dicts."""

    def __init__(self, store) -> None:
        self.store = store
        self.lock = threading.Lock()
        self.items: list[dict] = []  # {id, prompt, status: queued|running|done|error, reply, t}
        self.text, self.focused, self.shift, self.caps = "", False, False, False
        self.dirty, self.next_id = True, 1

    # -- queue (API side) --
    def send(self, prompt: str) -> dict:
        prompt = prompt.strip()
        if not prompt:
            return {}
        with self.lock:
            it = {"id": self.next_id, "prompt": prompt[:1000], "status": "queued", "reply": "", "t": time.time()}
            self.next_id += 1
            self.items = (self.items + [it])[-12:]
        self.dirty = True
        self.store.emit({"type": "chat", "status": "queued", "id": it["id"]})
        return it

    def pending(self) -> dict | None:
        with self.lock:
            for it in self.items:
                if it["status"] == "queued":
                    it["status"] = "running"
                    self.dirty = True
                    return dict(it)
        return None

    def reply(self, id_: int, text: str, ok: bool = True) -> bool:
        with self.lock:
            for it in self.items:
                if it["id"] == id_:
                    it.update(status="done" if ok else "error", reply=(text or "").strip()[:600], t=time.time())
                    self.dirty = True
                    self.store.emit({"type": "chat", "status": it["status"], "id": id_})
                    return True
        return False

    @property
    def busy(self) -> bool:
        return any(it["status"] in ("queued", "running") for it in self.items)

    def last_reply(self) -> dict | None:
        done = [it for it in self.items if it["status"] in ("done", "error") and it["reply"]]
        return done[-1] if done else None

    # -- keyboard capture (Engine side) --
    def key(self, label: str) -> None:
        if label == "Enter":
            self.send(self.text)
            self.text = ""
        elif label == "Bksp":
            self.text = self.text[:-1]
        elif label == "Esc":
            self.focused, self.text = False, ""
        elif label == "Space":
            self.text += " "
        elif label in ("Shift", "RShift"):
            self.shift = not self.shift
        elif label == "Caps":
            self.caps = not self.caps
        elif len(label) == 1 and len(self.text) < 200:
            ch = label
            if ch.isalpha():
                ch = ch.upper() if (self.shift ^ self.caps) else ch.lower()
            elif self.shift:
                ch = SHIFT.get(ch, ch)
            self.text += ch
            self.shift = False
        self.dirty = True


class Pet:
    """Procedural chibi: wanders along the floor of the top area, blinks, hops when you type, thinks while Agnes works."""

    def __init__(self, x0: int, x1: int, floor: int) -> None:
        self.x0, self.x1, self.floor = x0, x1, floor
        self.x, self.tx, self.dir = (x0 + x1) / 2, (x0 + x1) / 2, 1
        self.state, self.until, self.t = "idle", time.time() + 2, 0.0
        self.hop, self.blink_at, self.last_key = 0.0, time.time() + 2, time.time()
        self.look = 0.0  # -1..1 eye offset

    def poke(self, key_x: float | None = None) -> None:
        self.last_key = time.time()
        self.hop = max(self.hop, 1.0)
        if key_x is not None:
            self.look = max(-1.0, min(1.0, (key_x - self.x) / 900))

    def update(self, dt: float, thinking: bool) -> None:
        now = time.time()
        self.t += dt
        if thinking:
            self.state = "think"
        elif now - self.last_key > 120:
            self.state = "sleep"
        elif self.state in ("think", "sleep"):
            self.state, self.until = "idle", now + 1
        if self.state == "idle" and now > self.until:
            self.state, self.tx = "walk", random.uniform(self.x0, self.x1)
            self.dir = 1 if self.tx > self.x else -1
        if self.state == "walk":
            step = 140 * dt
            if abs(self.tx - self.x) <= step:
                self.x, self.state, self.until = self.tx, "idle", now + random.uniform(1.5, 5)
            else:
                self.x += step * self.dir
        self.hop = max(0.0, self.hop - dt * 2.2)
        self.look *= 0.98 if self.state != "think" else 1

    def draw(self, pg, canvas, font) -> list:
        """Draws onto the canvas; returns the rects it touched."""
        now, t = time.time(), self.t
        bob = abs(math.sin(t * 9)) * 6 if self.state == "walk" else math.sin(t * 2) * 2
        hop = math.sin(min(1, self.hop) * math.pi) * 40 if self.hop > 0 else 0
        s = pg.Surface((260, 300), pg.SRCALPHA)
        cx, fy = 130, 282 - bob - hop  # feet
        hair, hair2, skin, dress, eye = (199, 166, 255), (255, 154, 200), (255, 228, 216), (255, 143, 200), (95, 184, 255)
        pg.draw.ellipse(s, (0, 0, 0, 60), (cx - 48, 268, 96, 22))  # shadow (does not hop)
        sway = math.sin(t * 3) * 6
        for sd in (-1, 1):  # twin tails
            pg.draw.ellipse(s, hair, (cx + sd * 62 - 22 + sway * sd, fy - 170, 44, 120))
        pg.draw.rect(s, dress, (cx - 36, fy - 68, 72, 64), border_radius=18)  # dress
        pg.draw.rect(s, (255, 255, 255), (cx - 36, fy - 18, 72, 14), border_radius=6)  # hem
        for sd in (-1, 1):  # legs
            pg.draw.rect(s, skin, (cx + sd * 14 - 8, fy - 12, 16, 12), border_radius=4)
        hy = fy - 120
        pg.draw.ellipse(s, hair, (cx - 66, hy - 70, 132, 128))  # back hair
        pg.draw.circle(s, skin, (cx, hy), 56)  # head
        pg.draw.ellipse(s, hair, (cx - 60, hy - 66, 120, 70))  # bangs
        for i in (-34, -8, 18):
            pg.draw.ellipse(s, hair, (cx + i, hy - 40, 26, 50))
        ah = math.sin(t * 4) * 8  # ahoge
        pg.draw.lines(s, hair2, False, [(cx - 4, hy - 64), (cx + 10 + ah, hy - 92), (cx + 30 + ah, hy - 86)], 5)
        pg.draw.polygon(s, hair2, [(cx - 44, hy - 30), (cx - 70, hy - 44), (cx - 62, hy - 18)])  # ribbon
        pg.draw.polygon(s, hair2, [(cx - 44, hy - 30), (cx - 24, hy - 50), (cx - 30, hy - 22)])
        blink = self.state == "sleep" or (self.blink_at - 0.12 < now < self.blink_at)
        if now > self.blink_at:
            self.blink_at = now + random.uniform(2, 5)
        lx = self.look * 5
        for sd in (-1, 1):
            ex = cx + sd * 22 + lx
            if blink:
                pg.draw.arc(s, (90, 60, 90), (ex - 12, hy - 2, 24, 16), math.pi, 2 * math.pi, 3)
            else:
                pg.draw.ellipse(s, (255, 255, 255), (ex - 13, hy - 14, 26, 32))
                pg.draw.ellipse(s, eye, (ex - 10, hy - 8, 20, 26))
                pg.draw.ellipse(s, (30, 40, 80), (ex - 6, hy - 2, 12, 16))
                pg.draw.circle(s, (255, 255, 255), (int(ex - 4), int(hy - 4)), 4)
        pg.draw.ellipse(s, (255, 150, 170, 110), (cx - 46, hy + 10, 22, 12))
        pg.draw.ellipse(s, (255, 150, 170, 110), (cx + 24, hy + 10, 22, 12))
        if self.hop > 0.3 or self.state == "think":
            pg.draw.ellipse(s, (200, 80, 110), (cx - 7 + lx, hy + 22, 14, 10))  # open mouth
        else:
            pg.draw.arc(s, (160, 70, 100), (cx - 8 + lx, hy + 18, 16, 10), math.pi, 2 * math.pi, 2)
        if self.state == "sleep":
            for i in range(3):
                z = font.render("z", True, (220, 220, 255))
                s.blit(z, (cx + 60 + i * 14, hy - 80 - i * 18 - (t * 20 % 18)))
        if self.dir < 0:
            s = pg.transform.flip(s, True, False)
        pos = (int(self.x - 130), int(self.floor - 300))
        return [canvas.blit(s, pos)]

    def bubble(self, pg, canvas, font, text: str, thinking: bool, accent) -> list:
        lines = ["· · ·"] if thinking else wrap(font, text, 540)[:4]
        if not lines:
            return []
        w = max(font.size(l)[0] for l in lines) + 36
        h = len(lines) * (font.get_height() + 4) + 24
        x = int(min(max(20, self.x - w / 2), self.x1 + 160 - w))
        y = int(self.floor - 300 - h + 10)
        box = pg.Surface((w + 4, h + 18), pg.SRCALPHA)
        pg.draw.rect(box, (255, 255, 255, 235), (0, 0, w, h), border_radius=18)
        pg.draw.rect(box, accent, (0, 0, w, h), 3, border_radius=18)
        tip = int(self.x - x)
        pg.draw.polygon(box, (255, 255, 255, 235), [(tip - 12, h - 2), (tip + 12, h - 2), (tip, h + 16)])
        for i, l in enumerate(lines):
            box.blit(font.render(l, True, (60, 40, 70)), (18, 12 + i * (font.get_height() + 4)))
        return [canvas.blit(box, (x, y))]


class Widgets:
    """Owns layout of the top area and routes taps/keys; Renderer calls draw() every frame."""

    def __init__(self, pg, store, engine, bar_h: int, kb_y: int, w: int, mkfont) -> None:
        self.pg, self.store, self.engine = pg, store, engine
        self.chat = Chat(store)
        self.font, self.tiny = mkfont(26), mkfont(22)
        self.box = pg.Rect(w - 920, bar_h + 14, 890, kb_y - bar_h - 30)
        self.pet = Pet(140, self.box.left - 220, kb_y - 6)
        self.chips: list = []
        self.send_rect = None
        self.cache = None
        self.last, self.caret_on, self.caret_t = time.time(), True, 0.0
        self.shown_reply = None

    # -- input --
    def tap(self, x: float, y: float) -> None:
        if self.box.collidepoint(x, y):
            for rect, prompt in self.chips:
                if rect.collidepoint(x, y):
                    self.chat.send(prompt)
                    return
            if self.send_rect and self.send_rect.collidepoint(x, y):
                self.chat.send(self.chat.text)
                self.chat.text = ""
            self.chat.focused = True
        else:
            self.chat.focused = False
            if abs(x - self.pet.x) < 120:
                self.pet.poke()
        self.chat.dirty = True

    def key(self, label: str, x: float) -> bool:
        """Returns True when the key was consumed by the chat box (no HID)."""
        self.pet.poke(x)
        if not self.chat.focused:
            return False
        self.chat.key(label)
        return True

    # -- drawing --
    def _render_box(self, accent) -> None:
        pg, c, f, tf = self.pg, self.chat, self.font, self.tiny
        s = pg.Surface(self.box.size, pg.SRCALPHA)
        pg.draw.rect(s, (24, 16, 44, 175), s.get_rect(), border_radius=22)
        pg.draw.rect(s, accent if c.focused else (255, 255, 255, 60), s.get_rect(), 3, border_radius=22)
        s.blit(f.render("Agnes 助手", True, accent), (24, 14))
        st = "思考中…" if c.busy else ("输入中 · Enter 发送 · Esc 退出" if c.focused else "点此用键盘直接对 Agnes 说话")
        t = tf.render(st, True, (200, 190, 220))
        s.blit(t, (self.box.w - t.get_width() - 24, 20))
        # history: last exchanges, newest at the bottom
        y_in = self.box.h - 64
        y_chip = y_in - 50
        lines: list = []
        for it in c.items[-4:]:
            lines += [("you", l) for l in wrap(tf, "你：" + it["prompt"], self.box.w - 60)[:2]]
            if it["status"] in ("done", "error"):
                lines += [("ag", l) for l in wrap(tf, "Agnes：" + (it["reply"] or "(无回复)"), self.box.w - 60)[:4]]
            else:
                lines += [("ag", "Agnes：" + ("…正在读取设备、思考" if it["status"] == "running" else "排队中"))]
        lh = tf.get_height() + 4
        max_lines = max(1, (y_chip - 56) // lh)
        y = 56
        for who, l in lines[-max_lines:]:
            s.blit(tf.render(l, True, (255, 255, 255) if who == "you" else (255, 200, 230)), (24, y))
            y += lh
        self.chips = []
        x = 24
        for label, prompt in PRESETS:
            t = tf.render(label, True, (40, 20, 50))
            r = pg.Rect(x, y_chip, t.get_width() + 28, 38)
            pg.draw.rect(s, accent, r, border_radius=19)
            s.blit(t, (r.x + 14, r.y + (38 - t.get_height()) // 2))
            self.chips.append((r.move(self.box.topleft), prompt))
            x += r.w + 10
        inp = pg.Rect(24, y_in, self.box.w - 48 - 120, 48)
        pg.draw.rect(s, (255, 255, 255, 235 if c.focused else 170), inp, border_radius=14)
        txt = c.text if c.text or c.focused else "在这里打字…（支持英文和预设中文指令）"
        t = f.render(txt + ("|" if c.focused and self.caret_on else ""), True, (40, 30, 60) if c.text or c.focused else (150, 140, 170))
        s.set_clip(inp.inflate(-20, 0))
        s.blit(t, (max(inp.x + 12, inp.right - 12 - t.get_width()), inp.y + (48 - t.get_height()) // 2))
        s.set_clip(None)
        sr = pg.Rect(inp.right + 12, y_in, 108, 48)
        pg.draw.rect(s, accent, sr, border_radius=14)
        t = f.render("发送", True, (40, 20, 50))
        s.blit(t, (sr.centerx - t.get_width() // 2, sr.centery - t.get_height() // 2))
        self.send_rect = sr.move(self.box.topleft)
        self.cache = s
        c.dirty = False

    def draw(self, canvas, accent, miss_rate: float, wpm: float) -> tuple:
        """Returns (moving rects drawn this frame, chat-box rect if its cached surface changed).
        The box itself is a layer: Renderer.restore() blits self.cache, so it is not redrawn every frame."""
        now = time.time()
        dt, self.last = min(0.1, now - self.last), now
        self.caret_t += dt
        if self.caret_t > 0.5:
            self.caret_t, self.caret_on = 0.0, not self.caret_on
            if self.chat.focused:
                self.chat.dirty = True
        thinking = self.chat.busy
        self.pet.update(dt, thinking)
        box_dirty = None
        if self.chat.dirty or self.cache is None:
            self._render_box(accent)
            box_dirty = self.box
        rects = self.pet.draw(self.pg, canvas, self.tiny)
        last = self.chat.last_reply()
        if thinking:
            rects += self.pet.bubble(self.pg, canvas, self.tiny, "", True, accent)
        elif last and now - last["t"] < 25:
            rects += self.pet.bubble(self.pg, canvas, self.tiny, last["reply"], False, accent)
        mood = "zzz…" if self.pet.state == "sleep" else ("Agnes 思考中" if thinking else (f"{wpm:.0f} WPM · 误触 {miss_rate * 100:.0f}%" if wpm else "打几个字试试～"))
        t = self.tiny.render(mood, True, (255, 255, 255))
        bg = self.pg.Surface((t.get_width() + 20, t.get_height() + 8), self.pg.SRCALPHA)
        bg.fill((0, 0, 0, 110))
        bg.blit(t, (10, 4))
        mx = int(self.pet.x + 100 if self.pet.dir > 0 else self.pet.x - 100 - bg.get_width())
        rects.append(canvas.blit(bg, (mx, self.pet.floor - 150)))
        return rects, box_dirty
