"""Top-half widgets: the Agnes desk pet (sprite in assets/agnes.png), a slide-in Agnes chat box behind a toggle,
and an info line (weather / next event / foreground app, pushed by desktop/panel.py). Borderless by design.

Chat flow: board queues prompts -> desktop/panel.py polls /api/chat/pending, runs AGH -> /api/chat/reply.
Keys go to the chat box only while it is open; closed, every key goes to the PC."""

from __future__ import annotations

import math
import random
import threading
import time
from pathlib import Path

from ime import Pinyin
from pet import Pet

ASSETS = Path(__file__).resolve().parent / "assets"
PRESETS = [  # (chip label, prompt)
    ("二次元模式", "用 keyscreen-01 的 list_wallpapers 看键盘上有哪些壁纸，选一张最有二次元/活泼感觉的，用 set_wallpaper 应用到 default profile，主题色选粉色或天蓝色系。一句话说明理由。"),
    ("写代码配色", "我要写代码了。用 keyscreen-01 的 list_wallpapers 选一张最适合长时间写代码的壁纸，set_wallpaper 应用到 default profile，配协调的主题色和不透明度。一句话说明理由。"),
    ("校准按键", "调用 keyscreen-01 的 get_touch_stats（since_minutes=0），在 count≥10 的键中（Fn 除外）选出偏移最明显的 2 个，用 adjust_key 按平均偏移的一半（限 ±15 px）微调，一句话汇报。"),
    ("分析打字", "用 keyscreen-01 的 get_touch_stats（since_minutes=0）用两句话总结我的打字：误触率、最容易按偏的键、一条建议。不要修改设置。"),
]
TAP_LINES = ["诶嘿~", "戳我干嘛啦 (>_<)", "Agnes 在这里哦~", "今天也要加油！", "要好好打字哦～", "嗯？有事找我吗？", "点右下角就能和我说话啦"]
SHIFT = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*", "9": "(", "0": ")", "-": "_", "=": "+",
         "[": "{", "]": "}", "\\": "|", ";": ":", "'": '"', ",": "<", ".": ">", "/": "?"}
ZH_PUNCT = {",": "，", ".": "。", "/": "？", ";": "；", "'": "！", "\\": "、", "[": "「", "]": "」"}
PAGE = 5
ease = lambda t: 1 - (1 - t) ** 3


