"""Tiny pinyin IME for the on-screen Agnes chat box. Dictionary: assets/pinyin.txt, one line per key:
`pinyin top_freq word1 word2 ...` (words by frequency), built by tools/mkpinyin.py from jieba + pypinyin."""

from __future__ import annotations

import bisect
import threading


class Pinyin:
    def __init__(self, path) -> None:
        self.d: dict = {}
        self.freq: dict = {}
        self.keys: list = []
        threading.Thread(target=self._load, args=(path,), daemon=True).start()

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
        self.d, self.freq, self.keys = d, fq, sorted(d)

    def cands(self, buf: str, limit: int = 60) -> list:
        """[(word, letters consumed)]: exact matches, else completions, then the longest prefixes."""
        d, out, seen = self.d, [], set()

        def add(w, n):
            if w not in seen:
                seen.add(w)
                out.append((w, n))

        if buf in d:
            for w in d[buf]:
                add(w, len(buf))
        else:
            i, ks = bisect.bisect_left(self.keys, buf), []
            while i < len(self.keys) and self.keys[i].startswith(buf) and len(ks) < 400:
                ks.append(self.keys[i])
                i += 1
            for k in sorted(ks, key=lambda k: -self.freq[k])[:8]:
                add(d[k][0], len(buf))
        for n in range(len(buf) - 1, 0, -1):
            if len(out) >= limit:
                break
            for w in d.get(buf[:n], [])[:20]:
                add(w, n)
        return out[:limit]
