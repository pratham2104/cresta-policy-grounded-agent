"""Split customer turns into policy questions and label each one.

Default: deterministic patterns (no key needed, reproducible).
Optional: --llm uses an OpenAI model to label questions into the SAME closed
set of intents; anything it returns outside the set is treated as UNKNOWN,
which the workflow escalates. The LLM never decides amounts or eligibility.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

INTENTS = {
    "TAX_TREATMENT": "whether a credit changes taxes / regulatory surcharges / government fees (911, USF)",
    "CREDIT_TIMING": "when a credit will be applied or show up on the bill",
    "REQUEST_DEADLINE": "how long the customer has to file / request",
    "CREDIT_AMOUNT_OR_LIMIT": "how much credit/refund, or what limit applies",
    "DISPUTE_REQUEST": "customer opens a dispute about a charge",
    "IDENTITY_INFO": "customer supplies verification details, no question",
    "UNKNOWN": "anything else (e.g. fee waivers, device questions) -> escalated, never answered",
}

# Patterns per intent. A sentence can carry more than one question ("is it only $75, and how long do I have?"),
# so every intent is tested; precedence rules below drop the incidental matches.
PATTERNS = {
    "UNKNOWN": r"\b(waive|late fees?|installments?|payment plan|upgrade|new phone|cancel(?:lation)?|autopay)\b",
    "TAX_TREATMENT": r"\b(tax|taxes|surcharges?|regulatory|911|universal service|USF|fees?)\b",
    "CREDIT_TIMING": r"\b(how long (will|would|does) it take|when (will|would|does|do|can) (i|it|the credit|that|this)\b.{0,30}"
                     r"\b(see|get|show|appear|post|hit|apply|applied|land)|show up|appear on|post to)",
    "REQUEST_DEADLINE": r"\b(how long do i (actually )?(have|get)|how long (have|do) i got|deadline|cut-?off|how many days do i|"
                        r"time limit|by when|last day to|too late|how long .{0,40}\b(submit|file|request|dispute|claim|ask))",
    "CREDIT_AMOUNT_OR_LIMIT": r"(\b(refund|credit|limit|cap|capped|money back|get back|reimburse\w*|compensat\w*|owed|"
                              r"how much|for the downtime|make (it|this) right)\b|\$\d)",
    "DISPUTE_REQUEST": r"\b(dispute|disputing|charged|overcharged)\b",
}
IDENTITY_RE = r"\b(account is|account number|card ending|last 4|pin is)\b"
PRIORITY = ["UNKNOWN", "TAX_TREATMENT", "CREDIT_TIMING", "REQUEST_DEADLINE", "CREDIT_AMOUNT_OR_LIMIT", "DISPUTE_REQUEST"]
# kept for backwards compatibility with callers that iterate rules in order
RULES = [(k, PATTERNS[k]) for k in PRIORITY]


@dataclass
class Question:
    turn_time: str
    text: str
    intent: str
    labeled_by: str   # "rules" | "llm"


def split_questions(text: str) -> list[str]:
    sents = re.split(r"(?<=[.?!])\s+", text)
    qs = [s for s in sents if s.endswith("?")]
    return qs or [text]


def label_all(text: str) -> list[str]:
    """All question intents in one sentence, after precedence rules:
    - out-of-scope requests (waive / installments / ...) are escalated, and also suppress the generic credit match
    - tax and credit-timing questions mention "credit" incidentally -> drop CREDIT_AMOUNT_OR_LIMIT
    - "late fee" is a waiver request, not a tax question
    - DISPUTE_REQUEST only stands alone (it is the opening statement, not a question)."""
    hits = [k for k in PRIORITY if re.search(PATTERNS[k], text, re.I)]
    if "UNKNOWN" in hits:
        hits = [h for h in hits if h not in ("CREDIT_AMOUNT_OR_LIMIT", "DISPUTE_REQUEST")]
        if re.search(r"\blate fees?\b", text, re.I):
            hits = [h for h in hits if h != "TAX_TREATMENT"]
    if "TAX_TREATMENT" in hits or "CREDIT_TIMING" in hits:
        hits = [h for h in hits if h != "CREDIT_AMOUNT_OR_LIMIT"]
    if "DISPUTE_REQUEST" in hits and "?" not in text:
        return ["DISPUTE_REQUEST"]          # an opening statement ("I was charged $225"), not a question
    if len(hits) > 1:
        hits = [h for h in hits if h != "DISPUTE_REQUEST"]
    if not hits:
        if re.search(IDENTITY_RE, text, re.I) and "?" not in text:
            return ["IDENTITY_INFO"]
        return ["UNKNOWN"]
    return hits


def label_rules(text: str) -> str:
    return label_all(text)[0]


def extract(turn_time: str, text: str, llm=None) -> list[Question]:
    out: list[Question] = []
    for q in split_questions(text):
        labels, by = label_all(q), "rules"
        # The LLM labels one intent per question; use it only when the rules see a single question,
        # so a compound question ("is it $75, and how long do I have?") never loses half.
        if llm is not None and len(labels) == 1:
            lab = llm.label(q)
            if lab:
                labels, by = [lab], "llm"
            else:
                by = "rules(fallback)"
        for intent in labels:
            prev = [x for x in out if x.intent == intent]
            if prev:                             # same question asked twice in one turn
                prev[0].text += " " + q
                continue
            out.append(Question(turn_time, q, intent, by))
    return out
