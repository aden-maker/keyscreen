"""Controlled experiment: does Agnes' per-user key calibration reduce touch error?

  python3 desktop/experiment.py baseline        # report on all real touches so far
  python3 desktop/experiment.py start before    # then type TEXT on the board for ~3 min (to the PC, chat closed)
  python3 desktop/experiment.py stop
  python3 desktop/experiment.py calibrate       # Agnes reads get_touch_stats for the 'before' window and adjust_key's
  python3 desktop/experiment.py start after     # type the same text again
  python3 desktop/experiment.py stop
  python3 desktop/experiment.py report          # -> evidence/experiment/{results.md, results.json, compare.svg}

Touches injected by test scripts land exactly on key centres (dx = dy = 0) and are excluded."""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "evidence" / "experiment"
PHASES = OUT / "phases.json"
BOARD = "http://169.254.220.2:8765"
TEXT = "the quick brown fox jumps over the lazy dog. pack my box with five dozen liquor jugs. 1234567890"
KEY_W, KEY_H = 128, 108


def get(path: str) -> dict:
    return json.load(urllib.request.urlopen(BOARD + path, timeout=10))


def rows(since: float, until: float = 1e12) -> list:
    return [r for r in get(f"/api/touch/rows?since={since}&until={until}")["rows"] if r[1] and (r[2] or r[3])]


def metrics(rs: list) -> dict:
    if not rs:
        return {"n": 0}
    by: dict = {}
    for _, k, dx, dy, _h in rs:
        by.setdefault(k, []).append((dx, dy))
    bias = [math.hypot(sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for v in by.values() if len(v) >= 5]
    worst = sorted(((math.hypot(sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)), k, len(v)) for k, v in by.items() if len(v) >= 5), reverse=True)[:5]
    return {"n": len(rs), "miss_rate": round(1 - sum(r[4] for r in rs) / len(rs), 4),
            "mean_error_px": round(sum(math.hypot(r[2], r[3]) for r in rs) / len(rs), 1),
            "edge_rate": round(sum(abs(r[2]) > KEY_W * 0.3 or abs(r[3]) > KEY_H * 0.3 for r in rs) / len(rs), 4),
            "key_bias_px": round(sum(bias) / len(bias), 1) if bias else None,
            "worst_keys": [{"key": k, "bias_px": round(b, 1), "n": n} for b, k, n in worst]}


def svg(sets: list, path: Path) -> None:
    """Offset scatter inside one key outline + bar chart of the metrics, per phase."""
    colors = ["#ff6fa8", "#4fa8ff", "#7bd88f"]
    W, H = 980, 420
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif">',
         '<rect width="100%" height="100%" fill="#1d1630"/>',
         '<text x="24" y="34" fill="#fff" font-size="20">触点相对键帽中心的偏移（每点一次真实按键）</text>']
    cx, cy, s = 250, 230, 2.2
    o.append(f'<rect x="{cx - KEY_W * s / 2}" y="{cy - KEY_H * s / 2}" width="{KEY_W * s}" height="{KEY_H * s}" rx="18" fill="none" stroke="#8a7fb0" stroke-dasharray="6 6"/>')
    o.append(f'<line x1="{cx - 8}" y1="{cy}" x2="{cx + 8}" y2="{cy}" stroke="#fff"/><line x1="{cx}" y1="{cy - 8}" x2="{cx}" y2="{cy + 8}" stroke="#fff"/>')
    for i, (name, rs, _m) in enumerate(sets):
        for r in rs[-1500:]:
            o.append(f'<circle cx="{cx + r[2] * s:.1f}" cy="{cy + r[3] * s:.1f}" r="2.2" fill="{colors[i]}" fill-opacity="0.45"/>')
        o.append(f'<circle cx="{40 + i * 120}" cy="{H - 24}" r="6" fill="{colors[i]}"/><text x="{52 + i * 120}" y="{H - 19}" fill="#ddd" font-size="14">{name} (n={len(rs)})</text>')
    bars = [("误触率 %", "miss_rate", 100), ("平均偏移 px", "mean_error_px", 1), ("按键系统偏差 px", "key_bias_px", 1), ("靠近键边缘 %", "edge_rate", 100)]
    x0, y0, bw = 540, 360, 22
    for j, (label, key, mul) in enumerate(bars):
        vals = [(m.get(key) or 0) * mul for _, _, m in sets]
        top = max(vals + [1e-9])
        gx = x0 + j * 105
        for i, v in enumerate(vals):
            h = 240 * v / top
            o.append(f'<rect x="{gx + i * (bw + 4)}" y="{y0 - h:.1f}" width="{bw}" height="{h:.1f}" rx="4" fill="{colors[i]}"/>')
            o.append(f'<text x="{gx + i * (bw + 4) + bw / 2}" y="{y0 - h - 6:.1f}" fill="#fff" font-size="12" text-anchor="middle">{v:.1f}</text>')
        o.append(f'<text x="{gx + 24}" y="{y0 + 20}" fill="#ccc" font-size="13" text-anchor="middle">{label}</text>')
    o.append("</svg>")
    path.write_text("\n".join(o), encoding="utf-8")


