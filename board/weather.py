"""iPhone-style medium weather widget for the top half. Data is pushed by desktop/panel.py (the board is offline):
{city, temp, desc, code, hi, lo, hourly: [{label, code, temp}]} with wttr.in weather codes.
Icons are drawn at 3x and smoothscaled down (clean anti-aliasing without overlap seams)."""

from __future__ import annotations

import time

FOG = {143, 248, 260}
THUNDER = {200, 386, 389, 392, 395}
SNOW = {179, 182, 185, 227, 230, 281, 284, 311, 314, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377}
SKY = {  # (top, bottom) gradients
    "clear": ((86, 160, 238), (40, 104, 200)), "cloud": ((120, 140, 170), (72, 88, 120)), "rain": ((84, 104, 136), (44, 56, 84)),
    "night": ((32, 44, 96), (12, 16, 48)), "snow": ((150, 170, 200), (96, 116, 150)),
}


def kind(code) -> str:
    code = int(code or 0)
    if code == 113:
        return "clear"
    if code == 116:
        return "partly"
    if code in (119, 122):
        return "cloud"
    if code in FOG:
        return "fog"
    if code in THUNDER:
        return "thunder"
    if code in SNOW:
        return "snow"
    return "rain" if code else "cloud"


def night(hour: int | None = None) -> bool:
    h = time.localtime().tm_hour if hour is None else hour
    return h < 6 or h >= 19


def icon(pg, k: str, size: int, is_night: bool):
    S = size * 3
    s = pg.Surface((S, S), pg.SRCALPHA)
    u = S / 100

    def cloud(dx=0, dy=0, c=(246, 248, 252)):
        for cx, cy, r in ((34, 60, 17), (54, 50, 24), (73, 62, 16)):
            pg.draw.circle(s, c, (int((cx + dx) * u), int((cy + dy) * u)), int(r * u))
        pg.draw.rect(s, c, (int((34 + dx) * u), int((60 + dy) * u), int(39 * u), int(18 * u)), border_radius=int(9 * u))

    def sun(cx, cy, r):
        for i in range(8):
            v = pg.math.Vector2(0, 1).rotate(i * 45)
            pg.draw.line(s, (255, 214, 80), (cx * u + v.x * r * 1.45 * u, cy * u + v.y * r * 1.45 * u),
                         (cx * u + v.x * r * 1.95 * u, cy * u + v.y * r * 1.95 * u), int(5 * u))
        pg.draw.circle(s, (255, 204, 64), (int(cx * u), int(cy * u)), int(r * u))

    def moon(cx, cy, r):
        pg.draw.circle(s, (244, 240, 214), (int(cx * u), int(cy * u)), int(r * u))
        pg.draw.circle(s, (0, 0, 0, 0), (int((cx + r * 0.5) * u), int((cy - r * 0.35) * u)), int(r * 0.85 * u))

    if k == "clear":
        moon(50, 50, 28) if is_night else sun(50, 50, 22)
    elif k == "partly":
        moon(38, 36, 20) if is_night else sun(38, 36, 15)
        cloud(6, 6)
    elif k == "fog":
        for i, y in enumerate((38, 54, 70)):
            pg.draw.line(s, (232, 236, 244), (int((20 + i * 6) * u), int(y * u)), (int((80 - i * 4) * u), int(y * u)), int(7 * u))
    else:
        cloud(0, -8, (236, 240, 248) if k != "cloud" else (246, 248, 252))
        if k == "rain":
            for x in (36, 52, 68):
                pg.draw.line(s, (110, 190, 255), (int(x * u), int(80 * u)), (int((x - 5) * u), int(94 * u)), int(5 * u))
        elif k == "snow":
            for x in (36, 52, 68):
                pg.draw.circle(s, (255, 255, 255), (int(x * u), int(88 * u)), int(4 * u))
        elif k == "thunder":
            pg.draw.polygon(s, (255, 210, 60), [(int(a * u), int(b * u)) for a, b in ((56, 66), (42, 86), (52, 86), (46, 100), (64, 78), (54, 78), (60, 66))])
    return pg.transform.smoothscale(s, (size, size))


def card(pg, fonts: dict, data: dict, info: str, w: int = 470, h: int = 226):
    """-> SRCALPHA surface (w, h + info row)."""
    k = kind(data.get("code"))
    nt = night()
    top, bot = SKY["night" if nt and k in ("clear", "partly") else "clear" if k in ("clear", "partly") else
                  "snow" if k == "snow" else "rain" if k in ("rain", "thunder") else "cloud"]
    out = pg.Surface((w, h + 40), pg.SRCALPHA)
    g = pg.Surface((w, h), pg.SRCALPHA)
    for y in range(h):
        t = y / h
        g.fill(tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (235,), (0, y, w, 1))
    m = pg.Surface((w, h), pg.SRCALPHA)
    pg.draw.rect(m, (255, 255, 255, 255), m.get_rect(), border_radius=30)
    g.blit(m, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    out.blit(g, (0, 0))
    big, mid, sm = fonts["big"], fonts["mid"], fonts["small"]
    white, soft = (255, 255, 255), (230, 238, 250)
    temp = data.get("temp")
    out.blit(mid.render(data.get("city") or "天气", True, white), (24, 16))
    out.blit(big.render(f"{temp}°" if temp is not None else "--°", True, white), (20, 44))
    ic = icon(pg, k, 54, nt)
    out.blit(ic, (w - 24 - 54, 14))
    t = sm.render(data.get("desc") or "", True, white)
    out.blit(t, (w - 24 - t.get_width(), 74))
    if data.get("hi") is not None:
        t = sm.render(f"最高 {data['hi']}°  最低 {data['lo']}°", True, soft)
        out.blit(t, (w - 24 - t.get_width(), 102))
    hours = (data.get("hourly") or [])[:6]
    if hours:
        out.fill((255, 255, 255, 60), (24, 136, w - 48, 1))
        col = (w - 48) / len(hours)
        for i, hr in enumerate(hours):
            cx = int(24 + col * (i + 0.5))
            t = sm.render(str(hr.get("label", "")), True, soft)
            out.blit(t, (cx - t.get_width() // 2, 144))
            hk = kind(hr.get("code"))
            hn = night(hr.get("hour")) if hr.get("hour") is not None else nt
            out.blit(icon(pg, hk, 30, hn), (cx - 15, 170))
            t = sm.render(f"{hr.get('temp', '--')}°", True, white)
            out.blit(t, (cx - t.get_width() // 2, 200 - 2))
    if info:
        sh = sm.render(info, True, (0, 0, 0))
        sh.set_alpha(140)
        out.blit(sh, (12, h + 10))
        out.blit(sm.render(info, True, white), (10, h + 8))
    return out
