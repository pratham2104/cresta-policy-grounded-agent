# Policy-grounded billing agent workflow (NimbusCare, Agentic Assist prototype)

A runnable workflow that reads a live billing chat turn by turn and drafts the agent's reply. For each turn it shows which policy governs and which retrieved article drove the reply. When the evidence doesn't support an answer, it **declines or escalates** instead of answering.

It was built to show that the next version would not repeat either reported incident:

| Incident | What went wrong | What this workflow does instead |
|---|---|---|
| 1 | Quoted the general $75 refund limit when the narrower service-outage exception applied | The policy engine decides the **governing rule first** (the specific Rule 3 before the general Rule 2). It then applies **only that rule's** escalation thresholds. |
| 2 | Answered a billing question the KB never covered | An **answerability check** requires one sentence in the evidence that addresses the question's concepts *together*. Every citation is **verified verbatim** against the source, and anything unsupported is declined or escalated. |

> **Inputs:** the hiring team's policy, KB excerpt and transcript are not included in this public repo. See [`data/README.md`](data/README.md) for where they go. Committed outputs of the run are in [`output/`](output/), and the one-page design memo is [`design_memo.md`](design_memo.md).

## Run it (Python ≥ 3.9, standard library only, no API key needed)

```bash
python3 run.py                                   # provided transcript → output/run_report.md + output/run_trace.json
python3 -m unittest discover -s tests -v         # 49 tests (verified on Python 3.9, 3.12, 3.15)
python3 run.py --transcript path/to/other.txt    # any transcript in the same format
OPENAI_API_KEY=... python3 run.py --llm          # optional: LLM intent labelling + guarded reply rewording (gpt-4.1-mini; OPENAI_MODEL overrides)
```

`output/run_report.md` is the human-readable view: a per-turn table (question → intent → **governing policy** → **primary article** → supporting sources → decision), then for each turn the reply, the question-level retrieval with BM25 scores, the per-turn retrieval recall, the policy checks, the rules considered and rejected, anything declined as unsupported, and every citation with its rank in its evidence-need retrieval. `output/run_trace.json` holds the same data in machine-readable form. `output/run_report_llm.md` is the `--llm` run, showing which replies the rewording guard accepted or rejected.

## Result on the provided conversation (Dana Whitfield, Oct 5 2026)

| Turn | Question | Governing | Decision |
|---|---|---|---|
| 14:09 | "Isn't your refund limit only $75?" | **Rule 3** (outage credit). Rule 2 was considered and rejected. | Answer: **$225 ÷ 30 × 11 full days = $82.50**, not capped at $75. No Tier 2 needed (≤ $300, ≤ 30 days, ticket OUT-58823 verified). |
| 14:11 | Do credits reduce taxes and surcharges? | No rule or article covers it | **Partial answer + escalate.** It confirms only that the credit is calculated on the plan charge (KB-1004) and declines the rest. KB-1003 ranked top in retrieval but was **not** used. |
| 14:13 | How long do I have to submit? | Rule 3 / KB-1005 | Answer: **30 days from resolution → Oct 21 2026**. Rule 1's 60-days-from-statement window was considered and rejected. |

Preconditions the agent sees but the customer doesn't: the repeat-dispute and fraud checks (Rule 4c/4d, Rule 5) are **UNVERIFIED**, because no account history was provided. They are flagged as unverified rather than assumed clean.

## Architecture

```
transcript ─► conversation.py   facts known *at each turn* (no look-ahead); unknowns stay None
          ─► intents.py         split questions; closed intent set (rules by default, optional LLM)
          ─► retrieval.py       BM25 over 5 policy rules + preamble + 10 KB articles
          ─► policy_engine.py   governing rule → gates → formula → that track's thresholds → Rule 5
          ─► workflow.py        per-claim evidence-need retrieval hops → citation gate → compose → (optional) guarded rewording
          ─► grounding.py       answerability check + verbatim citation verification
```

**Retrieval is load-bearing, not decorative.** Every claim, including each policy check, declares an *evidence need* (a retrieval query). A claim is accepted only if:
1. BM25 retrieval for that need returns the cited source in its **top 3**, and
2. the quoted text is a **verbatim substring** of that source.

Any rejected claim withholds the reply and escalates. On this conversation, 29 of 29 claims pass.

