import re
from decimal import Decimal
from difflib import SequenceMatcher

from pydantic import BaseModel

from sop_agent.data.normalize import norm_dob
from sop_agent.data.repository import Repository

_CASE_ID = re.compile(r"\bCL-\d+\b", re.I)
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_MONEY = re.compile(rf"\$\s?{_NUMBER}(?:\.\d{{2}})?|(?<![\d.]){_NUMBER}\.\d{{2}}(?!\d|\.\d)")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_DATE = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b{_MONTH}\.? \d{{1,2}}(?:st|nd|rd|th)?,? \d{{4}}\b", re.I)
MIN_REASON_OVERLAP = 20


class GuardResult(BaseModel):
    ok: bool
    reasons: list[str] = []


def _facts(text: str) -> dict[str, set[str]]:
    """Case IDs, money amounts (2dp, no symbols) and dates (ISO) mentioned in free text."""
    return {
        "case id": {m.upper() for m in _CASE_ID.findall(text)},
        "amount": {f"{Decimal(re.sub(r'[$,\s]', '', m)):.2f}" for m in _MONEY.findall(text)},
        "date": {norm_dob(m) or m for m in _DATE.findall(text)},
    }


def check_pre_verification(reply: str, repo: Repository) -> GuardResult:
    """Before the caller is verified a reply must carry no claim data at all."""
    found = _facts(reply)
    claim_dates = {d.isoformat() for c in repo.claims for d in (c.created_at, c.appeal_deadline) if d}
    reasons = [f"claim {kind} in reply" for kind in ("case id", "amount") if found[kind]]
    if found["date"] & claim_dates:
        reasons.append("claim date in reply")
    lowered = reply.lower()
    for claim in repo.claims:
        reason = (claim.denial_reason or "").lower()
        match = SequenceMatcher(None, lowered, reason, autojunk=False).find_longest_match(
            0, len(lowered), 0, len(reason)
        )
        if match.size >= MIN_REASON_OVERLAP:
            reasons.append("denial reason in reply")
    return GuardResult(ok=not reasons, reasons=reasons)


def check_grounding(reply: str, evidence: list[str]) -> GuardResult:
    """Every case ID, amount and date in the reply must appear in the evidence."""
    allowed = _facts("\n".join(evidence))
    reasons = [
        f"ungrounded {kind}: {value}"
        for kind, values in _facts(reply).items()
        for value in sorted(values - allowed[kind])
    ]
    return GuardResult(ok=not reasons, reasons=reasons)
