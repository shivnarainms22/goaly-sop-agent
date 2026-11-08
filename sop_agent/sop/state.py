from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from sop_agent.data.normalize import mask_email


class Phase(StrEnum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    ENDED = "ENDED"
    HANDOFF = "HANDOFF"


class Identity(BaseModel):
    provided: dict[str, str] = {}  # normalized PII: full_name, dob, phone, email, id_last4
    policy_number: str | None = None
    caller_role: Literal["self", "representative", "unknown"] = "unknown"
    rep_name: str | None = None
    relationship: str | None = None
    verified_party_id: str | None = None
    failed_attempts: int = 0


class Consent(BaseModel):
    status: Literal["not_required", "pending", "approved", "timed_out"] = "not_required"
    scenario: str = "default"
    poll_index: int = 0


class Memory(BaseModel):
    intent: str | None = None
    case_type: str | None = None
    month: int | None = None
    year: int | None = None
    status: str | None = None
    case_id: str | None = None
    documents_mentioned: list[str] = []
    notes: list[str] = []


class CaseSelection(BaseModel):
    selected_case_id: str | None = None
    candidate_case_ids: list[str] = []


class Counters(BaseModel):
    off_topic_strikes: int = 0
    refusals: dict[str, int] = {}  # per phase
    human_offered: bool = False


class LedgerEntry(BaseModel):
    kind: Literal["fact", "next_step"]
    text: str
    source: str


class EmailMessage(BaseModel):
    to: str
    subject: str
    body: str


class EmailState(BaseModel):
    offered: bool = False
    decision: Literal["pending", "send", "skip"] = "pending"
    outbox: list[EmailMessage] = []


class SessionState(BaseModel):
    phase: Phase = Phase.VERIFY_ID
    identity: Identity = Identity()
    consent: Consent = Consent()
    memory: Memory = Memory()
    case: CaseSelection = CaseSelection()
    counters: Counters = Counters()
    ledger: list[LedgerEntry] = []
    email: EmailState = EmailState()
    transcript: list[dict[str, str]] = []  # {"role": "user"|"assistant", "text": ...}
    trace: list[dict] = []

    @classmethod
    def new(cls, consent_scenario: str = "default") -> "SessionState":
        return cls(consent=Consent(scenario=consent_scenario))

    def snapshot(self) -> dict:
        """JSON-safe view for the UI: PII values are never included, only which fields were provided."""
        identity = self.identity
        return {
            "phase": self.phase.value,
            "identity": {
                "provided_fields": list(identity.provided),
                "policy_number_provided": identity.policy_number is not None,
                "caller_role": identity.caller_role,
                "verified": identity.verified_party_id is not None,
                "failed_attempts": identity.failed_attempts,
            },
            "consent": self.consent.model_dump(),
            "memory": self.memory.model_dump(),
            "case": self.case.model_dump(),
            "counters": self.counters.model_dump(),
            "ledger": [e.model_dump() for e in self.ledger],
            "email": {
                "offered": self.email.offered,
                "decision": self.email.decision,
                "outbox": [{**m.model_dump(), "to": mask_email(m.to)} for m in self.email.outbox],
            },
        }
