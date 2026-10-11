"""Grounding gate.

Two jobs:
  * verify_quote: every citation must be a verbatim substring of the cited
    passage (after markdown normalisation). A reply whose citation does not
    verify is not allowed out.
  * find_support: the answerability check. A question is answerable only if
    some single sentence in the corpus mentions ALL of the question's required
    concept groups together. Topical overlap (e.g. a passage that mentions
    taxes somewhere) is not enough; that is how incident #2 happened.
"""
from __future__ import annotations

import re

from .corpus import Passage, normalize


class GroundingError(Exception):
    pass


def verify_quote(passages: dict[str, Passage], doc_id: str, quote: str) -> None:
    p = passages.get(doc_id)
    if p is None:
        raise GroundingError(f"unknown source {doc_id}")
    if normalize(quote).lower() not in p.plain.lower():
        raise GroundingError(f"quote not found in {doc_id}: {quote[:60]!r}")


def find_support(passages: list[Passage], concept_groups: list[list[str]]) -> list[tuple[str, str]]:
    """Return (doc_id, sentence) pairs where one sentence matches every group."""
    hits = []
    pats = [re.compile(r"\b(" + "|".join(g) + r")", re.I) for g in concept_groups]
    for p in passages:
        for s in p.sentences:
            if all(pt.search(s) for pt in pats):
                hits.append((p.doc_id, s))
    return hits


_NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")


_LABELS = re.compile(r"\b(?:Tier|Rule|KB|BIL-POL)[- ]?\d+(?:\.\d+)?\b", re.I)   # names, not quantities


def _nums(text: str) -> set[float]:
    out = set()
    for m in _NUM.finditer(_LABELS.sub(" ", text)):
        try:
            out.add(round(float(m.group(0).lstrip("$").replace(",", "")), 2))
        except ValueError:
            pass
    return out


def unsupported_numbers(reply: str, evidence_texts: list[str]) -> set[float]:
    """Numbers stated in the reply that appear in none of the evidence (verified quotes,
    computed policy checks, parsed case facts). Ties the reply text to the checked claims."""
    allowed = set()
    for t in evidence_texts:
        allowed |= _nums(t)
    return _nums(reply) - allowed
