from typing import Literal

from pydantic import BaseModel, Field

from sop_agent.data.normalize import norm_dob, norm_email, norm_last4, norm_name, norm_phone
from sop_agent.sop.state import SessionState

Intent = Literal[
    "denial_question",
    "status_inquiry",
    "document_submission",
    "next_steps",
    "payment_question",
    "general_claim_question",
    "new_claim",
    "other",
    "none",
]


class PII(BaseModel):
    full_name: str | None = None
    dob: str | None = None
    phone: str | None = None
    email: str | None = None
    id_last4: str | None = None


class CaseHints(BaseModel):
    case_type: str | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = None
    status: str | None = None
    case_id: str | None = None


class Emotion(BaseModel):
    label: Literal["neutral", "frustrated", "anxious", "angry", "confused"] = "neutral"
    intensity: int = Field(default=0, ge=0, le=3)


class TurnExtraction(BaseModel):
    pii: PII = PII()
    policy_number: str | None = None
    caller_role: Literal["self", "representative", "unknown"] = "unknown"
    rep_name: str | None = None
    relationship: str | None = None
    intent: Intent = "none"
    case_hints: CaseHints = CaseHints()
    documents_mentioned: list[str] = []
    scope: Literal["in_scope", "off_topic", "smalltalk"] = "in_scope"
    emotion: Emotion = Emotion()
    refusal: bool = False
    wants_human: bool = False
    email_decision: Literal["send", "skip", "none"] = "none"
    done_with_case: bool = False
    wants_other_case: bool = False


_PII_NORMALIZERS = {
    "full_name": norm_name,
    "dob": norm_dob,
    "phone": norm_phone,
    "email": norm_email,
    "id_last4": norm_last4,
}


def merge_into_state(state: SessionState, ex: TurnExtraction) -> None:
    """Remember what the caller said, in any phase. Never changes the phase."""
    identity, memory = state.identity, state.memory
    for field, normalize in _PII_NORMALIZERS.items():
        value = normalize(getattr(ex.pii, field))
        if value:
            identity.provided[field] = value
    if ex.policy_number and ex.policy_number.strip():
        identity.policy_number = ex.policy_number.strip().upper()
    identity.rep_name = ex.rep_name or identity.rep_name
    identity.relationship = ex.relationship or identity.relationship
    # Representative is sticky and implied by any rep detail: a role switch must never skip consent.
    if ex.caller_role == "representative" or identity.rep_name or identity.relationship:
        identity.caller_role = "representative"
    elif ex.caller_role == "self" and identity.caller_role != "representative":
        identity.caller_role = "self"

    if ex.intent != "none" and not (ex.intent == "other" and memory.intent):
        memory.intent = ex.intent
    for field, value in ex.case_hints:
        if value is not None:
            setattr(memory, field, value)
    for doc in ex.documents_mentioned:
        if doc not in memory.documents_mentioned:
            memory.documents_mentioned.append(doc)
