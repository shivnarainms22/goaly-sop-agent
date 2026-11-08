from sop_agent.sop.actions import Action, ActionKind
from sop_agent.sop.extraction import Emotion

_FIELD_LABELS = {
    "full_name": "full name",
    "dob": "date of birth",
    "phone": "phone number",
    "email": "email address",
    "id_last4": "the last 4 digits of your SSN/national ID",
}
_OPENERS = {
    "frustrated": "I'm sorry for the frustration, and thank you for your patience.",
    "angry": "I'm sorry this has been so upsetting; I want to help get it sorted.",
    "anxious": "I understand this is stressful, and I'm here to help.",
    "confused": "No worries, I'll walk you through it step by step.",
}
_WHY_PROTECTED = (
    "Claim details are protected, and verifying your identity is what keeps the policyholder safe."
)


def _fields(fields: list[str]) -> str:
    labels = [_FIELD_LABELS[f] for f in fields]
    return ", ".join(labels[:-1]) + ", or " + labels[-1] if len(labels) > 1 else labels[0]


def _ask_identity(f: dict) -> str:
    still = f["fields_still_accepted"]
    if f["details_still_needed"] == 0:
        ask = ""
    elif f["details_still_needed"] == f["matched_count_needed"]:
        ask = (
            "I can help with that, but first I need to verify your identity. "
            f"Please share any {f['matched_count_needed']} of: {_fields(still)}."
        )
    else:
        ask = f"Thank you. I still need {f['details_still_needed']} more of: {_fields(still)}."
    parts = [_WHY_PROTECTED] if f.get("refusal") else []
    if ask:
        parts.append(ask)
    if f.get("ask_rep_name"):
        parts.append("As you're calling on someone's behalf, please also tell me your own full name.")
    return " ".join(parts)


def _clarify_case(f: dict) -> str:
    claims = "; ".join(
        f"{c['case_id']} ({c['case_type']}, {c['month_name']} {c['year']}, {c['status']})"
        for c in f["candidates"]
    )
    return f"I found these claims: {claims}. Which one would you like to talk about?"


_TEMPLATES = {
    ActionKind.ASK_IDENTITY: _ask_identity,
    ActionKind.IDENTITY_MISMATCH: lambda f: (
        "I couldn't verify your identity with the details provided. "
        f"Please double-check and share {f['matched_count_needed']} of: "
        f"{_fields(f['fields_still_accepted'])}."
    ),
    ActionKind.VERIFIED: lambda f: "Thank you, you're verified.",
    ActionKind.CONSENT_PENDING: lambda f: (
        "Thank you. As you're calling on behalf of the policyholder, I've sent them a consent request. "
        "Send me a message in a moment and I'll check whether they've approved."
    ),
    ActionKind.CONSENT_TIMEOUT: lambda f: (
        "The policyholder hasn't approved the consent request, so I can't share any claim information."
    ),
    ActionKind.CASE_SELECTED: lambda f: (
        f"I've pulled up your {f['case_type']} claim {f['case_id']} (status: {f['status']})."
    ),
    ActionKind.CLARIFY_CASE: _clarify_case,
    ActionKind.ASK_INTENT: lambda f: "How can I help you with your claims today?",
    ActionKind.ANSWER_CASE: lambda f: f"Here is what I have on claim {f['case_id']}: status {f['status']}.",
    ActionKind.OFFER_EMAIL: lambda f: f"Would you like me to email a summary to {f['masked_email']}?",
    ActionKind.EMAIL_SENT: lambda f: "Done, I've sent the summary. Take care!",
    ActionKind.EMAIL_SKIPPED: lambda f: "No problem, I won't send an email. Take care!",
    ActionKind.DECLINE_OFF_TOPIC: lambda f: (
        "I'm sorry, I can only help with insurance claims and related questions."
    ),
    ActionKind.SMALLTALK: lambda f: "Happy to help.",
    ActionKind.OFFER_HUMAN: lambda f: "If you'd prefer, I can transfer you to a human representative.",
    ActionKind.HANDOFF: lambda f: (
        "I'm transferring you to a human representative now, with a note so you won't repeat yourself."
    ),
    ActionKind.CLOSED: lambda f: (
        "This conversation has ended. Please start a new session if you need more help."
    ),
}


def render(actions: list[Action], emotion: Emotion) -> str:
    """Deterministic reply: empathy opener (non-neutral emotion) followed by each action's template."""
    parts = [_OPENERS[emotion.label]] if emotion.label in _OPENERS else []
    parts += [_TEMPLATES[a.kind](a.facts) for a in actions]
    return " ".join(parts)
