#!/usr/bin/env python3
"""Run the policy-grounded workflow over a NimbusCare transcript.

  python3 run.py                       # provided transcript, deterministic
  python3 run.py --llm                 # + OpenAI intent labelling (needs OPENAI_API_KEY)
  python3 run.py --transcript other.txt
Writes output/run_trace.json (full evidence) and output/run_report.md (readable).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from nimbus_agent.workflow import Workflow  # noqa: E402

DEFAULT_TRANSCRIPT = ROOT / "data" / "transcript_CHT-2026-10-05-118827.txt"


def render(trace: dict) -> str:
    s = trace["summary"]
    L = ["# Run report", "", f"Transcript: `{Path(trace['transcript']).name}`", "",
         f"**Summary:** {s['questions']} questions · decisions {s['decisions']} · "
         f"{s['claims_verified']}/{s['claims']} claims grounded (retrieved for their evidence need + quote verified verbatim) · "
         f"retrieval recall of cited sources: single query on the question = {s['single_shot_retrieval_recall']}, "
         f"multi-hop evidence-need retrieval = {s['multi_hop_retrieval_recall']}", "",
         "| Turn | Customer question | Intent | Governing policy | Primary article | Supporting sources | Decision |",
         "|---|---|---|---|---|---|---|"]
    for t in trace["turns"]:
        q = t["question"].replace("|", "/")
        support = [a for a in t["driving_articles"] if a not in (t["primary_source"], t["governing_policy"])]
        L.append(f"| {t['turn_time']} | {q[:80]}{'…' if len(q) > 80 else ''} | {t['intent']} | {t['governing_policy'] or '-'} "
                 f"| {t['primary_source'] or '-'} | {', '.join(support) or '-'} | **{t['decision']}** |")
    for t in trace["turns"]:
        L += ["", f"## [{t['turn_time']}] {t['intent']} → {t['decision']}", "", f"> {t['question']}", "",
              f"**Reply** ({t['reply_rewritten_by']}): {t['reply']}", "",
              f"**Governing policy:** {t['governing_policy'] or '-'} · **Primary article:** {t['primary_source'] or '-'}", "",
              "**Hop-0 retrieval (question):** " + "; ".join(f"{h['doc_id']} ({h['score']}){' ✓cited' if h['used_in_reply'] else ''}"
                                                            for h in t["retrieved"])]
        if t["retrieval_metrics"]:
            m = t["retrieval_metrics"]
            L += ["", f"**Retrieval recall:** single query {m['single_shot_recall']} vs evidence-need hops {m['hop_recall']}"]
        if t["policy_checks"]:
            L += ["", "**Policy checks:** " + "; ".join(f"{c['check']}={c['result']} ({c['detail']})" for c in t["policy_checks"])]
        if t["rejected_rules"]:
            L += ["", "**Considered and rejected:** " + "; ".join(f"{a}: {b}" for a, b in t["rejected_rules"])]
        if t["unsupported"]:
            L += ["", "**Not supported by evidence (declined):** " + " ".join(t["unsupported"])]
        if t["conditions"]:
            L += ["", "**Preconditions (agent-only):** " + " ".join(t["conditions"])]
        L += ["", "**Citations** (source · rank in its evidence-need retrieval · verbatim quote):"]
        L += [f"- {c['doc_id']} · rank {c['retrieved_rank'] or '✗ not retrieved'} · \"{c['quote'][:90]}{'…' if len(c['quote']) > 90 else ''}\""
              f"{'' if c['verified'] else ' **✗ REJECTED**'}" for c in t["claims"]]
    c = trace["consolidated_follow_up"]
    L += ["", "## Consolidated follow-up (what Jordan promised at 14:14)", "", c["reply_to_customer"], "",
          "**Agent actions:**", *[f"- {x}" for x in c["agent_actions"]], "",
          "**Agent-only preconditions before issuing the credit:**", *[f"- {x}" for x in c["agent_only_preconditions_before_issuing_credit"]],
          "", "**Escalations:** " + (", ".join(c["escalations"]) or "none")]
    if "llm_usage" in trace:
        L += ["", f"**LLM usage:** {trace['llm_usage']}"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", default=str(DEFAULT_TRANSCRIPT))
    ap.add_argument("--llm", action="store_true", help="label intents with OpenAI (OPENAI_API_KEY)")
    ap.add_argument("--out", default=str(ROOT / "output"))
    a = ap.parse_args()

    llm = None
    if a.llm:
        from nimbus_agent.llm import IntentLLM
        try:
            llm = IntentLLM()
        except RuntimeError as e:
            print(f"[warn] {e}; falling back to rule-based intents", file=sys.stderr)
    trace = Workflow(llm=llm).run(a.transcript)
    if not trace["turns"]:
        sys.exit(f"error: no customer turns parsed from {a.transcript} - expected lines like "
                 "'[14:02] Customer (Name): ...' or '[2:02 PM] Agent: ...'")
    if llm:
        trace["llm_usage"] = {"model": llm.model, **llm.usage}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "_llm" if llm else ""
    (out / f"run_trace{suffix}.json").write_text(json.dumps(trace, indent=2, default=str))
    report = render(trace)
    (out / f"run_report{suffix}.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
