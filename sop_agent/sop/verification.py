from enum import StrEnum

from pydantic import BaseModel

from sop_agent.data.normalize import norm_name
from sop_agent.data.repository import Policyholder, Repository

PII_FIELDS = ("full_name", "dob", "phone", "email", "id_last4")
REQUIRED_MATCHES = 3


class Status(StrEnum):
    VERIFIED = "VERIFIED"
    NEED_MORE = "NEED_MORE"
    MISMATCH = "MISMATCH"


class VerificationResult(BaseModel):
    status: Status
    party_id: str | None = None
    matched_count: int = 0
    fields_still_accepted: list[str]
    conflicting_fields: list[str] = []  # internal only: never shown to the LLM or the caller


def _field_matches(p: Policyholder, field: str, value: str) -> bool:
    if field == "full_name":
        return value in p.name_set
    if field == "phone":
        return value in p.phone_set
    if field == "email":
        return value in p.email_set
    return value == getattr(p, field)


def verify_identity(
    provided: dict[str, str], policy_number: str | None, repo: Repository
) -> VerificationResult:
    given = {f: provided[f] for f in PII_FIELDS if provided.get(f)}
    still = [f for f in PII_FIELDS if f not in given]
    if len(given) < REQUIRED_MATCHES:
        return VerificationResult(status=Status.NEED_MORE, fields_still_accepted=still)

    # The policy number only narrows the candidates; it never counts as a match.
    candidates = repo.policyholders
    if policy_number:
        candidates = [p for p in candidates if p.policy_number.lower() == policy_number.lower()]

    scored = []
    for p in candidates:
        matched = [f for f, v in given.items() if _field_matches(p, f, v)]
        scored.append((p, len(matched), [f for f in given if f not in matched]))
    clean = [(p, n) for p, n, conflicts in scored if n >= REQUIRED_MATCHES and not conflicts]
    if len(clean) == 1:
        party, count = clean[0]
        return VerificationResult(
            status=Status.VERIFIED, party_id=party.party_id, matched_count=count, fields_still_accepted=still
        )
    _, best_count, best_conflicts = max(scored, key=lambda s: s[1], default=(None, 0, list(given)))
    return VerificationResult(
        status=Status.MISMATCH,
        matched_count=best_count,
        fields_still_accepted=still,
        conflicting_fields=best_conflicts,
    )


def verify_representative(
    rep_name: str | None, provided: dict[str, str], policy_number: str | None, repo: Repository
) -> VerificationResult:
    """Policyholder PII must verify AND the caller must be a registered representative of that person."""
    result = verify_identity(provided, policy_number, repo)
    if result.status is not Status.VERIFIED:
        return result
    known = {norm_name(r.rep_name) for r in repo.representatives_for(result.party_id)}
    if norm_name(rep_name) in known:
        return result
    return result.model_copy(
        update={"status": Status.MISMATCH, "party_id": None, "conflicting_fields": ["rep_name"]}
    )
