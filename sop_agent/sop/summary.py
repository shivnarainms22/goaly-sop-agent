from sop_agent.data.repository import Repository
from sop_agent.sop.state import EmailMessage, SessionState


def build_email_summary(state: SessionState, repo: Repository) -> EmailMessage:
    """Deterministic summary of what was disclosed, built from the ledger and the selected claim only."""
    party_id = state.identity.verified_party_id
    if party_id is None:
        raise ValueError("cannot build a summary for an unverified session")
    claim = (
        repo.claim_for_party(party_id, state.case.selected_case_id) if state.case.selected_case_id else None
    )

    discussed = [e.text for e in state.ledger if e.kind == "fact"] or ["No claim details were discussed."]
    next_steps = [e.text for e in state.ledger if e.kind == "next_step"] or ["No follow-up actions."]
    status = (
        f"Claim {claim.case_id} ({claim.case_type}): {claim.status}. {claim.summary}."
        if claim
        else "No claim was discussed."
    )
    lines = [
        "Hello,",
        "",
        "Here is a summary of your call with us.",
        "",
        "What we discussed",
        *(f"- {t}" for t in discussed),
        "",
        "Claim status",
        status,
        "",
        "Next steps",
        *(f"- {t}" for t in next_steps),
    ]
    return EmailMessage(
        to=repo.policyholder(party_id).email,
        subject=f"Summary of your call about claim {claim.case_id}" if claim else "Summary of your call",
        body="\n".join(lines),
    )