def load() -> list:
    return json.loads(PHASES.read_text()) if PHASES.exists() else []


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    ph = load()
    sets = None
    name = {"baseline": "baseline", "report": "compare"}.get(cmd, cmd)
    if cmd == "start":
        ph.append({"name": sys.argv[2] if len(sys.argv) > 2 else f"phase{len(ph) + 1}", "start": time.time(), "end": None})
        PHASES.write_text(json.dumps(ph, ensure_ascii=False, indent=1))
        print(f"[{ph[-1]['name']}] 开始。关闭助手对话框，在电脑记事本里反复输入：\n  {TEXT}\n约 3 分钟后运行 experiment.py stop")
    elif cmd == "stop":
        ph[-1]["end"] = time.time()
        PHASES.write_text(json.dumps(ph, ensure_ascii=False, indent=1))
        print(json.dumps({ph[-1]["name"]: metrics(rows(ph[-1]["start"], ph[-1]["end"]))}, ensure_ascii=False, indent=1))
    elif cmd == "calibrate":
        sys.path.insert(0, str(HERE))
        from panel import ask_agnes
        since_min = max(1, math.ceil((time.time() - ph[-1]["start"]) / 60))
        prompt = (f"调用 keyscreen-01 的 get_touch_stats（since_minutes={since_min}），在 count≥5 的键中（Fn 除外）选出平均偏移最明显的最多 4 个键，"
                  "用 adjust_key 按平均偏移的一半（限 ±15 px）把键帽往偏移方向挪，最后用两句话汇报你改了什么、为什么。")
        r = ask_agnes(prompt)
        (OUT / "calibration.json").write_text(json.dumps({"t": time.time(), "prompt": prompt, **r}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n".join(r.get("steps", [])), "\n", r.get("text") or r.get("error"))
    if cmd == "replay":
        # Hold-out replay on real touches: learn per-key offsets on the earlier half, apply the same rule
        # the calibrate prompt gives Agnes (half the mean offset, clamped to ±15 px), judge on the later half.
        rs = sorted(rows(0))
        train, test = rs[:len(rs) // 2], rs[len(rs) // 2:]
        by: dict = {}
        for _, k, dx, dy, _h in train:
            by.setdefault(k, []).append((dx, dy))
        clamp = lambda v: max(-15.0, min(15.0, v))
        shift = {k: (clamp(sum(p[0] for p in v) / len(v) / 2), clamp(sum(p[1] for p in v) / len(v) / 2))
                 for k, v in by.items() if len(v) >= 5 and k != "Fn"}
        inside = lambda dx, dy: int(abs(dx) <= KEY_W / 2 and abs(dy) <= KEY_H / 2)
        before = [(t, k, dx, dy, inside(dx, dy)) for t, k, dx, dy, _h in test]
        after = [(t, k, dx - shift.get(k, (0, 0))[0], dy - shift.get(k, (0, 0))[1], 0) for t, k, dx, dy, _h in test]
        after = [(t, k, dx, dy, inside(dx, dy)) for t, k, dx, dy, _ in after]
        sets = [("校准前", before, metrics(before)), ("回放校准后", after, metrics(after))]
        cmd, name = "report", "replay"
        (OUT / "replay_shift.json").write_text(json.dumps({"train_n": len(train), "test_n": len(test), "shift_px": shift}, ensure_ascii=False, indent=1), encoding="utf-8")
    if cmd in ("report", "baseline"):
        if sets:
            pass
        elif cmd == "baseline" or len(ph) < 2:
            rs = rows(0)
            sets = [("历史真实按键", rs, metrics(rs))]
        else:
            sets = [(p["name"], rs, metrics(rs)) for p in ph[-2:] for rs in [rows(p["start"], p["end"] or 1e12)]]
        svg(sets, OUT / f"{name}.svg")
        res = {n: m for n, _, m in sets}
        (OUT / f"{name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        lines = ["| 指标 | " + " | ".join(n for n, _, _ in sets) + " |", "|---|" + "---|" * len(sets)]
        for label, key, mul, unit in (("按键数", "n", 1, ""), ("误触率", "miss_rate", 100, "%"), ("平均偏移", "mean_error_px", 1, " px"),
                                      ("按键系统偏差", "key_bias_px", 1, " px"), ("靠近键边缘", "edge_rate", 100, "%")):
            lines.append(f"| {label} | " + " | ".join(f"{(m.get(key) or 0) * mul:.1f}{unit}" if m.get('n') else "-" for _, _, m in sets) + " |")
        if cmd == "report" and len(sets) == 2 and sets[0][2].get("n") and sets[1][2].get("n"):
            a, b = sets[0][2], sets[1][2]
            ch = lambda k: (1 - (b[k] or 0) / a[k]) * 100 if a.get(k) else 0
            lines.append(f"\n校准后：误触率下降 {ch('miss_rate'):.0f}%，按键系统偏差下降 {ch('key_bias_px'):.0f}%，平均偏移下降 {ch('mean_error_px'):.0f}%。")
        if name == "replay":
            lines.append(f"\n方法：{len(rs)} 次真实按键按时间对半分，前半学习每键偏移（取一半、限 ±15 px，与 Agnes 校准规则相同），在后半 {len(test)} 次上回放判定。")
        (OUT / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        web = HERE / "web" / "exp.json"
        if name != "baseline" or not web.exists() or json.loads(web.read_text()).get("kind") == "baseline":
            (HERE / "web" / "exp.svg").write_text((OUT / f"{name}.svg").read_text(encoding="utf-8"), encoding="utf-8")
            web.write_text(json.dumps({"kind": name, "rows": lines}, ensure_ascii=False), encoding="utf-8")  # for pitch.html
        print("\n".join(lines))


if __name__ == "__main__":
    main()
