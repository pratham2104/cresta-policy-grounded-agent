"""Parse a NimbusCare chat transcript into turns and case facts.

Facts are only ever taken from the transcript text. Anything the transcript
does not establish (prior disputes, prior goodwill credits, fraud flags) stays
None and is reported as unverified downstream, never defaulted to "clean".

NOC lookup has three distinct states, because conflating them is how a
pre-lookup question falls through to the $75 rule:
  * not yet looked up      -> noc_lookup_done = False
  * looked up, no ticket   -> noc_lookup_done = True,  noc_ticket = None
  * looked up, ticket      -> noc_lookup_done = True,  noc_ticket = "OUT-....."
    (if its dates/times can't be read precisely, noc_outage stays None and
     noc_unverifiable says why -> Rule 4b "cannot be verified" -> escalate)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MON = rf"(?:{MONTHS}|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
_TIME = r"(?:\s*,?\s*(?:at\s*)?(?P<{p}h>\d{{1,2}})(?::(?P<{p}m>\d{{2}}))?\s*(?P<{p}ap>[AaPp]\.?\s?[Mm]\.?)|\s*,?\s*(?:at\s*)?(?P<{p}H>[01]?\d|2[0-3]):(?P<{p}M>[0-5]\d)(?!\s*[AaPp]\.?\s?[Mm]))?"
DT_RE = re.compile(
    r"(?:(?P<mon>" + _MON + r")\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<yr>\d{4}))?" + _TIME.format(p="a") +
    r"|(?<![\d/])(?P<nm>\d{1,2})/(?P<nd>\d{1,2})(?:/(?P<ny>\d{2,4}))?(?![\d/])" + _TIME.format(p="b") + ")",
    re.I)
TICKET_RE = re.compile(r"\bOUT-\d{5}\b")
# "no ticket" must be a negation directly attached to ticket/record - "No problem, let me pull up our outage
# records" is not a lookup result (round-2 review).
NO_TICKET_RE = re.compile(r"\b(?:no|not finding any|not seeing any|don't see any|do not see any|don't see an|couldn't find any?|"
                          r"could not find any?|can't find any?|cannot find any?|unable to find any?|there is no|there's no)\s+"
                          r"(?:confirmed |matching |open |active )?(?:outage |NOC )?(?:ticket|record)s?\b", re.I)
# a ticket mentioned with these words IN THE SAME SENTENCE is not a confirmation for this customer
TICKET_NOT_OURS_RE = re.compile(r"\b(?:different|another|other|neighbou?r'?s?) (?:service )?(?:address|building|area)\b|"
                                r"\bnot (?:for|at|covering) your\b|\bdoes(?:n't| not) cover your (?:address|service|location)\b", re.I)
OUTAGE_MENTION_RE = re.compile(r"\b(?:outage|service (?:was|went) (?:down|out)|was down|went down|no service|without service|"
                               r"(?:internet|service|lines?|phone) (?:died|was dead|were dead|went dead|dropped)|totally dead|no signal)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", text) if x]


@dataclass
class Turn:
    time: str
    speaker: str      # "customer" | "agent"
    name: str
    text: str
    end: int = 0      # offset in the raw transcript where this turn ends (facts "as of" this turn = raw[:end])


@dataclass
class CaseFacts:
    account: str | None = None
    customer: str | None = None
    conversation_date: date | None = None
    monthly_recurring_charge: float | None = None
    identity_verified: bool = False
    disputed_item: str | None = None
    statement_date: date | None = None
    customer_reported_outage: tuple[datetime, datetime] | None = None
    customer_mentions_outage: bool = False
    noc_lookup_done: bool = False
    noc_ticket: str | None = None
    noc_outage: tuple[datetime, datetime] | None = None
    noc_unverifiable: str | None = None
    # Not present in this transcript -> stay None (= unverified)
    prior_resolved_dispute_within_90d: bool | None = None
    goodwill_credits_last_12m: float | None = None
    fraud_indicators: bool | None = None
    sources: dict = field(default_factory=dict)   # fact -> transcript line it came from

    def to_json(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat()
            elif isinstance(v, tuple):
                d[k] = [x.isoformat() for x in v]
        return d


def _month_num(s: str) -> int:
    return datetime.strptime(s.rstrip(".")[:3].title(), "%b").month


def find_datetimes(text: str, year: int, today: date | None) -> list[tuple[datetime, bool]]:
    """All dates in text as (datetime, has_time). Dates without a year are assumed to be
    in the past relative to the chat (Dec 28 in a January chat -> previous year)."""
    out = []
    for m in DT_RE.finditer(text):
        g = m.groupdict()
        try:
            if g["mon"]:
                mon, day, yr, p = _month_num(g["mon"]), int(g["day"]), g["yr"], "a"
            else:
                mon, day, yr, p = int(g["nm"]), int(g["nd"]), g["ny"], "b"
            y = int(yr) + (2000 if yr and len(yr) == 2 else 0) if yr else year
            hour = minute = 0
            has_time = False
            if g[p + "h"]:
                hour = int(g[p + "h"]) % 12 + (12 if g[p + "ap"].lower().startswith("p") else 0)
                minute, has_time = int(g[p + "m"] or 0), True
            elif g[p + "H"]:
                hour, minute, has_time = int(g[p + "H"]), int(g[p + "M"]), True
            d = datetime(y, mon, day, hour, minute)
        except (ValueError, TypeError):
            continue
        if not yr and today and d.date() > today:
            d = d.replace(year=d.year - 1)
        out.append((d, has_time))
    return out


def parse_transcript(path: str | Path) -> tuple[CaseFacts, list[Turn]]:
    return parse_text(Path(path).read_text(encoding="utf-8"))


def prefix_through(raw: str, turn: Turn) -> str:
    """Transcript text up to and including `turn` (facts known *at* that turn, no look-ahead).
    Uses the turn's offset, so two turns stamped with the same minute are handled correctly."""
    return raw[:turn.end]


