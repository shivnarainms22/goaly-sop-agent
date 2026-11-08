import re
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from pydantic import BaseModel

from sop_agent.data.repository import Repository

MIN_REASON_OVERLAP = 20
MIN_LEAKY_AMOUNT = 100
_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]  # fmt: skip
_MONTH_DAY = re.compile(rf"\b({'|'.join(m[:3] for m in _MONTHS)})[a-z]*\.? \d{{1,2}}\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


class GuardResult(BaseModel):
    ok: bool
    reasons: list[str] = []


def _normalize(text: str) -> str:
    """Lowercase and drop thousands separators (1,450 -> 1450)."""
    return re.sub(r"(?<=\d),(?=\d)", "", text.lower())


def _digit_run(digits: str) -> str:
    return rf"(?<!\d){digits}(?!\d)"


def _date_patterns(d: date) -> list[str]:
    # Built by hand: Windows strftime has no %-d.
    forms = [
        d.isoformat(),
        f"{d.month}/{d.day}/{d.year}",
        f"{d.month:02}/{d.day:02}/{d.year}",
        f"{d.month}/{d.day}",
    ]
    for month in {_MONTHS[d.month - 1], _MONTHS[d.month - 1][:3]}:
        forms += [f"{month} {d.day}", f"{d.day} {month}"]
    return [rf"\b{re.escape(form)}(?:st|nd|rd|th)?\b" for form in forms]


def _shares_long_substring(text: str, reason: str) -> bool:
    match = SequenceMatcher(None, text, reason, autojunk=False).find_longest_match(
        0, len(text), 0, len(reason)
    )
    return match.size >= MIN_REASON_OVERLAP


def check_pre_verification(reply: str, repo: Repository) -> GuardResult:
    """Before the caller is verified a reply must carry no claim data at all (checked against every claim)."""
    text = _normalize(reply)
    claims = repo.claims
    case_numbers = {re.sub(r"\D", "", c.case_id) for c in claims} - {""}
    amounts = {
        str(int(Decimal(a)))
        for c in claims
        for a in (c.expected_reimbursement_amount, c.allowed_max_amount, c.net_pay, c.net_fee)
        if Decimal(a) >= MIN_LEAKY_AMOUNT
    }
    dates = {p for c in claims for d in (c.created_at, c.appeal_deadline) if d for p in _date_patterns(d)}
    phrases = {t.lower() for c in claims for t in (c.summary, *c.documents_needed) if t}
    checks = {
        "claim case number in reply": any(re.search(_digit_run(n), text) for n in case_numbers),
        "claim amount in reply": any(re.search(_digit_run(a), text) for a in amounts),
        "claim date in reply": any(re.search(p, text) for p in dates),
        "claim text in reply": any(p in text for p in phrases),
        "denial reason in reply": any(
            _shares_long_substring(text, (c.denial_reason or "").lower()) for c in claims
        ),
    }
    reasons = [reason for reason, hit in checks.items() if hit]
    return GuardResult(ok=not reasons, reasons=reasons)


def check_grounding(reply: str, evidence: list[str]) -> GuardResult:
    """Every number in the reply must appear in the evidence (an ISO date also yields year, month, day)."""
    facts = _normalize("\n".join(evidence))
    allowed = {str(int(n)) for n in re.findall(r"\d+", facts)}
    months = {m[:3] for m in _MONTHS if re.search(rf"\b{m[:3]}", facts)}
    for year, month, day in _ISO_DATE.findall(facts):
        allowed |= {year, str(int(month)), str(int(day))}
        months.add(_MONTHS[int(month) - 1][:3] if 1 <= int(month) <= 12 else "")
    text = _normalize(reply)
    ungrounded = sorted({str(int(n)) for n in re.findall(r"\d+", text)} - allowed, key=int)
    reasons = [f"ungrounded numbers: {', '.join(ungrounded)}"] if ungrounded else []
    reasons += [f"ungrounded month: {m}" for m in _MONTH_DAY.findall(text) if m not in months]
    return GuardResult(ok=not reasons, reasons=reasons)
