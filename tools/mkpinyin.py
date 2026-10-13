"""Build board/assets/pinyin.txt for board/ime.py (run on the PC: pip install jieba pypinyin)."""

from pathlib import Path

import jieba
from pypinyin import Style, lazy_pinyin, pinyin

OUT = Path(__file__).resolve().parent.parent / "board" / "assets" / "pinyin.txt"
cjk = lambda w: all("\u4e00" <= c <= "\u9fff" for c in w)

words = []
with jieba.get_dict_file() as f:
    for line in f:
        parts = line.decode("utf-8").split()
        if len(parts) >= 2 and 1 <= len(parts[0]) <= 4 and cjk(parts[0]):
            words.append((int(parts[1]), parts[0]))
singles = [x for x in words if len(x[1]) == 1]
multi = sorted((x for x in words if len(x[1]) > 1), reverse=True)[:60000]

d = {}
for fr, w in singles:
    for py in set(pinyin(w, style=Style.NORMAL, heteronym=True)[0]):
        d.setdefault(py, []).append((fr, w))
for fr, w in multi:
    key = "".join(lazy_pinyin(w))
    if key.isascii() and key.isalpha():
        d.setdefault(key, []).append((fr, w))

with open(OUT, "w", encoding="utf-8") as f:
    for key in sorted(d):
        if key.isascii() and key.isalpha():
            ws = sorted(d[key], reverse=True)[:30]
            f.write(f"{key} {ws[0][0]} {' '.join(w for _, w in ws)}\n")
print(OUT, len(d), OUT.stat().st_size // 1024, "KB")
