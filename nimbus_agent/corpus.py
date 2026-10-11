"""Load the policy document and KB excerpt into citable passages.

Each passage keeps its exact source text so every quote the agent emits can be
checked verbatim against it (see grounding.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
POLICY_FILE = DATA / "policy_BIL-POL-014.md"
KB_FILE = DATA / "kb_billing_credits.md"


@dataclass
class Passage:
    doc_id: str          # e.g. "BIL-POL-014 Rule 3" or "KB-1004"
    title: str
    kind: str            # "policy" | "kb"
    text: str            # raw markdown of the section
    sentences: list[str] = field(default_factory=list)

    @property
    def plain(self) -> str:
        return normalize(self.text)


def normalize(s: str) -> str:
    """Strip markdown emphasis/code marks and collapse whitespace."""
    s = re.sub(r"[*`>]", "", s)
    s = s.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


def _sentences(text: str) -> list[str]:
    plain = normalize(text)
    parts = re.split(r"(?<=[.!?:])\s+(?=[A-Z0-9(\-])", plain)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def load_policy(path: Path = POLICY_FILE) -> list[Passage]:
    raw = path.read_text(encoding="utf-8")
    out = []
    preamble = raw.split("## Rule 1")[0]
    m = re.search(r"> (.+)", preamble)
    if m:
        out.append(Passage("BIL-POL-014 Preamble", "Policy precedence note", "policy", m.group(1),
                           _sentences(m.group(1))))
    for m in re.finditer(r"## Rule (\d+) — (.+?)\n(.*?)(?=\n## Rule |\Z)", raw, re.S):
        num, title, body = m.group(1), m.group(2).strip(), m.group(3).strip().strip("-").strip()
        out.append(Passage(f"BIL-POL-014 Rule {num}", title, "policy", body, _sentences(body)))
    return out


def load_kb(path: Path = KB_FILE) -> list[Passage]:
    raw = path.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"### (KB-\d+) — (.+?)\n(.*?)(?=\n### KB-|\Z)", raw, re.S):
        kid, title, body = m.group(1), m.group(2).strip(), m.group(3).strip().strip("-").strip()
        out.append(Passage(kid, title, "kb", body, _sentences(body)))
    return out


def load_all() -> list[Passage]:
    return load_policy() + load_kb()


def by_id(passages: list[Passage]) -> dict[str, Passage]:
    return {p.doc_id: p for p in passages}
