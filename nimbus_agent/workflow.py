"""The agent workflow: per customer turn -> questions -> evidence -> decision -> reply.

Pipeline per question
  1. retrieve   hop 0: BM25 on the question (+ known case context)
  2. decide     policy_engine.evaluate() on the facts known *at that turn*
  3. support    answerability check (grounding.find_support) for questions the
                policy engine does not itself decide (e.g. tax treatment)
  4. ground     every claim declares an evidence need; a retrieval hop runs that
                need as a query and the claim is accepted only if (a) retrieval
                returned the cited source in its top-k and (b) the quote is a
                verbatim substring of it. Any failure => the reply is withheld
                and the turn escalates.
  5. compose    reply built only from accepted claims (optional LLM rewording,
                rejected if it changes any amount, date or ticket, or adds numbers)

Decisions: ANSWER | ANSWER_WITH_CONDITIONS | PARTIAL_ANSWER_ESCALATE |
           ESCALATE | GATHER_INFO | NO_POLICY_QUESTION
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path

from . import corpus, intents
from .conversation import parse_text, prefix_through, CaseFacts
from .grounding import verify_quote, find_support, GroundingError, unsupported_numbers
from .policy_engine import evaluate, PolicyDecision
from .retrieval import BM25

HOP_K = 3          # a cited source must rank in the top-3 for its own evidence need
QUESTION_K = 4     # hop-0 retrieval depth shown per question
CUSTOMER_FACING = {"ANSWER", "ANSWER_WITH_CONDITIONS", "PARTIAL_ANSWER_ESCALATE"}


def _customer_reasons(reasons: list[str]) -> str:
    """Escalation reasons in customer language (internal rule ids stay in the trace)."""
    out = []
    for x in reasons:
        if "Rule 1" in x:
            out.append("the dispute was raised more than 60 days after the statement date")
        elif "> $300.00" in x:
            out.append("the credit is above the $300.00 amount I can apply myself")
        elif "30 consecutive days" in x:
            out.append("the outage lasted longer than 30 days")
        elif "4c" in x or "repeat" in x.lower():
            out.append("there's a recent prior dispute on the account")
        elif "fraud" in x.lower():
            out.append("the account needs a standard security review")
        else:
            out.append("this needs a specialist's sign-off")
    return " and ".join(dict.fromkeys(out))


def _short_q(q: str, n: int = 100) -> str:
    """The question part of a turn (drops identity details before a dash), truncated."""
    import re as _re
    q = _re.split(r"\s[-\u2014]\s", q)[-1].strip()
    return q if len(q) <= n else q[:n - 1] + "\u2026"


def fmt_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"       # portable (no %-d)


def _money(x: float) -> str:
    return f"${x:,.2f}"


@dataclass
class Claim:
    text: str
    doc_id: str
    quote: str
    need: str
    retrieved_rank: int | None = None   # rank of doc_id in the hop for `need` (1-based); None = not retrieved
    verified: bool = False


@dataclass
class QuestionResult:
    turn_time: str
    question: str
    intent: str
    labeled_by: str
    retrieval_query: str
    retrieved: list[dict]
    governing_policy: str | None
    primary_source: str | None
    driving_articles: list[str]
    decision: str
    reply: str
    reply_rewritten_by: str = "template"
    claims: list[Claim] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    policy_checks: list[dict] = field(default_factory=list)
    rejected_rules: list[list[str]] = field(default_factory=list)
    retrieval_metrics: dict = field(default_factory=dict)


class Workflow:
    def __init__(self, llm=None, passages=None):
        self.passages = passages if passages is not None else corpus.load_all()
        self.by_id = corpus.by_id(self.passages)
        self.bm25 = BM25(self.passages)
        self.llm = llm

    # ------------------------------------------------------------------ run
    def run(self, transcript_path: str | Path) -> dict:
        raw = Path(transcript_path).read_text(encoding="utf-8")
        final_facts, turns = parse_text(raw)
        results: list[QuestionResult] = []
        for t in turns:
            if t.speaker != "customer":
                continue
            facts, _ = parse_text(prefix_through(raw, t))
            for q in intents.extract(t.time, t.text, self.llm):
                results.append(self._handle(q, facts))
        cited = [r.retrieval_metrics for r in results if r.retrieval_metrics]
        summary = {
            "questions": len(results),
            "decisions": {d: sum(r.decision == d for r in results) for d in sorted({r.decision for r in results})},
            "claims": sum(len(r.claims) for r in results),
            "claims_verified": sum(c.verified for r in results for c in r.claims),
            "single_shot_retrieval_recall": round(sum(m["single_shot_recall"] for m in cited) / len(cited), 3) if cited else None,
            "multi_hop_retrieval_recall": round(sum(m["hop_recall"] for m in cited) / len(cited), 3) if cited else None,
        }
        return {
            "transcript": str(transcript_path),
            "facts_at_end": final_facts.to_json(),
            "summary": summary,
            "turns": [asdict(r) for r in results],
            "consolidated_follow_up": self._consolidate(results),
        }

    # -------------------------------------------------------------- per question
    def _handle(self, q: intents.Question, facts: CaseFacts) -> QuestionResult:
        self._facts_json = facts.to_json()
        context = " service outage credit NOC" if (facts.noc_ticket or facts.customer_reported_outage) else ""
        query = q.text + context
        hits = self.bm25.search(query, k=QUESTION_K)
        r = QuestionResult(q.turn_time, q.text, q.intent, q.labeled_by, query,
                           [{"doc_id": p.doc_id, "title": p.title, "score": s} for p, s in hits],
                           None, None, [], "ESCALATE", "")
        handler = getattr(self, "_q_" + q.intent.lower(), self._q_unknown)
        handler(r, facts)
        self._gate(r)
        # LLM rewording never touches money or deadline answers - those stay exactly as the engine computed them.
        if (self.llm is not None and r.decision in CUSTOMER_FACING and hasattr(self.llm, "rewrite")
                and r.intent not in ("CREDIT_AMOUNT_OR_LIMIT", "REQUEST_DEADLINE")):
            new = self.llm.rewrite(r.question, r.reply)
            if new:
                r.reply, r.reply_rewritten_by = new, "llm(guarded)"
        used = {c.doc_id for c in r.claims if c.verified}
        for h in r.retrieved:
            h["used_in_reply"] = h["doc_id"] in used
        return r

    def _cite(self, r: QuestionResult, text: str, doc_id: str, quote: str, need: str) -> None:
        r.claims.append(Claim(text, doc_id, quote, need))

    def _gate(self, r: QuestionResult) -> None:
        hop0 = {h["doc_id"] for h in r.retrieved}
        for c in r.claims:
            ranked = [p.doc_id for p, _ in self.bm25.search(c.need, k=HOP_K)]
            c.retrieved_rank = ranked.index(c.doc_id) + 1 if c.doc_id in ranked else None
            try:
                if c.retrieved_rank is None:
                    raise GroundingError(f"{c.doc_id} not retrieved in top-{HOP_K} for evidence need {c.need!r} (got {ranked})")
                verify_quote(self.by_id, c.doc_id, c.quote)
                c.verified = True
            except GroundingError as e:
                c.verified = False
                r.unsupported.append(f"claim rejected: {e}")
        if r.decision in CUSTOMER_FACING:
            f = self._facts_json
            facts_used = [str(f.get(k)) for k in ("monthly_recurring_charge", "noc_ticket", "noc_outage", "statement_date",
                                                  "conversation_date") if f.get(k)]
            evidence = [c.quote for c in r.claims if c.verified] + [ch["detail"] for ch in r.policy_checks] + facts_used
            bad = unsupported_numbers(r.reply, evidence)
            if bad:
                r.unsupported.append(f"reply states numbers not found in any verified evidence: {sorted(bad)}")
                r.claims.append(Claim("[reply numbers]", "-", "-", "-", None, False))
        if any(not c.verified for c in r.claims):
            r.decision = "ESCALATE"
            r.reply = ("I want to make sure I give you an accurate answer, so I'm passing this to a Tier 2 "
                       "Billing Specialist to confirm before I commit to anything.")
        cited = {c.doc_id for c in r.claims if c.verified}
        r.driving_articles = sorted(cited)
        if r.primary_source and r.primary_source not in cited:
            r.primary_source = None
        if cited:
            r.retrieval_metrics = {
                "cited_sources": sorted(cited),
                # share of cited sources that one query on the question alone would have surfaced
                "single_shot_recall": round(len(cited & hop0) / len(cited), 3),
                # share surfaced by the per-claim evidence-need hops (accepted claims only, so 1.0 unless rejected)
                "hop_recall": round(len({c.doc_id for c in r.claims if c.retrieved_rank}) / len({c.doc_id for c in r.claims}), 3),
            }

    def _attach_policy(self, r: QuestionResult, d: PolicyDecision) -> None:
        r.governing_policy = d.governing_rule
        r.conditions = list(d.conditions)
        r.policy_checks = [{"check": c.name, "result": c.result, "detail": c.detail, "source": c.cite[0]} for c in d.checks]
        r.rejected_rules = [list(x) for x in d.rejected_rules]
        for c in d.checks:                       # every policy check must itself be grounded
            self._cite(r, f"[check] {c.name}", c.cite[0], c.cite[1], c.need)

    def _missing(self, r: QuestionResult, d: PolicyDecision) -> bool:
        if d.governing_rule is not None:
            return False
        r.decision = "GATHER_INFO"
        r.conditions = list(d.missing_facts)
        if any("NOC" in m for m in d.missing_facts):
            r.primary_source = "KB-1005"
            r.reply = ("I don't want to quote you a limit or a deadline yet: which policy applies depends on whether our "
                       "network team has a confirmed outage ticket for your address and dates. Let me check the outage "
                       "records first, then I'll give you the exact amount and deadline.")
            self._cite(r, "NOC lookup first", "KB-1005",
                       "Look up the NOC outage ticket (format: OUT-#####) covering that address and date range.",
                       "request service outage credit look up NOC outage ticket covering address date range")
            self._cite(r, "policy first", "KB-1001", "Determine which policy governs the disputed charge",
                       "file billing dispute determine which policy governs disputed charge before calculating credit")
        else:
            r.primary_source = "KB-1001"
            r.reply = "Before I can say which policy applies, I need: " + "; ".join(d.missing_facts) + "."
            self._cite(r, "policy first", "KB-1001", "Determine which policy governs the disputed charge",
                       "file billing dispute determine which policy governs disputed charge before calculating credit")
        return True

    # ---------------------------------------------------------------- handlers
    def _q_identity_info(self, r, facts):
        r.decision = "NO_POLICY_QUESTION"
        r.primary_source = "KB-1001"
        r.reply = "(No policy question. Identity details captured for verification per KB-1001 step 1.)"
        self._cite(r, "Verify identity before acting", "KB-1001",
                   "Confirm the account holder's identity (name, account number, and either the last 4 digits of the payment method on file or the account PIN).",
                   "confirm account holder identity account number last 4 digits payment method PIN")

    def _q_dispute_request(self, r, facts):
        r.decision = "GATHER_INFO"
        need = []
        if not facts.identity_verified:
            need.append("verify identity (KB-1001 step 1)")
            self._cite(r, "verify identity", "KB-1001", "Confirm the account holder's identity",
                       "confirm account holder identity account number payment method PIN")
        if not facts.disputed_item:
            need.append("identify the specific disputed line item (KB-1001 step 2)")
            self._cite(r, "specific line item", "KB-1001", "Identify the exact line item being disputed",
                       "file billing dispute identify exact line item being disputed")
        if facts.customer_reported_outage and not facts.noc_ticket:
            need.append("look up the NOC outage ticket for the service address and dates (KB-1005 step 2)")
            self._cite(r, "NOC lookup", "KB-1005", "Look up the NOC outage ticket (format: OUT-#####) covering that address and date range.",
                       "request service outage credit look up NOC outage ticket covering address date range")
        if not need:
            need.append("determine which policy governs before calculating any credit (KB-1001 step 4)")
            self._cite(r, "policy first", "KB-1001", "Determine which policy governs the disputed charge",
                       "file billing dispute determine which policy governs disputed charge before calculating credit")
        r.primary_source = r.claims[-1].doc_id
        r.reply = "Next step for the agent: " + "; ".join(need) + ". Do not quote any credit amount yet."

    def _q_credit_amount_or_limit(self, r, facts):
        if not (facts.noc_ticket or facts.customer_reported_outage or facts.disputed_item):
            r.decision = "GATHER_INFO"
            r.primary_source = "KB-1001"
            r.reply = "I need the disputed charge and account details before I can say which policy applies."
            self._cite(r, "policy first", "KB-1001", "Determine which policy governs the disputed charge",
                       "file billing dispute determine which policy governs disputed charge before calculating credit")
            return
        d = evaluate(facts)
        if self._missing(r, d):
            return
        self._attach_policy(r, d)
        if d.track == "service_outage_credit":
            r.primary_source = "KB-1004"
            self._cite(r, "outage credit is a separate track", "KB-1004",
                       "is issued separately from, and is not limited by, the standard $75.00 goodwill credit ceiling described in KB-1002",
                       "service-outage credit issued separately not limited by standard $75.00 goodwill credit ceiling")
            self._cite(r, "$75 does not trigger escalation for outage credits", "KB-1006",
                       "A Service-Outage Credit above $75.00 does not by itself require escalation",
                       "escalate billing request Tier 2 service-outage credit above $75.00 does not by itself require escalation")
            if d.credit_amount is None:          # ticket on file but not verifiable (Rule 4b)
                r.decision = "ESCALATE"
                r.reply = (f"I can see outage ticket {facts.noc_ticket} on file, but I can't confirm its exact start and end "
                           "times right now, so I won't estimate an amount. This goes under our Service-Outage Credit policy "
                           "(not the $75 goodwill limit), and a Tier 2 Billing Specialist will confirm the credit.")
                return
            if d.escalate:
                r.decision = "ESCALATE"
                r.reply = (f"Your outage qualifies under our Service-Outage Credit policy, calculated at {_money(d.credit_amount)} "
                           f"for {d.full_days} full days. Because {_customer_reasons(d.escalation_reasons)}, a Tier 2 Billing "
                           "Specialist must approve it before it is applied. I'm sending it to them now.")
                return
            if d.full_days == 0:
                r.decision = "ESCALATE"
                r.reply = ("Your outage is confirmed and qualifies under our Service-Outage Credit policy, but that credit is "
                           "calculated per full day without service and this outage was shorter than one full day, so the "
                           "formula gives $0.00. The policy doesn't cover partial days, so I'm asking a Tier 2 Billing "
                           "Specialist to review rather than tell you zero.")
                return
            r.decision = "ANSWER_WITH_CONDITIONS" if d.conditions else "ANSWER"
            r.reply = (f"The $75 limit you saw is our general goodwill limit, and it doesn't apply here. Because NOC ticket "
                       f"{facts.noc_ticket} confirms your outage, you qualify for a Service-Outage Credit, which is a separate "
                       f"policy and isn't capped at $75. It's calculated as your {_money(facts.monthly_recurring_charge)} monthly "
                       f"charge / 30 x {d.full_days} full days without service = {_money(d.credit_amount)} (the credit covers the days "
                       f"you were without service, not the whole month). That's within what can be applied at the front line "
                       f"(outage credits only need specialist approval above $300 or for outages longer than 30 days)"
                       + ("; I'll apply it once I've completed the standard account-history check." if d.conditions else "."))
            self._cite(r, "Tier-2 threshold for outage credits", "KB-1005",
                       "If the calculated credit is $300.00 or less and the outage lasted 30 days or fewer, the agent may apply the credit directly.",
                       "calculated credit $300.00 or less outage lasted 30 days or fewer agent may apply credit directly")
        else:
            r.primary_source = "KB-1002"
            r.decision = "ESCALATE" if d.escalate else "ANSWER_WITH_CONDITIONS"
            why = ""
            if facts.noc_outage:
                closed = facts.noc_outage[1].date() + timedelta(days=30)
                why = (f"Your outage is confirmed, but outage-credit requests must be made within 30 days of the outage being "
                       f"resolved, and that window closed on {fmt_date(closed)}. ")
                self._cite(r, "outage window", "BIL-POL-014 Rule 3",
                           "The customer requests the credit within 30 calendar days of the outage's resolution date (not the billing statement date).",
                           "customer requests credit within 30 calendar days outage resolution date")
            elif facts.noc_lookup_done and not facts.noc_ticket:
                why = "Our network records don't show a confirmed outage ticket for your address and dates, so the outage-credit policy can't be used. "
                self._cite(r, "no ticket", "KB-1005", "If no ticket exists, the outage cannot be verified under this policy - route to KB-1002 instead.",
                           "no NOC outage ticket exists cannot be verified route")
            r.reply = why + ("This falls under our general goodwill credit policy, which is capped at $75.00 per account per rolling "
                       "12 months. " + ("A Tier 2 Billing Specialist needs to approve anything above that before I can commit to it."
                                        if d.escalate else "I'll confirm your account's credit history before applying it."))
            self._cite(r, "general cap", "KB-1002", "up to $75.00 per account per rolling 12-month period",
                       "refund eligibility goodwill credit limits $75.00 per account rolling 12-month period")

    def _q_request_deadline(self, r, facts):
        d = evaluate(facts)
        if self._missing(r, d):
            return
        self._attach_policy(r, d)
        rule3_window = ("BIL-POL-014 Rule 3", "The customer requests the credit within 30 calendar days of the outage's resolution date (not the billing statement date).",
                        "customer requests credit within 30 calendar days outage resolution date")
        if d.track == "service_outage_credit" and d.request_deadline:
            r.decision = "ANSWER_WITH_CONDITIONS" if d.conditions else "ANSWER"
            r.primary_source = "KB-1005"
            res = facts.noc_outage[1].date()
            r.reply = (f"For an outage credit, the deadline is 30 days from the date the outage was resolved, not from your "
                       f"bill date. Your outage was resolved on {res:%B} {res.day}, so the request must be in by "
                       f"{fmt_date(d.request_deadline)}. Today's request is within that.")
            self._cite(r, "30 days from resolution", "KB-1005", "Confirm the customer is requesting within 30 days of the ticket's resolution date.",
                       "confirm customer requesting within 30 days of ticket resolution date")
            r.rejected_rules.append(["BIL-POL-014 Rule 1 (60 days from statement date)",
                                     "general dispute window; the outage-credit request deadline is the narrower Rule 3 condition"])
        elif d.track == "service_outage_credit":    # ticket exists, dates unverifiable
            r.decision = "PARTIAL_ANSWER_ESCALATE"
            r.primary_source = "BIL-POL-014 Rule 3"
            r.reply = ("Outage-credit requests must be made within 30 days of the date the outage was resolved (not your bill "
                       f"date). I can't confirm the resolution date on ticket {facts.noc_ticket} right now, so a Tier 2 Billing "
                       "Specialist will confirm your exact deadline.")
            self._cite(r, "30 days from resolution", *rule3_window)
        elif facts.noc_outage and facts.statement_date:   # outage confirmed but the 30-day window has passed
            res = facts.noc_outage[1].date()
            closed = res + timedelta(days=30)
            dl = facts.statement_date + timedelta(days=60)
            r.decision = "ANSWER_WITH_CONDITIONS"
            r.primary_source = "BIL-POL-014 Rule 3"
            r.reply = (f"The window for an outage credit closed on {fmt_date(closed)}, 30 days after your outage was resolved "
                       f"on {res:%B} {res.day}. You can still dispute the charge as a general billing dispute until "
                       f"{fmt_date(dl)} (60 days from your statement date), but that is handled under our general goodwill "
                       "policy, which is capped at $75 with specialist approval needed above that.")
            self._cite(r, "outage window", *rule3_window)
            self._cite(r, "60-day dispute window", "BIL-POL-014 Rule 1", "within 60 calendar days of the statement date",
                       "billing dispute eligibility window 60 calendar days statement date")
            self._cite(r, "general cap", "KB-1002", "up to $75.00 per account per rolling 12-month period",
                       "refund eligibility goodwill credit limits $75.00 per account rolling 12-month period")
        elif facts.statement_date:
            dl = facts.statement_date + timedelta(days=60)
            r.decision = "ANSWER"
            r.primary_source = "BIL-POL-014 Rule 1"
            r.reply = f"You can dispute a specific charge within 60 days of the statement date, so by {fmt_date(dl)}."
            self._cite(r, "60-day dispute window", "BIL-POL-014 Rule 1", "within 60 calendar days of the statement date",
                       "billing dispute eligibility window 60 calendar days statement date")
        else:
            r.decision = "GATHER_INFO"
            r.primary_source = "KB-1001"
            r.reply = "I need to know which charge and statement this is about before I can give you the exact deadline."
            self._cite(r, "line item", "KB-1001", "Identify the exact line item being disputed",
                       "file billing dispute identify exact line item being disputed")

    def _q_tax_treatment(self, r, facts):
        r.primary_source = "KB-1004"
        # What the evidence DOES say about the credit's base:
        self._cite(r, "outage credit base = recurring plan charge", "KB-1004",
                   "This credit applies to the recurring plan charge only",
                   "service-outage credit applies to recurring plan charge only")
        # Answerability: need one sentence that speaks about taxes/surcharges AND the outage credit together.
        support = find_support(self.passages, [["tax", "taxes", "surcharge"], ["outage"]])
        if support:
            doc, sent = support[0]
            r.decision = "ANSWER"
            r.reply = sent
            r.primary_source = doc
            self._cite(r, "tax treatment", doc, sent, sent)
            return
        r.governing_policy = "none - not covered by BIL-POL-014 or KB excerpt"
        r.decision = "PARTIAL_ANSWER_ESCALATE"
        r.unsupported.append("Whether taxes/regulatory surcharges billed during the outage are reduced or refunded: no policy "
                             "rule or KB article addresses it (KB-1003 describes how taxes are billed, not how credits affect them).")
        r.reply = ("What I can confirm: the outage credit is calculated on your recurring plan charge only. Whether the taxes "
                   "and regulatory surcharges from those days are also adjusted isn't something our billing guidance covers, so "
                   "I won't guess. I'm sending that part to a Tier 2 Billing Specialist, and you'll get a confirmed answer in "
                   "writing with your case number.")

    def _q_unknown(self, r, facts):
        r.decision = "ESCALATE"
        r.unsupported.append("question did not map to any policy-governed intent; retrieved passages are listed for the human reviewer only")
        r.reply = "I don't have verified guidance on that, so rather than guess I'm routing it to a specialist who can confirm."

    # ------------------------------------------------------------- follow-up
    def _consolidate(self, results: list[QuestionResult]) -> dict:
        latest = {}
        for r in results:
            if r.intent in ("CREDIT_AMOUNT_OR_LIMIT", "TAX_TREATMENT", "REQUEST_DEADLINE"):
                latest[r.intent] = r
        parts, conds = [], []
        for key, label in [("CREDIT_AMOUNT_OR_LIMIT", "Credit and policy"), ("TAX_TREATMENT", "Taxes and surcharges"),
                           ("REQUEST_DEADLINE", "Deadline")]:
            if key in latest:
                parts.append(f"{label}: {latest[key].reply}")
                conds += latest[key].conditions
        actions = ["Log the dispute in the Billing Case queue and obtain a case number (format BDC-######) - KB-1001 step 3; "
                   "the transcript contains none, so the reply leaves a placeholder rather than inventing one.",
                   "Send this resolution and the case number to the customer in writing - KB-1001 step 5."]
        others = [r for r in results if r.intent in ("UNKNOWN", "CREDIT_TIMING") or
                  (r.intent not in latest and r.decision == "ESCALATE")]
        if others:
            parts.append("Your other question" + ("s" if len(others) > 1 else "") + " (" +
                         "; ".join(f'"{_short_q(o.question)}"' for o in others) +
                         "): I don't have verified guidance on " + ("these" if len(others) > 1 else "that") +
                         ", so a specialist will follow up rather than me guessing.")
        if parts:
            parts.append("Case number: [BDC-###### - assigned when the dispute is logged]. You'll receive this summary in writing.")
        return {"reply_to_customer": "\n\n".join(parts),
                "agent_actions": actions,
                "agent_only_preconditions_before_issuing_credit": sorted(set(conds)),
                "escalations": [f"[{r.turn_time}] {r.intent}" for r in list(latest.values()) + others
                                if r.decision in ("ESCALATE", "PARTIAL_ANSWER_ESCALATE")]}
