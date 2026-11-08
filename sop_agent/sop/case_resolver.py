from enum import StrEnum

from pydantic import BaseModel

from sop_agent.data.repository import Claim
from sop_agent.sop.state import Memory


class Kind(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"
    NO_HINTS = "NO_HINTS"


class CaseResolution(BaseModel):
    kind: Kind
    case_id: str | None = None
    candidates: list[str] = []


def resolve_case(memory: Memory, claims: list[Claim]) -> CaseResolution:
    """Pick the caller's claim from remembered hints. `claims` must already be scoped to the verified party.
    Several matches are never auto-resolved: the caller is asked to clarify."""
    if memory.case_id:
        matches = [c for c in claims if c.case_id.lower() == memory.case_id.lower()]
    elif all(v is None for v in (memory.case_type, memory.status, memory.month, memory.year)):
        return CaseResolution(kind=Kind.NO_HINTS)
    else:
        matches = [
            c
            for c in claims
            if memory.case_type in (None, c.case_type)
            and memory.status in (None, c.status)
            and memory.month in (None, c.created_at.month)
            and memory.year in (None, c.created_at.year)
        ]
    ids = [c.case_id for c in matches]
    if len(ids) == 1:
        return CaseResolution(kind=Kind.RESOLVED, case_id=ids[0], candidates=ids)
    return CaseResolution(kind=Kind.AMBIGUOUS if ids else Kind.NO_MATCH, candidates=ids)
