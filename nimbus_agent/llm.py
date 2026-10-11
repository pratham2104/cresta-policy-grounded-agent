"""Optional OpenAI intent labeller (stdlib urllib, no SDK).

Enabled with --llm and OPENAI_API_KEY. Labels go into a closed set; any error,
timeout or out-of-set answer returns None and the rule labeller is used.
Token usage is accumulated so runs can report cost.
"""
from __future__ import annotations

import json
import re
import os
import urllib.request

from .intents import INTENTS


class IntentLLM:
    def __init__(self, model: str | None = None):
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "failures": 0}

    def label(self, question: str) -> str | None:
        menu = "\n".join(f"- {k}: {v}" for k, v in INTENTS.items())
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Classify the customer's billing-support question into exactly one intent. "
                 "Reply as JSON {\"intent\": \"<NAME>\"}. Intents:\n" + menu},
                {"role": "user", "content": question},
            ],
        }
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            self.usage["calls"] += 1
            u = data.get("usage", {})
            self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            self.usage["completion_tokens"] += u.get("completion_tokens", 0)
            intent = json.loads(data["choices"][0]["message"]["content"]).get("intent", "")
            return intent if intent in INTENTS else "UNKNOWN"
        except Exception:
            self.usage["failures"] += 1
            return None

    # ------------------------------------------------------------------
    def rewrite(self, question: str, reply: str) -> str | None:
        """Reword a grounded reply for tone. Accepted only if every money amount, date,
        ticket/case ID and number in the original survives unchanged and no new ones appear."""
        body = {
            "model": self.model, "temperature": 0,
            "messages": [
                {"role": "system", "content": "Rewrite the support agent's reply so it reads warmly and clearly for a customer in chat. "
                 "Do NOT add, remove or change any facts, amounts, dates, ticket numbers, policies or promises. "
                 "Keep it about the same length. Return only the rewritten reply."},
                {"role": "user", "content": f"Customer asked: {question}\n\nReply to rewrite:\n{reply}"},
            ],
        }
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            self.usage["calls"] += 1
            u = data.get("usage", {})
            self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            self.usage["completion_tokens"] += u.get("completion_tokens", 0)
            new = data["choices"][0]["message"]["content"].strip()
        except Exception:
            self.usage["failures"] += 1
            return None
        if facts_preserved(reply, new):
            return new
        self.usage["rewrites_rejected"] = self.usage.get("rewrites_rejected", 0) + 1
        return None


_NUM_WORDS = ("zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
              "seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
              "half|twice|double|triple|dozen|first|second|third|fourth|fifth")
_FACT_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?|\b(?:OUT|BDC)-[#\d]+|\b\d+(?:\.\d+)?\b|"
                      r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b|"
                      rf"\b(?:{_NUM_WORDS})\b", re.I)


def facts_preserved(original: str, rewritten: str) -> bool:
    """Same amounts / IDs / numbers / month names, in the same ORDER, in both texts.
    Order matters: swapping "$75" and "$82.50" keeps the multiset but flips the meaning."""
    norm = lambda s: [m.group(0).lower().replace(",", "") for m in _FACT_RE.finditer(s)]
    neg = lambda s: len(_NEG_RE.findall(s))
    return bool(rewritten) and norm(original) == norm(rewritten) and neg(original) == neg(rewritten)


# negation count must match too: "doesn't apply" -> "applies" keeps every number but flips the meaning
_NEG_RE = re.compile(r"\b(?:not|no|never|none|nothing|cannot|without)\b|n't\b", re.I)