TURN_RE = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm]\.?)?)\]\s*(Customer|Agent)\s*(?:\(([^)]*)\))?\s*:\s*(.+?)"
                     r"(?=\n\s*\[\d{1,2}:\d{2}|\Z)", re.S | re.I)


def parse_text(raw: str) -> tuple[CaseFacts, list[Turn]]:
    facts = CaseFacts()
    first = re.search(r"\n\s*\[\d{1,2}:\d{2}", raw)
    header = raw[:first.start()] if first else raw

    if m := re.search(r"Account Number:\s*(\S+)", header):
        facts.account = m.group(1)
    if m := re.search(r"Customer:\s*(.+)", header):
        facts.customer = m.group(1).strip()
    if m := re.search(r"^Date:\s*(.+)$", header, re.M):
        iso = re.match(r"\s*(\d{4}-\d{2}-\d{2})", m.group(1))
        ds = find_datetimes(m.group(1), datetime.now().year, None)
        if iso:
            facts.conversation_date = date.fromisoformat(iso.group(1))
        elif ds:
            facts.conversation_date = ds[0][0].date()
    if m := re.search(r"\$([\d,]+\.\d{2})\s*/\s*month", header):
        facts.monthly_recurring_charge = float(m.group(1).replace(",", ""))
        facts.sources["monthly_recurring_charge"] = m.group(0)

    turns = [Turn(m.group(1), m.group(2).lower(), (m.group(3) or "").strip(), " ".join(m.group(4).split()), m.end())
             for m in TURN_RE.finditer(raw, first.start() if first else len(raw))]

    year = facts.conversation_date.year if facts.conversation_date else datetime.now().year
    today = facts.conversation_date
    for t in turns:
        if t.speaker == "agent":
            if re.search(r"\byou're verified\b|\byou are verified\b|\bthat matches\b", t.text, re.I):
                facts.identity_verified = True
                facts.sources["identity_verified"] = f"[{t.time}] {t.text[:80]}"
            ours = []          # (ticket, sentence) confirmed for this customer, judged sentence by sentence
            for sent in _sentences(t.text):
                for tk in TICKET_RE.findall(sent):
                    if not TICKET_NOT_OURS_RE.search(sent) and tk not in [x for x, _ in ours]:
                        ours.append((tk, sent))
            mentioned = bool(TICKET_RE.search(t.text))
            if ours:
                facts.noc_lookup_done = True
                facts.noc_ticket = ours[0][0]
                facts.sources["noc_ticket"] = f"[{t.time}] agent NOC lookup: {t.text[:160]}"
                if len(ours) > 1:
                    facts.noc_ticket = ", ".join(x for x, _ in ours)
                    facts.noc_outage = None
                    facts.noc_unverifiable = (f"{len(ours)} tickets ({facts.noc_ticket}) - combined coverage and overlap "
                                              "must be verified before computing one credit")
                else:
                    dts = find_datetimes(ours[0][1], year, today) or find_datetimes(t.text, year, today)
                    if len(dts) >= 2 and dts[0][1] and dts[1][1] and dts[1][0] > dts[0][0]:
                        facts.noc_outage = (dts[0][0], dts[1][0])
                        facts.noc_unverifiable = None
                    else:
                        facts.noc_outage = None
                        facts.noc_unverifiable = ("ticket found but its start/end date-times could not be read precisely "
                                                  f"from the lookup ({len(dts)} date(s) found)")
            elif mentioned or NO_TICKET_RE.search(t.text):
                # lookup happened but no ticket confirmed for this address/dates
                facts.noc_lookup_done = True
                facts.noc_ticket, facts.noc_outage, facts.noc_unverifiable = None, None, None
                facts.sources["noc_ticket"] = f"[{t.time}] agent NOC lookup found no matching ticket: {t.text[:160]}"
        else:
            if OUTAGE_MENTION_RE.search(t.text):
                facts.customer_mentions_outage = True
            dts = find_datetimes(t.text, year, today)
            if len(dts) >= 2 and facts.customer_reported_outage is None and dts[1][0] > dts[0][0]:
                facts.customer_reported_outage = (dts[0][0], dts[1][0])
                facts.sources["customer_reported_outage"] = f"[{t.time}] {t.text[:120]}"
            if m := re.search(r"(?:invoice|statement|bill)\s+dated\s+(.{3,30})", t.text, re.I):
                sd = find_datetimes(m.group(1), year, today)
                if sd:
                    facts.statement_date = sd[0][0].date()
                    facts.sources["statement_date"] = f"[{t.time}] {m.group(0)[:40]}"
            if m := re.search(r"disputing (?:the )?(full )?\$([\d,]+\.\d{2}) ([a-z ]+?charge)", t.text, re.I):
                facts.disputed_item = f"${m.group(2)} {m.group(3)}"
                facts.sources["disputed_item"] = f"[{t.time}] {m.group(0)}"
    return facts, turns
