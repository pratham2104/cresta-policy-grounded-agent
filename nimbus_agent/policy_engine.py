"""Deterministic policy layer for BIL-POL-014.

Order of operations is the point of this module (incident #1 was a model that
checked the $75 ceiling before deciding which rule governed):

  1. Decide the governing track: the specific exception (Rule 3) is tested
     first; only if one of its gates fails does the request fall to Rule 2.
  2. Compute the credit under that track only (no blending of rules).
  3. Apply ONLY that track's escalation thresholds (Rule 4a for Rule 2,
     Rule 4b for Rule 3).
  4. Apply Rule 4c/4d + Rule 5 (repeat dispute / fraud) to every track.
     Unknown account history is reported as unverified, not assumed clean.

Every check declares (a) the evidence need it must be grounded in, as a
retrieval query, and (b) the exact quote it relies on. The workflow retrieves
for each need and only accepts the citation if retrieval actually returned
that source and the quote verifies verbatim (see workflow._gate).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .conversation import CaseFacts

GENERAL_LIMIT = 75.00
OUTAGE_ESCALATE_AMOUNT = 300.00
OUTAGE_ESCALATE_DAYS = 30
OUTAGE_MIN_HOURS = 4
OUTAGE_REQUEST_WINDOW_DAYS = 30
DISPUTE_WINDOW_DAYS = 60


@dataclass
class Check:
    name: str
    result: str               # "pass" | "fail" | "unverified" | "info"
    detail: str
    cite: tuple[str, str]     # (doc_id, exact quote)
    need: str = ""            # retrieval query describing the evidence this check needs


@dataclass
class PolicyDecision:
    governing_rule: str | None                # "BIL-POL-014 Rule 3" | "BIL-POL-014 Rule 2" | None (cannot decide)
    track: str                                # "service_outage_credit" | "general_goodwill" | "undetermined"
    credit_amount: float | None
    full_days: int | None
    escalate: bool
    escalation_reasons: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)   # must be confirmed before issuing
    missing_facts: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    request_deadline: date | None = None
    rejected_rules: list[tuple[str, str]] = field(default_factory=list)  # (rule, why it does not govern)


def _calendar_days(outage) -> int:
    """Whole calendar days with no service at all (start day and end day excluded if partial)."""
    start, end = outage
    first = start.date() if start.time() == datetime.min.time() else start.date() + timedelta(days=1)
    return max(0, (end.date() - first).days)


def evaluate(facts: CaseFacts, request_date: date | None = None) -> PolicyDecision:
    request_date = request_date or facts.conversation_date
    checks: list[Check] = []
    missing: list[str] = []
    window_ok = True
    if request_date is None:
        missing.append("request date (transcript has no date)")
    if facts.monthly_recurring_charge is None:
        missing.append("monthly recurring charge")
    if (facts.customer_reported_outage or facts.customer_mentions_outage) and not facts.noc_lookup_done:
        # Choosing Rule 3 vs Rule 2 depends on the NOC lookup; answering before it is incident #1.
        missing.append("NOC outage ticket lookup for the service address and dates (KB-1005 step 2) - "
                       "needed before deciding between the outage-credit policy and the general goodwill policy")

    # ---- Rule 1: dispute window (applies to every dispute) -------------------
    if facts.statement_date and request_date:
        dl = facts.statement_date + timedelta(days=DISPUTE_WINDOW_DAYS)
        window_ok = request_date <= dl
        checks.append(Check("dispute_window_60d", "pass" if window_ok else "fail",
                            f"statement {facts.statement_date}, window closes {dl}",
                            ("BIL-POL-014 Rule 1", "within 60 calendar days of the statement date"),
                            "billing dispute eligibility window 60 days statement date"))
    if facts.disputed_item:
        checks.append(Check("specific_line_item", "pass", f"disputed item: {facts.disputed_item}",
                            ("BIL-POL-014 Rule 1", "The dispute must identify the specific line item or charge being contested"),
                            "dispute must identify specific line item charge"))

    # ---- Step 1: does the specific exception (Rule 3) govern? ----------------
    gates_ok = True
    outage = facts.noc_outage
    hours = None
    if facts.noc_ticket and not outage:
        # Ticket exists but its duration can't be established -> stays on the outage track, Rule 4b escalation.
        gates_ok = False
        checks.append(Check("noc_ticket_verifiable", "fail", f"{facts.noc_ticket}: {facts.noc_unverifiable}",
                            ("BIL-POL-014 Rule 4", "or the NOC ticket number cannot be verified at the time of the request."),
                            "Service-Outage Credit escalate Tier 2 NOC ticket number cannot be verified at time of request"))
    elif not facts.noc_ticket or not outage:
        gates_ok = False
        checks.append(Check("noc_ticket_exists", "fail", "no NOC outage ticket found for address/dates",
                            ("KB-1005", "If no ticket exists, the outage cannot be verified under this policy - route to KB-1002 instead."),
                            "no NOC outage ticket exists cannot be verified route"))
    else:
        checks.append(Check("noc_ticket_exists", "pass", f"{facts.noc_ticket} covers {outage[0]} -> {outage[1]}",
                            ("BIL-POL-014 Rule 3", "A valid NOC outage ticket number exists covering the customer's service address and the dates in question."),
                            "valid NOC outage ticket number covering service address dates"))
        hours = (outage[1] - outage[0]).total_seconds() / 3600
        ok = hours > OUTAGE_MIN_HOURS
        gates_ok &= ok
        checks.append(Check("outage_over_4h", "pass" if ok else "fail", f"{hours:.0f} consecutive hours on ticket",
                            ("BIL-POL-014 Rule 3", "The outage duration recorded on the NOC ticket exceeds 4 consecutive hours."),
                            "outage duration recorded NOC ticket exceeds 4 consecutive hours"))
        resolved = outage[1].date()
        deadline = resolved + timedelta(days=OUTAGE_REQUEST_WINDOW_DAYS)
        if request_date is None:
            gates_ok = False
            checks.append(Check("requested_within_30d_of_resolution", "unverified", f"resolved {resolved}, request date unknown",
                                ("BIL-POL-014 Rule 3", "The customer requests the credit within 30 calendar days of the outage's resolution date (not the billing statement date)."),
                                "customer requests credit within 30 calendar days outage resolution date"))
        else:
            ok = request_date <= deadline
            gates_ok &= ok
            checks.append(Check("requested_within_30d_of_resolution", "pass" if ok else "fail",
                                f"resolved {resolved}, requested {request_date}, deadline {deadline}",
                                ("BIL-POL-014 Rule 3", "The customer requests the credit within 30 calendar days of the outage's resolution date (not the billing statement date)."),
                                "customer requests credit within 30 calendar days outage resolution date"))

    if missing:
        # Cannot decide the governing track without these; never fall through to Rule 2 silently.
        d = PolicyDecision(None, "undetermined", None, None, False, missing_facts=missing)
        d.checks = checks
        return d

    if facts.noc_ticket and not outage:
        d = PolicyDecision("BIL-POL-014 Rule 3", "service_outage_credit", None, None, True,
                           escalation_reasons=[f"Rule 4b: NOC ticket {facts.noc_ticket} cannot be verified ({facts.noc_unverifiable})"])
        d.rejected_rules.append(("BIL-POL-014 Rule 2", "a NOC ticket exists, so the outage track applies; an unverifiable ticket escalates under Rule 4b, it does not fall back to the $75 rule"))
    elif gates_ok:
        full_days = math.floor(hours / 24)
        credit = round(facts.monthly_recurring_charge / 30 * full_days, 2)
        d = PolicyDecision("BIL-POL-014 Rule 3", "service_outage_credit", credit, full_days, False,
                           request_deadline=outage[1].date() + timedelta(days=OUTAGE_REQUEST_WINDOW_DAYS))
        cro = facts.customer_reported_outage
        if cro and (abs((cro[0] - outage[0]).total_seconds()) > 86400 or abs((cro[1] - outage[1]).total_seconds()) > 86400):
            d.conditions.append(f"Customer-reported outage ({cro[0]:%b %d %H:%M} - {cro[1]:%b %d %H:%M}) differs from NOC ticket by "
                                "more than a day - credit uses the NOC ticket (Rule 3); confirm with the customer.")
        d.conditions.append(f"'Full days' counted as complete 24-hour periods on the NOC ticket ({hours:.0f} h -> {full_days}). "
                            f"Counting only whole calendar days fully without service would give "
                            f"{_calendar_days(outage)} (= ${facts.monthly_recurring_charge / 30 * _calendar_days(outage):.2f}); "
                            "the policy does not define it - confirm Billing Ops convention.")
        checks.append(Check("credit_formula", "info",
                            f"${facts.monthly_recurring_charge:.2f} / 30 x {full_days} full days = ${credit:.2f}",
                            ("BIL-POL-014 Rule 3", "Service-Outage Credit = (current monthly recurring charge ÷ 30) × number of full days the account was without service"),
                            "service outage credit calculation monthly recurring charge divided 30 full days without service"))
        checks.append(Check("not_capped_by_general_75", "info",
                            f"${credit:.2f} exceeds $75.00 but Rule 2's ceiling does not apply to this track",
                            ("BIL-POL-014 Rule 3", "is not counted against, and not capped by, the $75.00 General Refund/Goodwill Credit Limit"),
                            "outage credit not counted against not capped by $75.00 general goodwill limit"))
        d.rejected_rules.append(("BIL-POL-014 Rule 2", "more specific Rule 3 governs; Rule 2's $75 ceiling must not be blended in (Rule 3, Rule 4 note, KB-1006)"))
        # Rule 4b — ONLY the outage-track thresholds
        if credit > OUTAGE_ESCALATE_AMOUNT:
            d.escalation_reasons.append(f"Rule 4b: outage credit ${credit:.2f} > $300.00")
        if hours / 24 > OUTAGE_ESCALATE_DAYS:
            d.escalation_reasons.append(f"Rule 4b: outage {hours/24:.1f} days > 30 consecutive days")
        checks.append(Check("rule_4b_thresholds", "fail" if d.escalation_reasons else "pass",
                            f"credit ${credit:.2f} vs $300.00; outage {hours/24:.1f} days vs 30",
                            ("BIL-POL-014 Rule 4", "A Service-Outage Credit only needs escalation if it independently meets condition (b)."),
                            "service outage credit escalation exceeds $300.00 30 consecutive days condition b"))
    else:
        # ---- Fallback: Rule 2 general goodwill -----------------------------------
        d = PolicyDecision("BIL-POL-014 Rule 2", "general_goodwill", None, None, False)
        d.rejected_rules.append(("BIL-POL-014 Rule 3", "one or more Rule 3 qualification gates failed (see checks)"))
        checks.append(Check("fallback_to_rule_2", "info", "Rule 3 gates not all met -> evaluate as general goodwill",
                            ("BIL-POL-014 Rule 3", "should instead be evaluated under Rule 2 as a general goodwill request, subject to the $75.00 ceiling and Rule 4 escalation."),
                            "condition not met request does not qualify evaluated under Rule 2 general goodwill"))
        requested = facts.monthly_recurring_charge
        prior = facts.goodwill_credits_last_12m
        if prior is None:
            d.conditions.append("Rolling 12-month goodwill total unknown - check account credit history before quoting (KB-1002).")
            if requested > GENERAL_LIMIT:
                d.escalation_reasons.append(f"Rule 4a: requested ${requested:.2f} alone exceeds the $75.00 rolling ceiling")
        elif prior + requested > GENERAL_LIMIT:
            d.escalation_reasons.append(f"Rule 4a: ${prior:.2f} prior + ${requested:.2f} > $75.00")
        d.credit_amount = min(requested, max(0.0, GENERAL_LIMIT - (prior or 0.0)))
        checks.append(Check("rule_4a_threshold", "fail" if d.escalation_reasons else "pass",
                            "general goodwill ceiling $75.00 per rolling 12 months",
                            ("BIL-POL-014 Rule 2", "up to $75.00 per account, per rolling 12-month period"),
                            "general refund goodwill credit limit $75.00 per account rolling 12-month period"))

    # ---- Rule 1: late dispute needs Tier 2 sign-off on every track -------------
    if facts.statement_date and request_date and not window_ok:
        d.escalation_reasons.append("Rule 1: dispute filed after the 60-day statement window - Tier 2 sign-off required")

    # ---- Rule 4c/4d + Rule 5 apply on every track ------------------------------
    rule5 = ("BIL-POL-014 Rule 5", "must have the credit decision made by a Tier 2 Billing Specialist, not the front-line agent, even if the dollar amount is small.")
    rule5_need = "repeat dispute 90 days prior resolved dispute fraud Tier 2 Billing Specialist"
    if facts.prior_resolved_dispute_within_90d is None:
        d.conditions.append("Repeat-dispute check UNVERIFIED: transcript has no account dispute history. If a resolved dispute exists in the prior 90 days, Tier 2 must decide (Rule 4c / Rule 5).")
        checks.append(Check("repeat_dispute_90d", "unverified", "no dispute history in the provided evidence", rule5, rule5_need))
    elif facts.prior_resolved_dispute_within_90d:
        d.escalation_reasons.append("Rule 4c / Rule 5: second dispute within 90 days of a prior resolved dispute")
        checks.append(Check("repeat_dispute_90d", "fail", "prior resolved dispute within 90 days", rule5, rule5_need))
    if facts.fraud_indicators is None:
        d.conditions.append("Fraud-indicator check UNVERIFIED: no fraud flags in provided evidence (Rule 4d / Rule 5).")
        checks.append(Check("fraud_indicators", "unverified", "no fraud review data in the provided evidence", rule5, rule5_need))
    elif facts.fraud_indicators:
        d.escalation_reasons.append("Rule 4d / Rule 5: fraud indicators present")
        checks.append(Check("fraud_indicators", "fail", "fraud indicators present", rule5, rule5_need))

    d.escalate = bool(d.escalation_reasons)
    d.checks = checks
    return d
