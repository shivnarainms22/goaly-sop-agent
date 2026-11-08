from sop_agent.sop.extraction import TurnExtraction
from sop_agent.sop.state import SessionState

REFUSALS_BEFORE_ESCALATION = 2
ANGRY_ESCALATION_INTENSITY = 3


def disclosure_allowed(state: SessionState) -> bool:
    """Claim data may be disclosed only to a verified caller (and, for a representative, with consent)."""
    return state.identity.verified_party_id is not None and state.consent.status in (
        "not_required",
        "approved",
    )


def should_escalate(state: SessionState, ex: TurnExtraction) -> bool:
    """Offer a human (never relax a gate) after repeated refusals in this phase or a very angry caller."""
    refusals = state.counters.refusals.get(state.phase.value, 0)
    angry = ex.emotion.label == "angry" and ex.emotion.intensity >= ANGRY_ESCALATION_INTENSITY
    return refusals >= REFUSALS_BEFORE_ESCALATION or angry
