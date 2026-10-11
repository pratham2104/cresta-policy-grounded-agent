"""BM25 retrieval over policy rules + KB articles (stdlib only).

Retrieval decides what evidence the workflow *sees*; it never decides the
answer. The policy engine and the coverage check decide what may be said.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .corpus import Passage

STOP = set("""a an the and or of to in on for is are was be by with as at it this that from any not
your you i my me we our can do does how what which who will would if than then there their its
into per under over only also about""".split())


def tokenize(s: str) -> list[str]:
    toks = re.findall(r"[a-z0-9$]+(?:\.\d+)?", s.lower())
    return [t for t in toks if t not in STOP]


class BM25:
    def __init__(self, passages: list[Passage], k1: float = 1.4, b: float = 0.75):
        self.passages = passages
        self.docs = [tokenize(p.title + " " + p.plain) for p in passages]
        self.k1, self.b = k1, b
        self.avgdl = sum(len(d) for d in self.docs) / len(self.docs)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def search(self, query: str, k: int = 4) -> list[tuple[Passage, float]]:
        q = tokenize(query)
        scores = []
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i])
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            scores.append((self.passages[i], round(s, 2)))
        scores.sort(key=lambda x: -x[1])
        return [x for x in scores[:k] if x[1] > 0]