def wrap(font, text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for ch in text.replace("\r", ""):
        if ch == "\n" or font.size(cur + ch)[0] > width:
            lines.append(cur)
            cur = "" if ch == "\n" else ch
        else:
            cur += ch
    return lines + [cur] if cur or not lines else lines


def shadow_text(pg, font, text: str, color):
    t = font.render(text, True, color)
    sh = font.render(text, True, (0, 0, 0))
    s = pg.Surface((t.get_width() + 3, t.get_height() + 3), pg.SRCALPHA)
    sh.set_alpha(150)
    s.blit(sh, (2, 2))
    s.blit(t, (0, 0))
    return s


class Chat:
    def __init__(self, store) -> None:
        self.store = store
        self.lock = threading.Lock()
        self.items: list[dict] = []  # {id, prompt, status: queued|running|done|error, reply, t}
        self.text, self.focused, self.shift, self.caps = "", False, False, False
        self.dirty, self.next_id, self.typed_at = True, 1, 0.0
        self.ime, self.zh, self.py, self.page = None, True, "", 0  # Chinese pinyin input by default
        self._cands = ("", [])

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

    @property
    def cands(self) -> list:
        if self._cands[0] != self.py:
            self._cands = (self.py, self.ime.cands(self.py) if (self.ime and self.py) else [])
        return self._cands[1]

    def pick(self, i: int) -> None:
        c = self.cands
        if 0 <= i < len(c):
            w, n = c[i]
            self.text, self.py, self.page = (self.text + w)[:200], self.py[n:], 0
        self.dirty = True

    def key(self, label: str) -> None:
        self.typed_at = time.time()
        self.dirty = True
        if label in ("Shift", "RShift"):
            self.text, self.py, self.zh = self.text + self.py, "", not self.zh
            return
        if self.zh and self.py:
            if label == "Space":
                return self.pick(0)
            if label in "123456789" and len(label) == 1:
                return self.pick(self.page * PAGE + int(label) - 1)
            if label == "-":
                self.page = max(0, self.page - 1)
                return
            if label == "=":
                self.page += (self.page + 1) * PAGE < len(self.cands)
                return
            if label == "Bksp":
                self.py, self.page = self.py[:-1], 0
                return
            if label == "Enter":
                self.text, self.py = self.text + self.py, ""
                return
            if len(label) == 1 and label.isalpha():
                self.py = (self.py + label.lower())[:30]
                self.page = 0
                return
            if len(label) != 1:
                return
            self.pick(0)
        if self.zh and not self.caps and len(label) == 1 and label.isalpha():
            self.py = label.lower()
            return
        if self.zh and label in ZH_PUNCT:
            self.text = (self.text + ZH_PUNCT[label])[:200]
            return
        if label == "Enter":
            self.send(self.text)
            self.text = ""
        elif label == "Bksp":
            self.text = self.text[:-1]
        elif label == "Space":
            self.text += " "
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


class Widgets:
    def __init__(self, pg, store, engine, bar_h: int, kb_y: int, w: int, mkfont) -> None:
        self.pg, self.store, self.engine, self.W = pg, store, engine, w
        self.chat = Chat(store)
        self.chat.ime = Pinyin(ASSETS / "pinyin.txt")
        self.font, self.tiny = mkfont(26), mkfont(22)
        self.box = pg.Rect(w - 910, bar_h + 12, 880, kb_y - bar_h - 120)
        self.toggle = (w - 70, kb_y - 62, 40)  # cx, cy, r
        self.pet = Pet(pg, 150, w - 220, kb_y - 4)
        self.pet.zfont = self.font
        self.open, self.anim, self.layer_on = False, 0.0, False
        self.chips: list = []
        self.send_rect = None
        self.cache = None
        self.last, self.caret_on, self.caret_t = time.time(), True, 0.0
        self.info, self.info_surf, self.unread = "", None, False
        self.seen_reply = 0

    # -- control --
    def set_open(self, v: bool) -> None:
        if v == self.open:
            return
        self.open = self.chat.focused = v
        self.chat.typed_at = time.time()
        self.chat.dirty = True
        if v:
            self.unread = False
        self.pet.x1 = (self.box.left - 120) if v else self.W - 220
        self.pet.say("有什么想让我做的吗？" if v else "那我先去玩啦~", 2)
        if v and self.pet.on_ground():
            self.pet.set_mode("wave", 1.5)

    def set_info(self, text: str) -> None:
        self.info, self.info_surf = text[:120], None

    # -- input --
    def down(self, slot, x: float, y: float) -> None:
        if self.pet.drag is None and self.pet.hit(x, y) and not (self.open and self.box.collidepoint(x, y)):
            self.pet.grab(slot, x, y)
        else:
            self.tap(x, y)

    def move(self, slot, x: float, y: float) -> None:
        if self.pet.drag and self.pet.drag["slot"] == slot:
            self.pet.drag_to(x, y)

    def up(self, slot) -> None:
        if self.pet.drag and self.pet.drag["slot"] == slot:
            self.pet.release()

    def tap(self, x: float, y: float) -> None:
        cx, cy, r = self.toggle
        if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 18) ** 2:
            self.set_open(not self.open)
            return
        if self.open and self.box.collidepoint(x, y):
            for rect, prompt in self.chips:
                if rect.collidepoint(x, y):
                    if isinstance(prompt, int):
                        self.chat.pick(prompt)
                    else:
                        self.chat.send(prompt)
                    return
            if self.send_rect and self.send_rect.collidepoint(x, y):
                self.chat.send(self.chat.text)
                self.chat.text = ""
                self.chat.dirty = True
            return
        if self.pet.hit(x, y):
            self.pet.tap()
        else:
            self.pet.goto(x)

    def key(self, label: str, x: float) -> bool:
        """True when the key was consumed by the open chat box (no HID)."""
        self.pet.poke()
        if not self.open:
            return False
        if label == "Esc" and self.chat.py:
            self.chat.py, self.chat.dirty = "", True
        elif label == "Esc":
            self.set_open(False)
        else:
            self.chat.key(label)
        return True

    # -- drawing --
    def _render_box(self, accent) -> None:
        pg, c, f, tf = self.pg, self.chat, self.font, self.tiny
        bw, bh = self.box.size
        s = pg.Surface((bw, bh), pg.SRCALPHA)
        for i in range(12):  # feathered glass, no outline
            pg.draw.rect(s, (22, 14, 42, 13), (i * 3, i * 3, bw - i * 6, bh - i * 6), border_radius=34)
        s.blit(shadow_text(pg, f, "Agnes 助手", accent), (34, 22))
        st = "思考中…" if c.busy else "Shift 中/英 · 空格/数字选字 · Enter 发送 · Esc 收起"
        t = shadow_text(pg, tf, st, (225, 215, 240))
        s.blit(t, (bw - t.get_width() - 34, 28))
        y_in, lh = bh - 70, tf.get_height() + 4
        y_chip = y_in - 52
        lines: list = []
        for it in c.items[-4:]:
            lines += [("you", l) for l in wrap(tf, "你：" + it["prompt"], bw - 80)[:2]]
            if it["status"] in ("done", "error"):
                lines += [("ag", l) for l in wrap(tf, "Agnes：" + (it["reply"] or "(无回复)"), bw - 80)[:4]]
            else:
                lines += [("ag", "Agnes：" + ("…正在读取设备、思考" if it["status"] == "running" else "排队中"))]
        y = 66
        for who, l in lines[-max(1, (y_chip - 70) // lh):]:
            s.blit(shadow_text(pg, tf, l, (255, 255, 255) if who == "you" else (255, 205, 232)), (34, y))
            y += lh
        self.chips, x = [], 34
        if c.py:  # composing: the chip row becomes the candidate row
            t = shadow_text(pg, f, c.py, (255, 255, 255))
            s.blit(t, (x, y_chip + (40 - t.get_height()) // 2))
            x += t.get_width() + 18
            cands = c.cands
            for i, (w, _) in enumerate(cands[c.page * PAGE:(c.page + 1) * PAGE]):
                t = tf.render(f"{i + 1}.{w}", True, (60, 30, 70))
                r = pg.Rect(x, y_chip, t.get_width() + 26, 40)
                pg.draw.rect(s, (*tuple(accent)[:3], 235 if i == 0 else 150), r, border_radius=20)
                s.blit(t, (r.x + 13, r.y + (40 - t.get_height()) // 2))
                self.chips.append((r.move(self.box.topleft), c.page * PAGE + i))
                x += r.w + 10
            if len(cands) > PAGE:
                s.blit(shadow_text(pg, tf, "- / = 翻页", (225, 215, 240)), (x + 6, y_chip + 8))
        else:
            for label, prompt in PRESETS:
                t = tf.render(label, True, (60, 30, 70))
                r = pg.Rect(x, y_chip, t.get_width() + 30, 40)
                pg.draw.rect(s, (*tuple(accent)[:3], 215), r, border_radius=20)
                s.blit(t, (r.x + 15, r.y + (40 - t.get_height()) // 2))
                self.chips.append((r.move(self.box.topleft), prompt))
                x += r.w + 12
        inp = pg.Rect(34, y_in, bw - 68 - 124, 50)
        pg.draw.rect(s, (255, 255, 255, 200), inp, border_radius=25)
        t = tf.render("中" if c.zh else "英", True, (255, 255, 255))
        pg.draw.circle(s, (*tuple(accent)[:3], 255), (inp.right - 27, inp.centery), 18)
        s.blit(t, (inp.right - 27 - t.get_width() // 2, inp.centery - t.get_height() // 2))
        inp.width -= 44
        txt = c.text if c.text else ("" if c.focused else "在这里打字…")
        t = f.render(txt + ("|" if c.focused and self.caret_on else ""), True, (50, 35, 70))
        s.set_clip(inp.inflate(-30, 0))
        s.blit(t, (max(inp.x + 18, inp.right - 18 - t.get_width()), inp.y + (50 - t.get_height()) // 2))
        s.set_clip(None)
        sr = pg.Rect(inp.right + 14, y_in, 110, 50)
        pg.draw.rect(s, (*tuple(accent)[:3], 230), sr, border_radius=25)
        t = f.render("发送", True, (60, 30, 70))
        s.blit(t, (sr.centerx - t.get_width() // 2, sr.centery - t.get_height() // 2))
        self.send_rect = sr.move(self.box.topleft)
        self.cache = s
        c.dirty = False

    def prepare(self, accent) -> object:
        """State + cached surfaces. Returns a rect the Renderer must restore (box layer appeared/changed/vanished)."""
        now = time.time()
        dt, self.last = min(0.1, now - self.last), now
        self.caret_t += dt
        if self.caret_t > 0.5:
            self.caret_t, self.caret_on = 0.0, not self.caret_on
            if self.open:
                self.chat.dirty = True
        if self.open and not self.chat.busy and now - self.chat.typed_at > 60:
            self.set_open(False)
        last = self.chat.last_reply()
        if last and last["id"] != self.seen_reply:
            self.seen_reply = last["id"]
            self.pet.say(last["reply"], 25)
            self.unread = not self.open
        self.pet.update(dt, self.chat.busy)
        dirty = None
        if self.chat.dirty or self.cache is None:
            self._render_box(accent)
            if self.layer_on:
                dirty = self.box
        target = 1.0 if self.open else 0.0
        if self.anim != target:
            self.anim = min(1.0, self.anim + dt / 0.32) if self.open else max(0.0, self.anim - dt / 0.25)
        if self.layer_on and not self.open:
            self.layer_on, dirty = False, self.box
        elif self.open and self.anim >= 1.0 and not self.layer_on:
            self.cache.set_alpha(255)  # set_alpha(None) disables per-pixel blending in pygame 2 -> opaque box
            self.layer_on, dirty = True, self.box
        return dirty

    def draw(self, canvas, accent, miss_rate: float, wpm: float) -> list:
        pg, now = self.pg, time.time()
        rects = []
        if not self.layer_on and self.anim > 0:
            e = ease(self.anim)
            self.cache.set_alpha(int(255 * e))
            rects.append(canvas.blit(self.cache, (int(self.box.x + (1 - e) * 260), self.box.y)))
            self.cache.set_alpha(255)
        if self.info:
            if self.info_surf is None:
                self.info_surf = shadow_text(pg, self.tiny, self.info, (255, 255, 255))
            rects.append(canvas.blit(self.info_surf, (30, 100)))
        rects += self.pet.draw(canvas)
        if self.chat.busy:
            rects += self.pet.bubble(canvas, self.tiny, "", True)
        elif now < self.pet.say_until:
            rects += self.pet.bubble(canvas, self.tiny, self.pet.say_text, False)
        mood = "zzz…" if self.pet.mode == "sleep" else (f"{wpm:.0f} WPM · 误触 {miss_rate * 100:.0f}%" if wpm else "")
        if mood:
            t = shadow_text(pg, self.tiny, mood, (255, 255, 255))
            mx = int(self.pet.x + 100 if self.pet.dir > 0 else self.pet.x - 100 - t.get_width())
            rects.append(canvas.blit(t, (mx, int(self.pet.y) - 150)))
        cx, cy, r = self.toggle  # toggle: soft glowing orb, no outline
        pulse = (math.sin(now * 4) + 1) / 2 if (self.chat.busy or self.unread) else 0
        s = pg.Surface((r * 4, r * 4), pg.SRCALPHA)
        c = r * 2
        for i in range(6):
            pg.draw.circle(s, (*tuple(accent)[:3], int(18 + 22 * pulse)), (c, c), int(r + 14 - i * 2))
        pg.draw.circle(s, (*tuple(accent)[:3], 235), (c, c), r)
        if self.open:
            for a, b in (((c - 12, c - 12), (c + 12, c + 12)), ((c - 12, c + 12), (c + 12, c - 12))):
                pg.draw.line(s, (60, 30, 70), a, b, 5)
        else:
            pg.draw.rect(s, (255, 255, 255), (c - 18, c - 14, 36, 24), border_radius=10)
            pg.draw.polygon(s, (255, 255, 255), [(c - 8, c + 8), (c + 2, c + 8), (c - 10, c + 18)])
            for k in (-9, 0, 9):
                pg.draw.circle(s, (*tuple(accent)[:3], 255), (c + k, c - 2), 3)
            if self.unread:
                pg.draw.circle(s, (255, 90, 120), (c + r - 6, c - r + 6), 8)
        rects.append(canvas.blit(s, (cx - c, cy - c)))
        return rects
