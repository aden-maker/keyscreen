"""Pinyin IME for the on-screen Agnes chat box, Sogou-style: whole-sentence conversion (Viterbi over dictionary words),
initials abbreviations (nh -> 你好), completion of a half-typed last syllable, ' as a syllable separator,
and a user dictionary that learns picked words/phrases (assets/ime_user.txt).

Dictionary: assets/pinyin.txt, one line per key: `pinyin top_freq word1 word2 ...` (built by tools/mkpinyin.py)."""

from __future__ import annotations

import bisect
import math
import threading
from pathlib import Path

WORD_PENALTY, ABBR_PENALTY, TAIL_PENALTY, RAW_COST = 2.5, 6.0, 3.0, 40.0  # per-word costs: favour long words


class Pinyin:
    def __init__(self, path, user_path=None) -> None:
        self.d: dict = {}
        self.freq: dict = {}
        self.keys: list = []
        self.syl: set = set()
        self.sylpre: set = set()
        self.ab: dict = {}
        self.abf: dict = {}
        self.top = 1.0
        self.user_path = Path(user_path) if user_path else Path(str(path)).with_name("ime_user.txt")
        self.lock = threading.Lock()
        threading.Thread(target=self._load, args=(path,), daemon=True).start()

    # ---------- loading ----------
    def _load(self, path) -> None:
        d, fq = {}, {}
        try:
            with open(str(path), encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) > 2:
                        d[parts[0]], fq[parts[0]] = parts[2:], int(parts[1])
        except OSError:
            return
        syl = {k for k, ws in d.items() if len(k) <= 6 and any(len(w) == 1 for w in ws)}
        self.sylpre = {s[:i] for s in syl for i in range(1, len(s) + 1)}
        self.d, self.freq, self.syl, self.keys = d, fq, syl, sorted(d)
        self.top = float(max(fq.values()) or 1)
        try:
            for line in self.user_path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2:
                    self._promote(parts[0], parts[1])
        except OSError:
            pass
        ab: dict = {}
        for k, ws in d.items():
            n = len(ws[0])
            if 2 <= n <= 4:
                sy = self.split(k)
                if sy and len(sy) == n:
                    ab.setdefault("".join(s[0] for s in sy), []).append((fq[k], ws[0]))
        self.ab = {k: [w for _, w in sorted(v, reverse=True)[:12]] for k, v in ab.items()}
        self.abf = {k: max(f for f, _ in v) for k, v in ab.items()}

    def is_pinyin(self, key: str) -> bool:
        """Full pinyin, allowing a half-typed final syllable (zhongg)."""
        for t in range(min(6, len(key)) + 1):
            head, tail = key[:len(key) - t], key[len(key) - t:]
            if (not tail or tail in self.sylpre) and (not head or self.split(head)):
                return True
        return False

    def split(self, s: str) -> list | None:
        """Fewest-syllable segmentation of a full-pinyin string."""
        best = [None] * (len(s) + 1)
        best[0] = []
        for i in range(len(s)):
            if best[i] is None:
                continue
            for j in range(min(len(s), i + 6), i, -1):
                if s[i:j] in self.syl and (best[j] is None or len(best[j]) > len(best[i]) + 1):
                    best[j] = best[i] + [s[i:j]]
        return best[-1]

    # ---------- learning ----------
    def _promote(self, key: str, word: str) -> bool:
        ws = self.d.get(key)
        if ws and ws[0] == word:
            return False
        if ws:
            if word in ws:
                ws.remove(word)
            ws.insert(0, word)
        else:
            self.d[key] = [word]
            bisect.insort(self.keys, key)
        self.freq[key] = max(self.freq.get(key, 0), 50000)
        return True

    def learn(self, raw: str, word: str) -> None:
        key = raw.replace("'", "")
        if not key or not word or not self.d:
            return
        with self.lock:
            if self._promote(key, word):
                try:
                    with open(str(self.user_path), "a", encoding="utf-8") as f:
                        f.write(f"{key} {word}\n")
                except OSError:
                    pass

    # ---------- conversion ----------
    def _tail(self, piece: str):
        """Best completion of a half-typed final piece: (freq, word)."""
        i, best, n = bisect.bisect_left(self.keys, piece), None, 0
        while i < len(self.keys) and self.keys[i].startswith(piece) and n < 80:
            k = self.keys[i]
            if best is None or self.freq[k] > best[0]:
                best = (self.freq[k], self.d[k][0])
            i, n = i + 1, n + 1
        return best

    def sentence(self, buf: str):
        """Viterbi over dictionary words -> (text, display segmentation, number of words)."""
        n, d, top = len(buf), self.d, self.top
        best = [None] * (n + 1)  # (cost, prev, word, shown)
        best[0] = (0.0, -1, "", "")
        for i in range(n):
            if best[i] is None:
                continue
            c0 = best[i][0]
            if buf[i] == "'":
                if best[i + 1] is None or best[i + 1][0] > c0:
                    best[i + 1] = (c0, i, "", "")
                continue
            for j in range(i + 1, min(n, i + 24) + 1):
                if buf[j - 1] == "'":
                    break
                p, opt = buf[i:j], None
                if p in d:
                    opt = (c0 + WORD_PENALTY - math.log(self.freq[p] / top), d[p][0], "'".join(self.split(p) or [p]))
                elif 2 <= len(p) <= 4 and p in self.ab:
                    opt = (c0 + ABBR_PENALTY - math.log(self.abf[p] / top), self.ab[p][0], "'".join(p))
                elif j == n and len(p) <= 6:
                    t = self._tail(p)
                    if t:
                        opt = (c0 + TAIL_PENALTY - math.log(t[0] / top), t[1], p)
                if opt is None and j == i + 1:
                    opt = (c0 + RAW_COST, p, p)
                if opt and (best[j] is None or best[j][0] > opt[0]):
                    best[j] = (opt[0], i, opt[1], opt[2])
        words, shown, j = [], [], n
        while j > 0 and best[j]:
            _, i, w, s = best[j]
            if w:
                words.append(w)
                shown.append(s)
            j = i
        return "".join(reversed(words)), "'".join(reversed(shown)), len(words)

    def query(self, buf: str, limit: int = 60):
        """-> ([(word, letters consumed)], segmented display string)."""
        if not self.d or not buf:
            return [], buf
        with self.lock:
            out, seen = [], set()

            def add(w, k):
                if w and w not in seen:
                    seen.add(w)
                    out.append((w, k))

            sent, shown, nw = self.sentence(buf)
            key = buf.replace("'", "")
            if len(key) > 4 and not self.is_pinyin(key):  # <= 4 letters is most likely an abbreviation (zgrm)
                add(key, len(buf))  # not pinyin (an English word): offer the letters first, like Sogou
            if nw > 1:
                add(sent, len(buf))
            for w in self.d.get(key, []):
                add(w, len(buf))
            for w in self.ab.get(key, []):
                add(w, len(buf))
            if key not in self.d and key not in self.ab:
                t = self._tail(key)
                if t:
                    add(t[1], len(buf))
            if nw <= 1:
                add(sent, len(buf))
            for k in range(len(buf) - 1, 0, -1):
                if len(out) >= limit:
                    break
                p = buf[:k].replace("'", "")
                for w in self.d.get(p, [])[:16]:
                    add(w, k)
                for w in self.ab.get(p, [])[:6]:
                    add(w, k)
            return out[:limit], shown
