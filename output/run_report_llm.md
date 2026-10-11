# Run report

Transcript: `transcript_CHT-2026-10-05-118827.txt`

**Summary:** 6 questions · decisions {'ANSWER_WITH_CONDITIONS': 2, 'GATHER_INFO': 2, 'NO_POLICY_QUESTION': 1, 'PARTIAL_ANSWER_ESCALATE': 1} · 29/29 claims grounded (retrieved for their evidence need + quote verified verbatim) · retrieval recall of cited sources: single query on the question = 0.781, multi-hop evidence-need retrieval = 1.0

| Turn | Customer question | Intent | Governing policy | Primary article | Supporting sources | Decision |
|---|---|---|---|---|---|---|
| 14:02 | Hi, I need to dispute a charge on my latest bill. My service was out for almost … | DISPUTE_REQUEST | - | KB-1001 | - | **GATHER_INFO** |
| 14:04 | Account is NMB-7745213, and the card ending is 4471. | IDENTITY_INFO | - | KB-1001 | - | **NO_POLICY_QUESTION** |
| 14:06 | Service went down on September 10th at 6 AM and wasn't back until September 21st… | DISPUTE_REQUEST | - | KB-1005 | - | **GATHER_INFO** |
| 14:09 | Okay, but isn't your refund limit only $75? So you can only give me $75 back for… | CREDIT_AMOUNT_OR_LIMIT | BIL-POL-014 Rule 3 | KB-1004 | BIL-POL-014 Rule 1, BIL-POL-014 Rule 4, BIL-POL-014 Rule 5, KB-1005, KB-1006 | **ANSWER_WITH_CONDITIONS** |
| 14:11 | While you're looking into that — does whatever credit I end up getting also redu… | TAX_TREATMENT | none - not covered by BIL-POL-014 or KB excerpt | KB-1004 | - | **PARTIAL_ANSWER_ESCALATE** |
| 14:13 | One more thing while I have you — how long do I actually have to submit a reques… | REQUEST_DEADLINE | BIL-POL-014 Rule 3 | KB-1005 | BIL-POL-014 Rule 1, BIL-POL-014 Rule 4, BIL-POL-014 Rule 5 | **ANSWER_WITH_CONDITIONS** |

## [14:02] DISPUTE_REQUEST → GATHER_INFO

> Hi, I need to dispute a charge on my latest bill. My service was out for almost two weeks last month and I still got charged the full $225.00 like nothing happened.

**Reply** (template): Next step for the agent: verify identity (KB-1001 step 1); identify the specific disputed line item (KB-1001 step 2). Do not quote any credit amount yet.

**Governing policy:** - · **Primary article:** KB-1001

**Hop-0 retrieval (question):** KB-1004 (5.63); KB-1005 (5.31); KB-1006 (5.06); KB-1001 (4.32) ✓cited

**Retrieval recall:** single query 1.0 vs evidence-need hops 1.0

**Citations** (source · rank in its evidence-need retrieval · verbatim quote):
- KB-1001 · rank 1 · "Confirm the account holder's identity"
- KB-1001 · rank 1 · "Identify the exact line item being disputed"

## [14:04] IDENTITY_INFO → NO_POLICY_QUESTION

> Account is NMB-7745213, and the card ending is 4471.

**Reply** (template): (No policy question. Identity details captured for verification per KB-1001 step 1.)

**Governing policy:** - · **Primary article:** KB-1001

**Hop-0 retrieval (question):** BIL-POL-014 Rule 2 (0.7); KB-1002 (0.63); KB-1001 (0.6) ✓cited; KB-1007 (0.6)

**Retrieval recall:** single query 1.0 vs evidence-need hops 1.0

**Citations** (source · rank in its evidence-need retrieval · verbatim quote):
- KB-1001 · rank 1 · "Confirm the account holder's identity (name, account number, and either the last 4 digits …"

## [14:06] DISPUTE_REQUEST → GATHER_INFO

> Service went down on September 10th at 6 AM and wasn't back until September 21st at 6 AM — all three lines, totally dead, no calls or data. I'm disputing the full $225.00 recurring charge on the invoice dated October 1st.

**Reply** (template): Next step for the agent: look up the NOC outage ticket for the service address and dates (KB-1005 step 2). Do not quote any credit amount yet.

