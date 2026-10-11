# Design memo: policy-grounded billing-dispute workflow

**To:** Agentic Assist product lead · **From:** Senior MLE

**Bottom line:** On the provided chat and on 49 perturbed-variant tests, the prototype does not repeat either incident. The tests include "$75?" asked *before* the outage lookup, agent small talk, other ticket date formats, two tickets and compound questions. That is evidence on constructed variants, not proof: it has not run on real traffic, and §3 is how to get there.

The fix is architectural:
- The workflow decides **which rule governs before calculating anything**.
- A claim reaches the customer only if retrieval surfaced its source *and* the quote matches verbatim.

I recommend funding the rebuild on this pattern, gated on §3.

## 1. Which replies are grounded

| Turn | Reply | Grounding |
|---|---|---|
| 14:09 "$75 limit?" | **$82.50** outage credit ($225 ÷ 30 × 11 full days), not capped at $75, no Tier 2 needed | **Grounded:** Rule 3, the Rule 4 note, KB-1004/1005/1006, ticket OUT-58823. Three agent-only conditions: repeat-dispute and fraud checks are **unverified** (no account history), and "full days" is undefined in the policy (24-hour periods give 11; whole calendar days give 10, which is $75.00). |
| 14:11 taxes | Credit applies to the plan charge only; tax treatment isn't covered, so it's escalated | **Partial, by design.** Only the first clause is grounded (KB-1004). KB-1003 ranks *first* in retrieval but describes how taxes are billed, not how credits affect them, so the answerability check rejects it. This is incident #2's shape. |
| 14:13 deadline | 30 days from resolution → **Oct 21, 2026** | **Grounded** (Rule 3, KB-1005). Rule 1's 60 days from the statement date (Nov 30) is logged as considered and rejected. |
| 14:02–14:06 | Gather info: identity, line item, NOC lookup | Grounded (KB-1001/1005). Credit and deadline questions asked before the lookup get "let me check the outage records first". |

All 29 claims passed the citation gate, and every number in every reply traces to verified evidence.

**Process:**
- gpt-4.1 audited the follow-up: all three answers correct; its missing-case-number note was added as a placeholder.
- Two rounds of independent adversarial review found ways back to incident #1: a "$75?" before the lookup, and agent phrasing like "No problem…records" read as "no ticket". Both are fixed, and every reviewer input is now one of the 49 regression tests.

## 2. Hardest point in the hierarchy to enforce

**Deciding Rule 2 vs Rule 3 before any threshold check, and never mixing thresholds across tracks.** $82.50 is over $75, so checking "> $75" first caps or escalates it wrongly. That is incident #1, and the ordering appears only in a note under Rule 4.

Retrieval alone can't enforce it. **One search on the customer's question surfaces 29% of the sources the correct answer needs, and the $75 article ranks second.** So the engine fixes the order (exception → its gates → its formula → its own thresholds → Rule 5), and each check retrieves its own evidence (100% recall).

The traps next to it:
- **Timing:** before the NOC lookup, the governing rule is *unknown*, not Rule 2. Lookup is modelled as three states: not done, no ticket, ticket.
- **Fall-through:** a failed Rule 3 gate drops the request to Rule 2 and its $75 cap. The exception is a ticket that exists but can't be verified, which escalates under Rule 4b.
- **Unknown ≠ pass:** missing account history becomes an explicit UNVERIFIED condition.

## 3. Next step: measuring instruction-adherence and hallucination

1. **Test set:** about 200 conversations (≈40 seeds × 5 perturbations). Cover every gate failing, both sides of each threshold ($75 / $300 / 4 h / 30 d / 60 d / 90 d), unanswerable questions, distractors, and question-before-lookup orderings. Gold-label rule, amount, decision and answerability per turn. The 49 tests are the seed.
2. **Release metrics:**
   - **Instruction-adherence:** correct rule *and* escalation; 100% on money turns.
   - **Hallucination rate:** claims without a verified span, via the verbatim gate plus an LLM judge for paraphrase.
   - **Abstention precision and recall** on unanswerable turns.
   - **Retrieval recall:** single query vs evidence-need hops, already logged at 0.78 vs 1.00.
   - **Rewording-guard rejections:** 1 of 3 live.
3. **Judge calibration:** about 100 human double-labelled turns; κ ≥ 0.8 before the judge gates releases.
4. **Shadow mode** with full traces; alert on escalation/abstention drift; add disagreements to the test set.

**What would change this:** if more than 5% of shadow turns hit "unknown intent → escalate", the closed intent set is too narrow. Build an open-question answerer behind the same gate first.
