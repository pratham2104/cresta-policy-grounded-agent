12:31 start build; copied source materials unchanged into data/
12:36 first full run OK: Rule 3 credit $82.50, tax question partial+escalate, deadline Oct 21; fixed reply overclaiming 'apply directly' while Rule 5 unverified
12:37 LLM intent mode (gpt-4.1-mini): 6/6 intents match rules, ~1.1k tokens. gpt-4.1 compliance audit: all 3 answers correct+supported; added its suggestion (case-number placeholder + written-summary action, KB-1001 steps 3/5). Did NOT invent a case number.
12:38 packaged; clean-extract run + 15/15 tests pass; no keys
12:55 review fixes started: (1) retrieval made load-bearing via per-claim evidence-need hops (cited source must rank top-3 for its need), (2) primary_source per reply, (3) bugs: turn-offset facts, year boundary, missing date crash, %-d portability, missing-charge silent Rule 2 fallback
12:57 added guarded LLM rewrite; guard rejected the $82.50 rewrite; caught spelled-out 'eleven' slipping past the numeric guard -> added number words; 25 tests pass on py3.9/3.12/3.15
12:58 memo cut to one page; repackaged; clean-extract verified
13:03 independent review: 3 HIGH (pre-lookup question repeats both incidents; ticket date formats -> treated as no ticket; late request deadline answer wrong) + 6 MED + LOW. Fixing all.
13:07 fixed all review findings (3 HIGH, 6 MED, LOW): NOC lookup states, wider date/time/timestamp parsing, unverifiable ticket->4b escalate, late-window deadline answer, Rule 1 late escalation, intent fixes (timing/911/USF/waive/identity+question), reply-number evidence check, order-aware LLM guard, zero-day outage, full-day convention flag. 37 tests, each reviewer input reproduced as a test.
13:07 memo trimmed; repackaged; clean-extract 37/37 (both discover and direct run)
13:11 round-2 review: ticket-negation over-fires ('No problem...records'), lookup gate needs parseable dates, multi-ticket, multi-question sentences, fees, loose number check, guard negation. Fixing.
13:14 round-2 fixes done; 49 tests; repackaged