**Governing policy:** - · **Primary article:** KB-1005

**Hop-0 retrieval (question):** KB-1005 (16.35) ✓cited; BIL-POL-014 Rule 3 (11.5); KB-1004 (11.38); KB-1003 (5.44)

**Retrieval recall:** single query 1.0 vs evidence-need hops 1.0

**Citations** (source · rank in its evidence-need retrieval · verbatim quote):
- KB-1005 · rank 1 · "Look up the NOC outage ticket (format: OUT-#####) covering that address and date range."

## [14:09] CREDIT_AMOUNT_OR_LIMIT → ANSWER_WITH_CONDITIONS

> Okay, but isn't your refund limit only $75? So you can only give me $75 back for this, right?

**Reply** (template): The $75 limit you saw is our general goodwill limit, and it doesn't apply here. Because NOC ticket OUT-58823 confirms your outage, you qualify for a Service-Outage Credit, which is a separate policy and isn't capped at $75. It's calculated as your $225.00 monthly charge / 30 x 11 full days without service = $82.50 (the credit covers the days you were without service, not the whole month). That's within what can be applied at the front line (outage credits only need specialist approval above $300 or for outages longer than 30 days); I'll apply it once I've completed the standard account-history check.

**Governing policy:** BIL-POL-014 Rule 3 · **Primary article:** KB-1004

**Hop-0 retrieval (question):** BIL-POL-014 Rule 3 (5.77) ✓cited; KB-1002 (4.95); KB-1006 (4.92) ✓cited; BIL-POL-014 Rule 2 (4.18)

**Retrieval recall:** single query 0.286 vs evidence-need hops 1.0

