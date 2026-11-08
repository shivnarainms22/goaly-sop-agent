from enum import StrEnum

from pydantic import BaseModel


class ActionKind(StrEnum):
    ASK_IDENTITY = "ASK_IDENTITY"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    VERIFIED = "VERIFIED"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_TIMEOUT = "CONSENT_TIMEOUT"
    CASE_SELECTED = "CASE_SELECTED"
    CLARIFY_CASE = "CLARIFY_CASE"
    ASK_INTENT = "ASK_INTENT"
    ANSWER_CASE = "ANSWER_CASE"
    OFFER_EMAIL = "OFFER_EMAIL"
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_SKIPPED = "EMAIL_SKIPPED"
    DECLINE_OFF_TOPIC = "DECLINE_OFF_TOPIC"
    SMALLTALK = "SMALLTALK"
    OFFER_HUMAN = "OFFER_HUMAN"
    HANDOFF = "HANDOFF"
    CLOSED = "CLOSED"


class Action(BaseModel):
    """What the engine decided to do. `facts` is everything the template (and phraser) may use."""

    kind: ActionKind
    facts: dict = {}
