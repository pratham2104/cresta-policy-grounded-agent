# Input materials (not included)

The three inputs were provided by the hiring team (Cresta) for the assessment, and they aren't redistributed here:

| Expected file name | What it is |
|---|---|
| `policy_BIL-POL-014.md` | Nimbus Wireless, Billing Dispute & Refund Policy (BIL-POL-014 v6.2) |
| `kb_billing_credits.md` | NimbusCare Knowledge Base, Billing & Credits excerpt (KB-1001 to KB-1010) |
| `transcript_CHT-2026-10-05-118827.txt` | NimbusCare chat transcript, Dana Whitfield, Oct 5 2026 |

Put them in this folder under these names, then run `python3 run.py` and `python3 -m unittest discover -s tests -v` from the repo root.

`../output/` holds the committed results of running the workflow on these inputs (`run_report.md`, `run_trace.json`, and the `--llm` variants), so you can inspect the behaviour without the materials.