Measured: a single retrieval on the customer's question surfaces only **29% of the sources** the correct $75 answer needs, and 78% averaged over all turns. Per-claim evidence-need hops surface **100%**. That gap is how incident #1 happens: answering from whatever the question happens to retrieve (here KB-1002, the $75 article, ranks second). A test removes KB-1004 from the corpus and checks the credit answer escalates instead of answering from memory.

**Optional LLM, kept out of the decision path.** `--llm` uses the model in two places:
- **Intent labelling** into a closed set. It agreed with the rules on 6/6 questions.
- **Rewording customer-facing replies, never money or deadline answers.** Those stay exactly as the engine computed them. Other rewrites are accepted only if the *ordered* sequence of amounts, digits, spelled-out numbers, month names and ticket or case IDs is unchanged and the negation count matches ("doesn't apply" → "applies" is rejected). Otherwise the template stays.

On the live run the guard rejected a rewrite of the tax reply that added "eleven days", a fact the grounded reply never asserted. The guard checks facts, not meaning: a rewrite that changes a policy claim without changing a number would pass. That's why amounts, deadlines and eligibility never come from the model and are never reworded by it.


Design choice: **money decisions are deterministic code, not model output.** Retrieval and the optional LLM only decide what is *considered*. The policy engine and the grounding gate decide what is *said*. Any claim whose citation fails verification turns the reply into an escalation.

## Files
- `data/`: where the three provided inputs go (not redistributed; see `data/README.md`).
- `nimbus_agent/`: the workflow package.
- `tests/test_workflow.py`: 49 tests.
  - **Both incidents**, including the case where the customer asks before the NOC lookup has happened. The workflow says "let me check the outage records first" instead of quoting $75 or a 60-day deadline.
  - **Policy perturbations:** no ticket → Rule 2 + Tier 2; ticket for a different address; request after 30 days, with the deadline answer explaining that the outage window closed on Oct 21 and the general window runs to Nov 30; outage of 4 hours or less; outage under 24 hours; $900 plan → $330 → escalate; outage over 30 days; dispute outside the 60-day statement window; repeat dispute → Tier 2; ticket without readable times → Rule 4b escalation on the outage track, never a $75 fallback.
  - **Parsing:** `9/10 06:00`, `Sep 10, 06:00`, `6 AM`, 12-hour `[2:08 PM]` timestamps, two turns stamped the same minute, missing date or charge, an outage crossing New Year.
  - **Intents:** credit-timing, 911/USF fees, and a question tucked into the identity turn are escalated, not answered with the wrong rule.
  - **Grounding:** corpus ablation (removing KB-1004 forces escalation); a fabricated quote is rejected; reply numbers must appear in verified evidence; the LLM guard rejects changed, added, spelled-out or **swapped** amounts.
  - `IndependentReviewFindings` and `IndependentReviewRound2` reproduce every input from two rounds of independent adversarial review. Examples: agent small talk like "No problem, let me pull up the records" must not count as "no ticket"; a negation in another sentence must not cancel a ticket; an outage mentioned without dates still waits for the lookup; two tickets escalate; two questions in one sentence are both answered; paraphrases ("how much will I get back", "is it too late") are understood.
- `output/`: committed run outputs, both deterministic and `--llm`.

## Limitations (honest)
- **What "grounded" means here.** Each claim the engine makes is retrieved for its evidence need and verified verbatim, and every number in a customer-facing reply must appear in that verified evidence or in the computed checks. Non-numeric wording in the reply templates is written by the engine author and is not semantically verified sentence by sentence; that would need an NLI or LLM-judge check (see memo §3).
- **"Full days"** are counted as complete 24-hour periods on the NOC ticket (264 h → 11 → $82.50). Counting whole calendar days without service gives 10 → $75.00. The policy doesn't define it, so it is surfaced to the agent as a condition rather than silently chosen.
- Evidence needs are written per policy check (part of the engine), not per transcript, so they generalise across conversations about this policy. A new policy needs its checks and needs written.
- The intent rules are tuned to billing phrasing. The `--llm` mode generalises labelling, but the closed intent set means a novel question type escalates rather than being answered. That fail-safe is deliberate, but it costs coverage.
- Facts come from transcript text, including the NOC ticket the human agent read out. In production these would come from the NOC, billing and dispute-history tools directly.
- The KB header says "9 articles", but the excerpt contains 10 (KB-1001 to KB-1010). All 10 are indexed.
