"""Top-half widgets: the Agnes desk pet (sprite in assets/agnes.png), a slide-in Agnes chat box behind a toggle,
and an info line (weather / next event / foreground app, pushed by desktop/panel.py). Borderless by design.

Chat flow: board queues prompts -> desktop/panel.py polls /api/chat/pending, runs AGH -> /api/chat/reply.
Keys go to the chat box only while it is open; closed, every key goes to the PC."""

from __future__ import annotations

import collections
import math
import random
import threading
import time
from pathlib import Path

import weather
from ime import Pinyin
from pet import Pet

ASSETS = Path(__file__).resolve().parent / "assets"
PRESETS = [  # (chip label, prompt)
    ("二次元模式", "用 keyscreen-01 的 list_wallpapers 看键盘上有哪些壁纸，选一张最有二次元/活泼感觉的，用 set_wallpaper 应用到 default profile，主题色选粉色或天蓝色系。一句话说明理由。"),
    ("写代码配色", "我要写代码了。用 keyscreen-01 的 list_wallpapers 选一张最适合长时间写代码的壁纸，set_wallpaper 应用到 default profile，配协调的主题色和不透明度。一句话说明理由。"),
    ("校准按键", "调用 keyscreen-01 的 get_touch_stats（since_minutes=0），在 count≥10 的键中（Fn 除外）选出偏移最明显的 2 个，用 adjust_key 按平均偏移的一半（限 ±15 px）微调，一句话汇报。"),
    ("换语言键盘", "换语言键盘"),
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


LANG_WORDS = {"ru": ("俄语", "俄文", "俄罗斯"), "fr": ("法语", "法文"), "de": ("德语", "德文"), "en": ("英语", "英文", "默认键盘")}
LANG_INTRO = {"en": "已切回英语 QWERTY 键盘，电脑也恢复你原来的输入法～",
              "ru": "已切到俄语 ЙЦУКЕН 键盘：西里尔字母按使用频率排布，最常用的 А、О 在中排正中。Привет! 你好！",
              "fr": "已切到法语 AZERTY 键盘：A/Q、Z/W 互换，数字要按 Shift，é è ç à 直接在数字行。Bonjour ! 你好！",
              "de": "已切到德语 QWERTZ 键盘：Y/Z 互换，Ö Ä Ü ß 都有独立键位。Hallo! 你好！"}


def lang_command(prompt: str) -> str | None:
    """'next' for the language chip, a language code for short commands like 切换到俄语键盘, else None."""
    if "set_language" in prompt or prompt in ("换语言", "切换语言", "换语言键盘"):
        return "next"
    if len(prompt) <= 16 and any(w in prompt for w in ("键盘", "切换", "换成", "切到", "换到")):
        return next((c for c, ws in LANG_WORDS.items() if any(w in prompt for w in ws)), None)
    return None


class Chat:
    def __init__(self, store) -> None:
        self.store = store
        self.lock = threading.Lock()
        self.items: list[dict] = []  # {id, prompt, status: queued|running|done|error, reply, t}
        self.text, self.focused, self.shift, self.caps = "", False, False, False
        self.dirty, self.next_id, self.typed_at = True, 1, 0.0
        self.ime, self.zh, self.py, self.page = None, True, "", 0  # Chinese pinyin input by default
        self._cands = ("", [], "")
        self.key_t = 0.0
        self.last_poll = 0.0  # desktop/panel.py polls every second; silence means the PC side is not there

    def expire(self, now: float) -> None:
        for it in list(self.items):
            if it["status"] == "queued" and now - it["t"] > 12 and now - self.last_poll > 8:
                self.reply(it["id"], "电脑端还没连上～检查一下 USB 线；电脑开机登录后会自动连接哦", ok=False)
            elif it["status"] == "running" and now - it["t"] > 150:
                self.reply(it["id"], "Agnes 这次想太久了，换个说法再试试？", ok=False)

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
        lang = lang_command(prompt)
        if lang and hasattr(self.store, "set_lang"):  # instant on the board; no round trip to Agnes
            self.reply(it["id"], LANG_INTRO[self.store.set_lang(lang)])
        return it

    def pending(self) -> dict | None:
        self.last_poll = time.time()
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
            self._cands = (self.py, *(self.ime.query(self.py) if (self.ime and self.py) else ([], self.py)))
        return self._cands[1]

    @property
    def seg(self) -> str:
        self.cands
        return self._cands[2]

    def pick(self, i: int) -> None:
        c = self.cands
        if 0 <= i < len(c):
            w, n = c[i]
            if self.ime:
                self.ime.learn(self.py[:n], w)
            self.text, self.py, self.page = (self.text + w)[:200], self.py[n:].lstrip("'"), 0
        self.dirty = True

    def key(self, label: str) -> None:
        self.typed_at, self.key_t = time.time(), time.perf_counter()
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
            if (len(label) == 1 and label.isalpha()) or (label == "'" and not self.py.endswith("'")):
                self.py = (self.py + label.lower())[:40]
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
        self.cache = self.glass = self.glass_acc = None
        bw, bh = self.box.size
        self.zones = {"top": pg.Rect(0, 0, bw, bh - 122), "row": pg.Rect(0, bh - 122, bw, 50), "in": pg.Rect(0, bh - 72, bw, 72)}
        self.sigs: dict = {}
        self._memo: dict = {}
        self.wfonts = {"big": mkfont(84), "mid": mkfont(30), "small": self.tiny}
        self.wdata: dict = {}
        self.card, self.card_rect, self.card_dirty = None, pg.Rect(28, bar_h + 14, 470, 266), True  # static layer
        self.wake = None  # threading.Event set by the Renderer: a chat key wakes the frame loop early
        self.held = None  # [label, next repeat time] for typematic Bksp/Space
        self.perf = collections.deque(maxlen=100)  # (composite ms, key -> composited ms)
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
        if not v:
            self.pet.say("那我先去玩啦~", 2)
        if v and self.pet.on_ground():
            self.pet.set_mode("wave", 1.5)

    def set_info(self, text: str) -> None:
        self.info, self.card_dirty = text[:60], True

    def set_weather(self, data: dict) -> None:
        self.wdata, self.card_dirty = dict(data), True

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
            self.caret_on, self.caret_t = True, 0.0
            self.held = [label, time.time() + 0.45] if label in ("Bksp", "Space") else None
        if self.wake is not None:
            self.wake.set()
        return True

    def key_up(self, label: str) -> None:
        if self.held and self.held[0] == label:
            self.held = None

    # -- drawing --
    # The box is cached as three zones (header+history, chip/candidate row, input line) composited over a glass layer;
    # a keystroke only recomposites the small zones it changed, and the Renderer restores just those rects.
    def _glass(self, accent) -> None:
        pg = self.pg
        bw, bh = self.box.size
        g = pg.Surface((bw, bh), pg.SRCALPHA)
        a = tuple(accent)[:3]
        for y in range(bh):
            u = y / bh
            g.fill((int(34 + a[0] * 0.10 * (1 - u)), int(22 + a[1] * 0.06 * (1 - u)), int(58 + a[2] * 0.10 * (1 - u)), int(150 + 40 * u)), (0, y, bw, 1))
        g.fill((255, 255, 255, 16), (40, 2, bw - 80, 1))
        m = pg.Surface((bw // 8, bh // 8), pg.SRCALPHA)  # feathered rounded mask: drawn small, scaled up soft
        pg.draw.rect(m, (255, 255, 255, 255), m.get_rect().inflate(-2, -2), border_radius=4)
        g.blit(pg.transform.smoothscale(m, (bw, bh)), (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        self.glass, self.glass_acc = g, a
        self.cache = g.copy()
        self.sigs = {}

    def _zone(self, name: str, content) -> None:
        z = self.zones[name]
        self.cache.fill((0, 0, 0, 0), z)
        self.cache.blit(self.glass, z.topleft, z)
        self.cache.blit(content, z.topleft)

    def _bubble(self, lines: list, fg, bg) -> object:
        pg, tf = self.pg, self.tiny
        lh = tf.get_height() + 2
        w = max(tf.size(l)[0] for l in lines) + 30
        s = pg.Surface((w, len(lines) * lh + 18), pg.SRCALPHA)
        pg.draw.rect(s, bg, s.get_rect(), border_radius=18)
        for i, l in enumerate(lines):
            s.blit(tf.render(l, True, fg), (15, 9 + i * lh))
        return s

    def _render_top(self, accent) -> None:
        pg, c, f, tf = self.pg, self.chat, self.font, self.tiny
        z = self.zones["top"]
        s = pg.Surface(z.size, pg.SRCALPHA)
        a = tuple(accent)[:3]
        pg.draw.circle(s, (*a, 255), (50, 30), 19)  # avatar: tiny Agnes face
        pg.draw.circle(s, (255, 236, 226), (50, 33), 13)
        pg.draw.ellipse(s, (190, 156, 255), (36, 15, 28, 12))
        for ex in (45, 55):
            pg.draw.circle(s, (52, 58, 120), (ex, 34), 3)
        pg.draw.arc(s, (200, 80, 110), (46, 35, 9, 6), 3.5, 6.0, 2)
        t = shadow_text(pg, f, "Agnes", (255, 255, 255))
        s.blit(t, (80, 30 - t.get_height() // 2))
        x, busy = 80 + t.get_width() + 14, c.busy
        pg.draw.circle(s, (255, 200, 90) if busy else (120, 230, 160), (x, 31), 5)
        t = tf.render("思考中…" if busy else "在线 · agnes-3.0-flash", True, (215, 205, 235))
        s.blit(t, (x + 12, 31 - t.get_height() // 2))
        t = tf.render("Shift 中/英 · Enter 发送 · Esc 收起", True, (190, 180, 215))
        s.blit(t, (z.w - t.get_width() - 34, 31 - t.get_height() // 2))
        maxw, y = int(z.w * 0.72), z.h - 4
        for it in reversed(c.items[-6:]):
            if it["status"] in ("done", "error"):
                ls = wrap(tf, it["reply"] or "(无回复)", maxw)
                ls = ls[:4] if len(ls) <= 4 else ls[:3] + [ls[3][:-1] + "…"]
            else:
                ls = ["正在读取设备、思考…" if it["status"] == "running" else "排队中…"]
            for b, right in ((self._bubble(ls, (70, 50, 90), (255, 255, 255, 228)), False),
                             (self._bubble(wrap(tf, it["prompt"], maxw)[:3], (60, 30, 70), (*a, 225)), True)):
                y -= b.get_height() + 6
                if y < 56:
                    break
                s.blit(b, (z.w - 34 - b.get_width() if right else 34, y))
            if y < 56:
                break
        if not c.items:
            t = tf.render("嗨～我是 Agnes。打字或点下面的快捷指令，我会帮你操控键盘～", True, (225, 215, 240))
            s.blit(t, ((z.w - t.get_width()) // 2, z.h // 2 + 10))
        self._zone("top", s)

    def _render_row(self, accent) -> None:
        pg, c, f, tf = self.pg, self.chat, self.font, self.tiny
        z = self.zones["row"]
        s = pg.Surface(z.size, pg.SRCALPHA)
        a = tuple(accent)[:3]
        self.chips, x, cy = [], 34, z.h // 2
        if c.py:  # composing: PC-style candidate strip
            t = f.render(c.seg or c.py, True, (*a,))
            s.blit(t, (x, cy - t.get_height() // 2))
            x += t.get_width() + 16
            cands = c.cands
            for i, (w, _) in enumerate(cands[c.page * PAGE:(c.page + 1) * PAGE]):
                t = f.render(w, True, (60, 30, 70) if i == 0 else (255, 255, 255))
                n = tf.render(str(i + 1), True, (60, 30, 70) if i == 0 else (200, 190, 225))
                r = pg.Rect(x, cy - 20, n.get_width() + t.get_width() + 30, 40)
                if i and r.right > z.w - 170:
                    break
                if i == 0:
                    pg.draw.rect(s, (*a, 240), r, border_radius=20)
                s.blit(n, (r.x + 12, cy - n.get_height() // 2 + 1))
                s.blit(t, (r.x + 18 + n.get_width(), cy - t.get_height() // 2))
                self.chips.append((r.move(self.box.x, self.box.y + z.y), c.page * PAGE + i))
                x += r.w + 6
            if len(cands) > PAGE:
                t = tf.render(f"- = 翻页  {c.page + 1}/{(len(cands) + PAGE - 1) // PAGE}", True, (200, 190, 225))
                s.blit(t, (z.w - 34 - t.get_width(), cy - t.get_height() // 2))
        else:
            for label, prompt in PRESETS:
                t = tf.render(label, True, (255, 255, 255))
                r = pg.Rect(x, cy - 19, t.get_width() + 30, 38)
                pg.draw.rect(s, (255, 255, 255, 38), r, border_radius=19)
                s.blit(t, (r.x + 15, cy - t.get_height() // 2))
                self.chips.append((r.move(self.box.x, self.box.y + z.y), prompt))
                x += r.w + 10
        self._zone("row", s)

    def _render_input(self, accent) -> None:
        pg, c, f, tf = self.pg, self.chat, self.font, self.tiny
        z = self.zones["in"]
        s = pg.Surface(z.size, pg.SRCALPHA)
        a = tuple(accent)[:3]
        inp = pg.Rect(34, 6, z.w - 68 - 66, 52)
        pg.draw.rect(s, (255, 255, 255, 222), inp, border_radius=26)
        pg.draw.circle(s, (*a, 255), (inp.right - 28, inp.centery), 17)
        t = tf.render("中" if c.zh else "英", True, (255, 255, 255))
        s.blit(t, (inp.right - 28 - t.get_width() // 2, inp.centery - t.get_height() // 2))
        field = pg.Rect(inp.x + 22, inp.y, inp.w - 70, inp.h)
        if c.text:
            t = f.render(c.text, True, (50, 35, 70))
            tx = min(field.x, field.right - t.get_width() - 4)
            s.set_clip(field)
            s.blit(t, (tx, field.centery - t.get_height() // 2))
            s.set_clip(None)
            cx = tx + t.get_width() + 2
        else:
            t = f.render("和 Agnes 说点什么…", True, (170, 155, 190))
            s.blit(t, (field.x + 8, field.centery - t.get_height() // 2))
            cx = field.x
        if c.focused and self.caret_on:
            pg.draw.rect(s, (*a, 255), (cx, field.centery - 15, 3, 30), border_radius=1)
        sc = (inp.right + 40, inp.centery)
        pg.draw.circle(s, (*a, 255), sc, 26)
        pg.draw.polygon(s, (255, 255, 255), [(sc[0] - 10, sc[1] - 11), (sc[0] + 13, sc[1]), (sc[0] - 10, sc[1] + 11), (sc[0] - 5, sc[1])])
        self.send_rect = pg.Rect(sc[0] - 30, sc[1] - 30, 60, 60).move(self.box.x, self.box.y + z.y)
        self._zone("in", s)

    def prepare(self, accent) -> object:
        """State + cached surfaces. Returns a rect the Renderer must restore (box layer appeared/changed/vanished)."""
        pg, now = self.pg, time.time()
        dt, self.last = min(0.1, now - self.last), now
        self.caret_t += dt
        if self.caret_t > 0.53:
            self.caret_t, self.caret_on = 0.0, not self.caret_on
        if self.held and now >= self.held[1]:
            self.held[1] = now + 0.033  # typematic: 450 ms delay, ~30 repeats/s
            self.chat.key(self.held[0])
            self.caret_on, self.caret_t = True, 0.0
        if self.open and not self.chat.busy and now - self.chat.typed_at > 60:
            self.set_open(False)
        if int(now) != int(now - dt):
            self.chat.expire(now)
        last = self.chat.last_reply()
        if last and last["id"] != self.seen_reply:
            self.seen_reply = last["id"]
            if self.open:  # the reply is already in the box; a bubble would cover it
                self.pet.act("cheer")
            else:
                self.pet.say(last["reply"], 25)
            self.unread = not self.open
        self.pet.update(dt, self.chat.busy)
        c = self.chat
        if self.cache is None or tuple(accent)[:3] != self.glass_acc:
            self._glass(accent)
        t0 = time.perf_counter()
        sigs = {"top": (tuple((it["id"], it["status"], len(it["reply"])) for it in c.items), c.busy),
                "row": (c.py, c.page, len(c.cands) if c.py else 0),
                "in": (c.text, c.zh, c.focused, self.caret_on)}
        changed = None
        for name, render in (("top", self._render_top), ("row", self._render_row), ("in", self._render_input)):
            if sigs[name] != self.sigs.get(name):
                self.sigs[name] = sigs[name]
                render(accent)
                z = self.zones[name].move(self.box.topleft)
                changed = z if changed is None else changed.union(z)
        if changed is not None and c.key_t:
            self.perf.append(((time.perf_counter() - t0) * 1000, (time.perf_counter() - c.key_t) * 1000))
            c.key_t = 0.0
        dirty = changed if self.layer_on else None
        target = 1.0 if self.open else 0.0
        if self.anim != target:
            self.anim = min(1.0, self.anim + dt / 0.28) if self.open else max(0.0, self.anim - dt / 0.22)
        if self.layer_on and not self.open:
            self.layer_on, dirty = False, self.box
        elif self.open and self.anim >= 1.0 and not self.layer_on:
            self.cache.set_alpha(255)  # set_alpha(None) disables per-pixel blending in pygame 2 -> opaque box
            self.layer_on, dirty = True, self.box
        if self.card_dirty:
            self.card_dirty = False
            self.card = weather.card(pg, self.wfonts, self.wdata, self.info) if (self.wdata or self.info) else None
            dirty = self.card_rect if dirty is None else dirty.union(self.card_rect)
        return dirty

    def draw(self, canvas, accent, miss_rate: float, wpm: float) -> list:
        pg, now = self.pg, time.time()
        rects = []
        if not self.layer_on and self.anim > 0:
            e = ease(self.anim)
            self.cache.set_alpha(int(255 * e))
            rects.append(canvas.blit(self.cache, (int(self.box.x + (1 - e) * 260), self.box.y)))
            self.cache.set_alpha(255)
        rects += self.pet.draw(canvas)
        if self.chat.busy:
            rects += self.pet.bubble(canvas, self.tiny, "", True)
        elif now < self.pet.say_until:
            rects += self.pet.bubble(canvas, self.tiny, self.pet.say_text, False)
        mood = "zzz…" if self.pet.mode == "sleep" else (f"{wpm:.0f} WPM · 误触 {miss_rate * 100:.0f}%" if wpm else "")
        if mood:
            t = self.memo(("mood", mood), lambda: shadow_text(pg, self.tiny, mood, (255, 255, 255)))
            mx = int(self.pet.x + 100 if self.pet.dir > 0 or self.pet.x - 110 - t.get_width() < 0 else self.pet.x - 100 - t.get_width())
            rects.append(canvas.blit(t, (mx, int(self.pet.y) - 150)))
        cx, cy, r = self.toggle
        pulse = round((math.sin(now * 4) + 1) / 2 * 8) / 8 if (self.chat.busy or self.unread) else 0
        s = self.memo(("orb", self.open, self.unread, pulse, tuple(accent)[:3]), lambda: self._orb(accent, pulse))
        rects.append(canvas.blit(s, (cx - r * 2, cy - r * 2)))
        return rects

    def memo(self, key, build):
        if key not in self._memo:
            if len(self._memo) > 64:
                self._memo.clear()
            self._memo[key] = build()
        return self._memo[key]

    def _orb(self, accent, pulse: float):
        """Toggle: soft glowing orb, no outline."""
        pg, r = self.pg, self.toggle[2]
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
        return s