**Policy checks:** dispute_window_60d=pass (statement 2026-10-01, window closes 2026-11-30); specific_line_item=pass (disputed item: $225.00 recurring charge); noc_ticket_exists=pass (OUT-58823 covers 2026-09-10 06:00:00 -> 2026-09-21 06:00:00); outage_over_4h=pass (264 consecutive hours on ticket); requested_within_30d_of_resolution=pass (resolved 2026-09-21, requested 2026-10-05, deadline 2026-10-21); credit_formula=info ($225.00 / 30 x 11 full days = $82.50); not_capped_by_general_75=info ($82.50 exceeds $75.00 but Rule 2's ceiling does not apply to this track); rule_4b_thresholds=pass (credit $82.50 vs $300.00; outage 11.0 days vs 30); repeat_dispute_90d=unverified (no dispute history in the provided evidence); fraud_indicators=unverified (no fraud review data in the provided evidence)

**Considered and rejected:** BIL-POL-014 Rule 2: more specific Rule 3 governs; Rule 2's $75 ceiling must not be blended in (Rule 3, Rule 4 note, KB-1006)

**Preconditions (agent-only):** 'Full days' counted as complete 24-hour periods on the NOC ticket (264 h -> 11). Counting only whole calendar days fully without service would give 10 (= $75.00); the policy does not define it - confirm Billing Ops convention. Repeat-dispute check UNVERIFIED: transcript has no account dispute history. If a resolved dispute exists in the prior 90 days, Tier 2 must decide (Rule 4c / Rule 5). Fraud-indicator check UNVERIFIED: no fraud flags in provided evidence (Rule 4d / Rule 5).

**Citations** (source · rank in its evidence-need retrieval · verbatim quote):
- BIL-POL-014 Rule 1 · rank 1 · "within 60 calendar days of the statement date"
- BIL-POL-014 Rule 1 · rank 1 · "The dispute must identify the specific line item or charge being contested"
- BIL-POL-014 Rule 3 · rank 1 · "A valid NOC outage ticket number exists covering the customer's service address and the da…"
- BIL-POL-014 Rule 3 · rank 1 · "The outage duration recorded on the NOC ticket exceeds 4 consecutive hours."
- BIL-POL-014 Rule 3 · rank 1 · "The customer requests the credit within 30 calendar days of the outage's resolution date (…"
- BIL-POL-014 Rule 3 · rank 2 · "Service-Outage Credit = (current monthly recurring charge ÷ 30) × number of full days the …"
- BIL-POL-014 Rule 3 · rank 1 · "is not counted against, and not capped by, the $75.00 General Refund/Goodwill Credit Limit"
- BIL-POL-014 Rule 4 · rank 1 · "A Service-Outage Credit only needs escalation if it independently meets condition (b)."
- BIL-POL-014 Rule 5 · rank 1 · "must have the credit decision made by a Tier 2 Billing Specialist, not the front-line agen…"
- BIL-POL-014 Rule 5 · rank 1 · "must have the credit decision made by a Tier 2 Billing Specialist, not the front-line agen…"
- KB-1004 · rank 1 · "is issued separately from, and is not limited by, the standard $75.00 goodwill credit ceil…"
- KB-1006 · rank 1 · "A Service-Outage Credit above $75.00 does not by itself require escalation"
- KB-1005 · rank 1 · "If the calculated credit is $300.00 or less and the outage lasted 30 days or fewer, the ag…"

## [14:11] TAX_TREATMENT → PARTIAL_ANSWER_ESCALATE

> While you're looking into that — does whatever credit I end up getting also reduce the taxes and regulatory surcharges I paid during those eleven days, or is it only applied against the plan charge itself?

**Reply** (template): What I can confirm: the outage credit is calculated on your recurring plan charge only. Whether the taxes and regulatory surcharges from those days are also adjusted isn't something our billing guidance covers, so I won't guess. I'm sending that part to a Tier 2 Billing Specialist, and you'll get a confirmed answer in writing with your case number.

**Governing policy:** none - not covered by BIL-POL-014 or KB excerpt · **Primary article:** KB-1004

**Hop-0 retrieval (question):** KB-1003 (16.2); KB-1004 (9.73) ✓cited; KB-1010 (9.45); BIL-POL-014 Rule 3 (6.55)

**Retrieval recall:** single query 1.0 vs evidence-need hops 1.0

**Not supported by evidence (declined):** Whether taxes/regulatory surcharges billed during the outage are reduced or refunded: no policy rule or KB article addresses it (KB-1003 describes how taxes are billed, not how credits affect them).

**Citations** (source · rank in its evidence-need retrieval · verbatim quote):
- KB-1004 · rank 1 · "This credit applies to the recurring plan charge only"

## [14:13] REQUEST_DEADLINE → ANSWER_WITH_CONDITIONS

> One more thing while I have you — how long do I actually have to submit a request like this after an outage gets fixed?

**Reply** (template): For an outage credit, the deadline is 30 days from the date the outage was resolved, not from your bill date. Your outage was resolved on September 21, so the request must be in by October 21, 2026. Today's request is within that.

**Governing policy:** BIL-POL-014 Rule 3 · **Primary article:** KB-1005

**Hop-0 retrieval (question):** BIL-POL-014 Rule 3 (8.13) ✓cited; KB-1006 (7.31); KB-1004 (6.88); BIL-POL-014 Rule 5 (6.17) ✓cited

**Retrieval recall:** single query 0.4 vs evidence-need hops 1.0

**Policy checks:** dispute_window_60d=pass (statement 2026-10-01, window closes 2026-11-30); specific_line_item=pass (disputed item: $225.00 recurring charge); noc_ticket_exists=pass (OUT-58823 covers 2026-09-10 06:00:00 -> 2026-09-21 06:00:00); outage_over_4h=pass (264 consecutive hours on ticket); requested_within_30d_of_resolution=pass (resolved 2026-09-21, requested 2026-10-05, deadline 2026-10-21); credit_formula=info ($225.00 / 30 x 11 full days = $82.50); not_capped_by_general_75=info ($82.50 exceeds $75.00 but Rule 2's ceiling does not apply to this track); rule_4b_thresholds=pass (credit $82.50 vs $300.00; outage 11.0 days vs 30); repeat_dispute_90d=unverified (no dispute history in the provided evidence); fraud_indicators=unverified (no fraud review data in the provided evidence)

**Considered and rejected:** BIL-POL-014 Rule 2: more specific Rule 3 governs; Rule 2's $75 ceiling must not be blended in (Rule 3, Rule 4 note, KB-1006); BIL-POL-014 Rule 1 (60 days from statement date): general dispute window; the outage-credit request deadline is the narrower Rule 3 condition

**Preconditions (agent-only):** 'Full days' counted as complete 24-hour periods on the NOC ticket (264 h -> 11). Counting only whole calendar days fully without service would give 10 (= $75.00); the policy does not define it - confirm Billing Ops convention. Repeat-dispute check UNVERIFIED: transcript has no account dispute history. If a resolved dispute exists in the prior 90 days, Tier 2 must decide (Rule 4c / Rule 5). Fraud-indicator check UNVERIFIED: no fraud flags in provided evidence (Rule 4d / Rule 5).

**Citations** (source · rank in its evidence-need retrieval · verbatim quote):
- BIL-POL-014 Rule 1 · rank 1 · "within 60 calendar days of the statement date"
- BIL-POL-014 Rule 1 · rank 1 · "The dispute must identify the specific line item or charge being contested"
- BIL-POL-014 Rule 3 · rank 1 · "A valid NOC outage ticket number exists covering the customer's service address and the da…"
- BIL-POL-014 Rule 3 · rank 1 · "The outage duration recorded on the NOC ticket exceeds 4 consecutive hours."
- BIL-POL-014 Rule 3 · rank 1 · "The customer requests the credit within 30 calendar days of the outage's resolution date (…"
- BIL-POL-014 Rule 3 · rank 2 · "Service-Outage Credit = (current monthly recurring charge ÷ 30) × number of full days the …"
- BIL-POL-014 Rule 3 · rank 1 · "is not counted against, and not capped by, the $75.00 General Refund/Goodwill Credit Limit"
- BIL-POL-014 Rule 4 · rank 1 · "A Service-Outage Credit only needs escalation if it independently meets condition (b)."
- BIL-POL-014 Rule 5 · rank 1 · "must have the credit decision made by a Tier 2 Billing Specialist, not the front-line agen…"
- BIL-POL-014 Rule 5 · rank 1 · "must have the credit decision made by a Tier 2 Billing Specialist, not the front-line agen…"
- KB-1005 · rank 1 · "Confirm the customer is requesting within 30 days of the ticket's resolution date."

## Consolidated follow-up (what Jordan promised at 14:14)

Credit and policy: The $75 limit you saw is our general goodwill limit, and it doesn't apply here. Because NOC ticket OUT-58823 confirms your outage, you qualify for a Service-Outage Credit, which is a separate policy and isn't capped at $75. It's calculated as your $225.00 monthly charge / 30 x 11 full days without service = $82.50 (the credit covers the days you were without service, not the whole month). That's within what can be applied at the front line (outage credits only need specialist approval above $300 or for outages longer than 30 days); I'll apply it once I've completed the standard account-history check.

Taxes and surcharges: What I can confirm: the outage credit is calculated on your recurring plan charge only. Whether the taxes and regulatory surcharges from those days are also adjusted isn't something our billing guidance covers, so I won't guess. I'm sending that part to a Tier 2 Billing Specialist, and you'll get a confirmed answer in writing with your case number.

Deadline: For an outage credit, the deadline is 30 days from the date the outage was resolved, not from your bill date. Your outage was resolved on September 21, so the request must be in by October 21, 2026. Today's request is within that.

Case number: [BDC-###### - assigned when the dispute is logged]. You'll receive this summary in writing.

**Agent actions:**
- Log the dispute in the Billing Case queue and obtain a case number (format BDC-######) - KB-1001 step 3; the transcript contains none, so the reply leaves a placeholder rather than inventing one.
- Send this resolution and the case number to the customer in writing - KB-1001 step 5.

**Agent-only preconditions before issuing the credit:**
- 'Full days' counted as complete 24-hour periods on the NOC ticket (264 h -> 11). Counting only whole calendar days fully without service would give 10 (= $75.00); the policy does not define it - confirm Billing Ops convention.
- Fraud-indicator check UNVERIFIED: no fraud flags in provided evidence (Rule 4d / Rule 5).
- Repeat-dispute check UNVERIFIED: transcript has no account dispute history. If a resolved dispute exists in the prior 90 days, Tier 2 must decide (Rule 4c / Rule 5).

**Escalations:** [14:11] TAX_TREATMENT

**LLM usage:** {'model': 'gpt-4.1-mini', 'calls': 8, 'prompt_tokens': 1499, 'completion_tokens': 140, 'failures': 0, 'rewrites_rejected': 1}
