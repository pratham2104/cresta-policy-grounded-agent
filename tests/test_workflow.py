"""Regression tests for both incidents + perturbations that prove the workflow
is not hard-wired to the one provided transcript.

Run:  python3 -m unittest discover -s tests -v
Variants are built by editing the provided transcript text, so each test
exercises the full path: parse -> retrieve -> policy -> grounding -> reply.
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nimbus_agent.workflow import Workflow                      # noqa: E402
from nimbus_agent.conversation import parse_text                # noqa: E402
from nimbus_agent.policy_engine import evaluate                 # noqa: E402
from nimbus_agent.grounding import verify_quote, GroundingError  # noqa: E402
from nimbus_agent import corpus                                 # noqa: E402

BASE = (ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt").read_text(encoding="utf-8")
WF = Workflow()


def run_variant(text: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
    return WF.run(f.name)


def turn(trace, intent):
    return [t for t in trace["turns"] if t["intent"] == intent][-1]


class Incident1_NarrowExceptionGoverns(unittest.TestCase):
    def setUp(self):
        self.tr = WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt")

    def test_outage_credit_not_capped_at_75(self):
        t = turn(self.tr, "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["governing_policy"], "BIL-POL-014 Rule 3")
        self.assertIn("$82.50", t["reply"])
        self.assertNotIn("ESCALATE", t["decision"])
        self.assertIn("BIL-POL-014 Rule 2", [r[0] for r in t["rejected_rules"]])

    def test_75_threshold_never_applied_to_outage_track(self):
        facts, _ = parse_text(BASE)
        d = evaluate(facts)
        self.assertFalse(any("4a" in r for r in d.escalation_reasons))

    def test_deadline_uses_resolution_date_not_statement(self):
        t = turn(self.tr, "REQUEST_DEADLINE")
        self.assertIn("October 21, 2026", t["reply"])
        self.assertNotIn("November 30", t["reply"])


class Incident2_RefuseWhenKBSilent(unittest.TestCase):
    def test_tax_question_is_not_answered_from_thin_air(self):
        t = turn(WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt"), "TAX_TREATMENT")
        self.assertEqual(t["decision"], "PARTIAL_ANSWER_ESCALATE")
        self.assertTrue(t["unsupported"])
        # only the grounded part may be asserted
        self.assertEqual(t["driving_articles"], ["KB-1004"])

    def test_unknown_question_escalates(self):
        txt = BASE.replace("One more thing while I have you — how long do I actually have to submit a request like this after an outage gets fixed?",
                           "Also, can you upgrade my phone for free since this happened?")
        t = [x for x in run_variant(txt)["turns"] if x["turn_time"] == "14:13"][0]
        self.assertEqual(t["decision"], "ESCALATE")

    def test_fabricated_citation_is_rejected(self):
        with self.assertRaises(GroundingError):
            verify_quote(corpus.by_id(corpus.load_all()), "KB-1004", "Outage credits also reduce taxes and surcharges.")


class PolicyPerturbations(unittest.TestCase):
    def test_no_noc_ticket_falls_back_to_rule_2(self):
        txt = BASE.replace("I do see a confirmed outage ticket, OUT-58823, logged for your address covering September 10, 6:00 AM through September 21, 6:00 AM.",
                           "I don't see any outage ticket for your address.")
        t = turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["governing_policy"], "BIL-POL-014 Rule 2")
        self.assertEqual(t["decision"], "ESCALATE")          # $225 > $75 ceiling -> Tier 2

    def test_request_after_30_days_falls_back_to_rule_2(self):
        facts, _ = parse_text(BASE)
        d = evaluate(facts, request_date=date(2026, 10, 25))
        self.assertEqual(d.governing_rule, "BIL-POL-014 Rule 2")

    def test_outage_under_4_hours_not_rule_3(self):
        txt = BASE.replace("September 21, 6:00 AM", "September 10, 9:00 AM")
        facts, _ = parse_text(txt)
        self.assertEqual(evaluate(facts).governing_rule, "BIL-POL-014 Rule 2")

    def test_credit_over_300_escalates_under_4b(self):
        txt = BASE.replace("$225.00/month", "$900.00/month")
        t = turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["governing_policy"], "BIL-POL-014 Rule 3")
        self.assertEqual(t["decision"], "ESCALATE")
        self.assertIn("$330.00", t["reply"])

    def test_outage_over_30_days_escalates(self):
        facts, _ = parse_text(BASE.replace("September 10, 6:00 AM", "August 10, 6:00 AM"))
        d = evaluate(facts)
        self.assertTrue(d.escalate)
        self.assertTrue(any("30 consecutive days" in r for r in d.escalation_reasons))

    def test_repeat_dispute_forces_tier_2(self):
        facts, _ = parse_text(BASE)
        facts.prior_resolved_dispute_within_90d = True
        d = evaluate(facts)
        self.assertTrue(d.escalate)

    def test_unknown_history_is_flagged_not_assumed_clean(self):
        facts, _ = parse_text(BASE)
        self.assertTrue(any("UNVERIFIED" in c for c in evaluate(facts).conditions))

    def test_distractor_articles_never_drive_a_reply(self):
        tr = WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt")
        used = {a for t in tr["turns"] for a in t["driving_articles"]}
        self.assertTrue(used.isdisjoint({"KB-1008", "KB-1009", "KB-1010"}))

    def test_facts_are_time_aware(self):
        # at 14:06 the NOC lookup has not happened yet -> must not quote a credit
        t = [x for x in WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt")["turns"] if x["turn_time"] == "14:06"][0]
        self.assertEqual(t["decision"], "GATHER_INFO")
        self.assertNotIn("$", t["reply"].replace("$225", ""))



class RetrievalIsLoadBearing(unittest.TestCase):
    def test_every_claim_retrieved_and_verified(self):
        s = WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt")["summary"]
        self.assertEqual(s["claims"], s["claims_verified"])
        self.assertEqual(s["multi_hop_retrieval_recall"], 1.0)
        self.assertLess(s["single_shot_retrieval_recall"], 1.0)   # one query alone misses evidence -> why hops exist

    def test_removing_the_outage_article_blocks_the_answer(self):
        # If the KB no longer contains KB-1004, the workflow must not answer the credit question from memory.
        wf = Workflow(passages=[p for p in corpus.load_all() if p.doc_id != "KB-1004"])
        t = turn(wf.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt"), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["decision"], "ESCALATE")
        self.assertTrue(any("KB-1004" in u for u in t["unsupported"]))

    def test_primary_article_named_for_every_reply(self):
        for t in WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt")["turns"]:
            self.assertIsNotNone(t["primary_source"], t["turn_time"])
            self.assertIn(t["primary_source"], t["driving_articles"])


class ParserAndRobustness(unittest.TestCase):
    def test_turns_with_same_minute_stamp_use_correct_prefix(self):
        # duplicate the 14:08 agent stamp onto the customer turn right after it
        txt = BASE.replace("[14:09] Customer", "[14:08] Customer")
        t = [x for x in run_variant(txt)["turns"] if x["intent"] == "CREDIT_AMOUNT_OR_LIMIT"][0]
        self.assertEqual(t["governing_policy"], "BIL-POL-014 Rule 3")   # NOC ticket from the earlier 14:08 turn is known

    def test_missing_date_does_not_crash_and_gathers_info(self):
        txt = BASE.replace("Date: October 5, 2026\n", "")
        t = turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["decision"], "GATHER_INFO")
        self.assertIn("request date", t["reply"])

    def test_missing_charge_does_not_fall_back_to_rule_2(self):
        txt = BASE.replace(" — $225.00/month recurring charge", "")
        t = turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["decision"], "GATHER_INFO")
        self.assertIsNone(t["governing_policy"])

    def test_year_boundary_outage(self):
        txt = (BASE.replace("Date: October 5, 2026", "Date: January 5, 2027")
                   .replace("September 10, 6:00 AM", "December 28, 6:00 AM")
                   .replace("September 21, 6:00 AM", "January 2, 6:00 AM")
                   .replace("invoice dated October 1st", "invoice dated January 1st"))
        facts, _ = parse_text(txt)
        self.assertEqual(facts.noc_outage[0].year, 2026)
        self.assertEqual(facts.noc_outage[1].year, 2027)
        d = evaluate(facts)
        self.assertEqual(d.governing_rule, "BIL-POL-014 Rule 3")
        self.assertEqual(d.full_days, 5)

    def test_llm_rewrite_guard(self):
        from nimbus_agent.llm import facts_preserved
        orig = "Credit $82.50 for 11 days; deadline October 21, 2026; ticket OUT-58823."
        self.assertTrue(facts_preserved(orig, "Good news: your credit is $82.50 for 11 days, the deadline is October 21, 2026, on ticket OUT-58823."))
        # reviewer's loophole: same multiset, roles swapped -> must be rejected
        self.assertFalse(facts_preserved("The $75 limit doesn't apply; your credit is $82.50.",
                                         "The $82.50 limit doesn't apply; your credit is $75."))
        self.assertFalse(facts_preserved(orig, "Credit $85.00 for 11 days; deadline October 21, 2026; ticket OUT-58823."))
        self.assertFalse(facts_preserved(orig, "Credit $82.50 for eleven days; deadline October 21, 2026; ticket OUT-58823."))
        self.assertFalse(facts_preserved(orig, orig + " You'll also get $10 back on taxes."))
        self.assertFalse(facts_preserved("Taxes aren't covered.", "Taxes for those eleven days aren't covered."))

    def test_rejected_llm_rewrite_keeps_template(self):
        class BadLLM:
            def label(self, q): return None
            def rewrite(self, q, reply): return None      # what IntentLLM.rewrite returns when the guard rejects
        t = turn(Workflow(llm=BadLLM()).run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt"), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["reply_rewritten_by"], "template")
        self.assertIn("$82.50", t["reply"])


class IndependentReviewFindings(unittest.TestCase):
    """Each test reproduces an input from the independent adversarial review."""

    def _with_turn(self, after_time: str, line: str) -> str:
        i = BASE.index(f"[{after_time}]")
        j = BASE.index("\n[", i + 1)
        return BASE[:j] + "\n\n" + line + BASE[j:]

    def test_H1_question_before_noc_lookup_does_not_repeat_incidents(self):
        txt = self._with_turn("14:06", "[14:07] Customer (Dana Whitfield): Isn't your refund limit only $75? And how long do I "
                                      "have to submit a request like this after an outage gets fixed?")
        early = [t for t in run_variant(txt)["turns"] if t["turn_time"] == "14:07"]
        self.assertEqual({t["intent"] for t in early}, {"CREDIT_AMOUNT_OR_LIMIT", "REQUEST_DEADLINE"})
        for t in early:
            self.assertEqual(t["decision"], "GATHER_INFO", t["reply"])
            self.assertNotIn("$75.00", t["reply"])
            self.assertNotIn("November", t["reply"])
            self.assertIn("outage records", t["reply"])

    def _ticket_line(self, covering: str) -> str:
        return BASE.replace("covering September 10, 6:00 AM through September 21, 6:00 AM", covering)

    def test_H2_ticket_dates_in_other_formats(self):
        for covering in ["covering 9/10 06:00 through 9/21 06:00", "covering Sep 10, 06:00 through Sep 21, 06:00",
                         "covering September 10 at 6 AM through September 21 at 6 AM"]:
            t = turn(run_variant(self._ticket_line(covering)), "CREDIT_AMOUNT_OR_LIMIT")
            self.assertIn("$82.50", t["reply"], covering)

    def test_H2_ticket_without_times_escalates_on_outage_track(self):
        tr = run_variant(self._ticket_line("covering September 10 through September 21"))
        c, dl = turn(tr, "CREDIT_AMOUNT_OR_LIMIT"), turn(tr, "REQUEST_DEADLINE")
        self.assertEqual(c["governing_policy"], "BIL-POL-014 Rule 3")
        self.assertEqual(c["decision"], "ESCALATE")
        self.assertNotIn("$75", c["reply"].replace("not the $75 goodwill limit", ""))
        self.assertEqual(dl["decision"], "PARTIAL_ANSWER_ESCALATE")
        self.assertNotIn("November", dl["reply"])

    def test_H3_late_request_deadline_answer(self):
        t = turn(run_variant(BASE.replace("Date: October 5, 2026", "Date: October 22, 2026")), "REQUEST_DEADLINE")
        self.assertIn("closed on October 21, 2026", t["reply"])
        self.assertIn("November 30, 2026", t["reply"])
        self.assertIn("$75", t["reply"])

    def test_M_credit_timing_not_answered_with_filing_deadline(self):
        txt = BASE.replace("how long do I actually have to submit a request like this after an outage gets fixed?",
                           "how long will it take for the credit to show up on my bill?")
        t = [x for x in run_variant(txt)["turns"] if x["turn_time"] == "14:13"][0]
        self.assertEqual(t["intent"], "CREDIT_TIMING")
        self.assertEqual(t["decision"], "ESCALATE")
        self.assertNotIn("October 21", t["reply"])

    def test_M_911_usf_fee_question_is_tax_treatment(self):
        txt = BASE.replace("does whatever credit I end up getting also reduce the taxes and regulatory surcharges I paid during those eleven days, or is it only applied against the plan charge itself?",
                           "will I get the 911 fee and Universal Service Fund charge back too?")
        t = [x for x in run_variant(txt)["turns"] if x["turn_time"] == "14:11"][0]
        self.assertEqual(t["intent"], "TAX_TREATMENT")
        self.assertNotIn("$82.50", t["reply"])

    def test_M_question_inside_identity_turn_not_dropped(self):
        txt = BASE.replace("the card ending is 4471.", "the card ending is 4471 - can you also waive the late fee from August?")
        t = [x for x in run_variant(txt)["turns"] if x["turn_time"] == "14:04"][0]
        self.assertEqual(t["decision"], "ESCALATE")

    def test_M_dispute_outside_60_day_window_escalates(self):
        t = turn(run_variant(BASE.replace("invoice dated October 1st", "invoice dated July 1st")), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["decision"], "ESCALATE")
        self.assertIn("more than 60 days after the statement date", t["reply"])
        self.assertNotIn("Rule 1", t["reply"])             # internal ids stay in the trace, not the customer reply

    def test_M_reply_numbers_must_be_evidenced(self):
        from nimbus_agent.grounding import unsupported_numbers
        self.assertEqual(unsupported_numbers("Your credit is $82.50 (Tier 2 not needed).", ["$82.50"]), set())
        self.assertEqual(unsupported_numbers("Your credit is $90.00.", ["$82.50"]), {90.0})

    def test_L_23_hour_outage_does_not_say_you_qualify_for_zero(self):
        t = turn(run_variant(self._ticket_line("covering September 10, 6:00 AM through September 11, 5:00 AM")), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["decision"], "ESCALATE")
        self.assertIn("shorter than one full day", t["reply"])

    def test_L_ticket_for_different_address_is_not_confirmation(self):
        txt = BASE.replace("Okay, I do see a confirmed outage ticket, OUT-58823, logged for your address covering September 10, 6:00 AM through September 21, 6:00 AM.",
                           "I don't see a ticket for your address; the only one nearby is OUT-58823, for a different address.")
        facts, _ = parse_text(txt)
        self.assertTrue(facts.noc_lookup_done)
        self.assertIsNone(facts.noc_ticket)
        self.assertEqual(turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")["governing_policy"], "BIL-POL-014 Rule 2")

    def test_L_12_hour_timestamps_parse(self):
        import re as _re
        txt = _re.sub(r"\[(\d{2}):(\d{2})\]", lambda m: f"[{int(m.group(1)) - 12}:{m.group(2)} PM]", BASE)
        t = turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertIn("$82.50", t["reply"])

    def test_L_full_day_convention_flagged(self):
        t = turn(WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt"), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertTrue(any("calendar days" in c for c in t["conditions"]))


class IndependentReviewRound2(unittest.TestCase):
    """Inputs from the second adversarial review round."""

    def _ins(self, after_time: str, lines: str, base: str = BASE) -> str:
        i = base.index(f"[{after_time}]")
        j = base.index("\n[", i + 1)
        return base[:j] + "\n\n" + lines + base[j:]

    def _credit_and_deadline(self, txt):
        tr = run_variant(txt)
        return [t for t in tr["turns"] if t["intent"] in ("CREDIT_AMOUNT_OR_LIMIT", "REQUEST_DEADLINE")]

    def test_R2H2a_no_problem_is_not_a_lookup_result(self):
        txt = self._ins("14:06", "[14:07] Agent (Jordan R.): No problem, let me pull up our outage records for your address now.\n\n"
                                 "[14:07] Customer (Dana Whitfield): Isn't your refund limit only $75? How long do I have to submit a request like this?")
        early = [t for t in self._credit_and_deadline(txt) if t["turn_time"] == "14:07"]
        self.assertEqual(len(early), 2)
        for t in early:
            self.assertEqual(t["decision"], "GATHER_INFO", t["reply"])

    def test_R2H2b_negation_in_other_clause_does_not_cancel_ticket(self):
        txt = BASE.replace("Okay, I do see a confirmed outage ticket", "I don't see any problem with your verification, and I do see a confirmed outage ticket")
        self.assertIn("$82.50", turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")["reply"])

    def test_R2H2c_negation_in_other_sentence_does_not_cancel_ticket(self):
        txt = BASE.replace("Give me a moment to work out", "Note the ticket doesn't cover your neighbour's building. Give me a moment to work out")
        self.assertIn("$82.50", turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")["reply"])

    def test_R2H1_outage_mentioned_without_dates_waits_for_lookup(self):
        cut = BASE[:BASE.index("[14:08]")]
        cut = cut.replace("Service went down on September 10th at 6 AM and wasn't back until September 21st at 6 AM — all three lines, totally dead, no calls or data.",
                          "Service was down for eleven days last month.")
        txt = cut.rstrip() + "\n\n[14:07] Customer (Dana Whitfield): Isn't your refund limit only $75?\n"
        t = turn(run_variant(txt), "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(t["decision"], "GATHER_INFO")
        self.assertNotIn("$75.00", t["reply"])

    def test_R2_two_tickets_escalate(self):
        txt = BASE.replace("covering September 10, 6:00 AM through September 21, 6:00 AM.",
                           "covering September 10, 6:00 AM through September 12, 6:00 AM, and a second ticket OUT-58901 covering September 12, 6:00 AM through September 21, 6:00 AM.")
        tr = run_variant(txt)
        c = turn(tr, "CREDIT_AMOUNT_OR_LIMIT")
        self.assertEqual(c["decision"], "ESCALATE")
        self.assertNotIn("$15.00", c["reply"])
        self.assertNotIn("October 12", turn(tr, "REQUEST_DEADLINE")["reply"])

    def test_R2_two_questions_in_one_sentence(self):
        txt = BASE.replace("Okay, but isn't your refund limit only $75? I saw something like that in your terms once. So you can only give me $75 back for this, right?",
                           "So is it only $75, and how long do I have to submit this?")
        q = [t for t in run_variant(txt)["turns"] if t["turn_time"] == "14:09"]
        self.assertEqual({t["intent"] for t in q}, {"CREDIT_AMOUNT_OR_LIMIT", "REQUEST_DEADLINE"})
        self.assertTrue(any("$82.50" in t["reply"] for t in q))

    def test_R2_fees_on_page_2_not_answered_with_credit(self):
        txt = BASE.replace("does whatever credit I end up getting also reduce the taxes and regulatory surcharges I paid during those eleven days, or is it only applied against the plan charge itself?",
                           "does the credit also cover the fees on page 2 of my invoice?")
        t = [x for x in run_variant(txt)["turns"] if x["turn_time"] == "14:11"][0]
        self.assertEqual(t["intent"], "TAX_TREATMENT")
        self.assertNotIn("$82.50", t["reply"])

    def test_R2_number_check_uses_only_decision_evidence(self):
        from nimbus_agent.grounding import unsupported_numbers
        tr = WF.run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt")
        t = turn(tr, "CREDIT_AMOUNT_OR_LIMIT")
        ev = [c["quote"] for c in t["claims"] if c["verified"]] + [c["detail"] for c in t["policy_checks"]] + ["225.0", "OUT-58823"]
        self.assertEqual(unsupported_numbers(t["reply"], ev), set())
        self.assertTrue(unsupported_numbers("Your credit is $91.25 for 13 full days.", ev))

    def test_R2_guard_rejects_negation_flip_and_money_turns_never_reworded(self):
        from nimbus_agent.llm import facts_preserved
        self.assertFalse(facts_preserved("The $75 limit doesn't apply here.", "The $75 limit applies here."))

        class EchoLLM:
            def label(self, q): return None
            def rewrite(self, q, reply): return reply + " (reworded)"
        tr = Workflow(llm=EchoLLM()).run(ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt")
        self.assertEqual(turn(tr, "CREDIT_AMOUNT_OR_LIMIT")["reply_rewritten_by"], "template")
        self.assertEqual(turn(tr, "REQUEST_DEADLINE")["reply_rewritten_by"], "template")

    def test_R2_other_escalations_reach_the_follow_up(self):
        txt = BASE.replace("the card ending is 4471.", "the card ending is 4471 - can you also waive the late fee from August?")
        c = run_variant(txt)["consolidated_follow_up"]
        self.assertIn("late fee", c["reply_to_customer"])
        self.assertTrue(any("UNKNOWN" in e for e in c["escalations"]))

    def test_R2_paraphrases_are_understood(self):
        from nimbus_agent.intents import label_all
        cases = {"How much will I get back?": "CREDIT_AMOUNT_OR_LIMIT", "what do I get for the downtime?": "CREDIT_AMOUNT_OR_LIMIT",
                 "will I get a credit for the days my device had no signal?": "CREDIT_AMOUNT_OR_LIMIT",
                 "when is the cutoff to ask for this?": "REQUEST_DEADLINE", "Is it too late to claim this?": "REQUEST_DEADLINE",
                 "how long will it take for the credit to show up?": "CREDIT_TIMING",
                 "can I pay the rest in installments?": "UNKNOWN", "can you waive the late fee from August?": "UNKNOWN"}
        for q, want in cases.items():
            self.assertEqual(label_all(q), [want], q)

    def test_R2_iso_date_header_and_not_finding_phrase(self):
        facts, _ = parse_text(BASE.replace("Date: October 5, 2026", "Date: 2026-10-05"))
        self.assertEqual(facts.conversation_date, date(2026, 10, 5))
        facts, _ = parse_text(BASE.replace("Okay, I do see a confirmed outage ticket, OUT-58823, logged for your address covering September 10, 6:00 AM through September 21, 6:00 AM.",
                                           "I'm not finding any outage ticket for your address."))
        self.assertTrue(facts.noc_lookup_done)
        self.assertIsNone(facts.noc_ticket)


if __name__ == "__main__":
    unittest.main()
