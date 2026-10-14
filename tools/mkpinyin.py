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
# Everyday chat / demo phrases that jieba's corpus under-weights (otherwise 我想 loses to 我向).
EXTRA = """我想 我要 我们 你们 他们 帮我 帮你 一下 一份 一个 一首 什么 怎么 怎么样 为什么 可以吗 不是 没有 知道 现在 今天 明天 昨天
天气 谢谢 你好 好的 没问题 打开 关闭 设置 壁纸 键盘 屏幕 主题 颜色 粉色 蓝色 切换 写代码 校准 按键 汇报 总结 分析 打字 速度 误触
电脑 助手 评委 比赛 黑客松 人工智能 演示 看板娘 二次元 可爱 喜欢 推荐 音乐 播放 邮件 安排 日程 提醒 会议 下午 上午 晚上 几点 西安
换一张 换个 好看 适合 帮我看看 介绍一下 你自己 大家好 辛苦了 加油 晚安 早上好 下班 上班 休息 喝水 文件 整理 一句话 帮我写 写一份 写一个 写一封 写代码 一首歌""".split()
words += [(300000, w) for w in EXTRA]
singles = [x for x in words if len(x[1]) == 1]
multi = sorted((x for x in words if 1 < len(x[1]) <= 5), reverse=True)[:60000]

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
