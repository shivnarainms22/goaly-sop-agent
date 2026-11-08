import pytest

from sop_agent.data.normalize import mask_email
from sop_agent.data.repository import Repository
from sop_agent.sop.state import LedgerEntry, SessionState
from sop_agent.sop.summary import build_email_summary

R = Repository.load()


def verified_state(with_ledger: bool = True) -> SessionState:
    s = SessionState.new()
    s.identity.verified_party_id = "P9"
    s.identity.provided = {"dob": "1985-03-15", "id_last4": "4472"}
    s.case.selected_case_id = "CL-2048"
    if with_ledger:
        s.ledger = [
            LedgerEntry(
                kind="fact",
                text="Claim CL-2048 was denied: missing pathology report and office note",
                source="ANSWER_CASE",
            ),
            LedgerEntry(
                kind="next_step",
                text="Upload the pathology report and office note via the member portal",
                source="ANSWER_CASE",
            ),
        ]
    return s


def test_summary_has_sections_status_and_next_step():
    m = build_email_summary(verified_state(), R)
    assert m.to == "margaret@email.com" and "CL-2048" in m.subject
    for heading in ("What we discussed", "Claim status", "Next steps"):
        assert heading in m.body
    assert "denied" in m.body
    assert "Claim CL-2048 was denied: missing pathology report and office note" in m.body
    assert "Upload the pathology report and office note via the member portal" in m.body


def test_summary_contains_no_identity_data():
    body = build_email_summary(verified_state(), R).body
    assert "4472" not in body and "1985-03-15" not in body


def test_empty_ledger_still_renders():
    m = build_email_summary(verified_state(with_ledger=False), R)
    assert "No follow-up actions" in m.body and "Next steps" in m.body


def test_no_selected_case_still_renders():
    s = verified_state(with_ledger=False)
    s.case.selected_case_id = None
    m = build_email_summary(s, R)
    assert m.to == "margaret@email.com" and "No claim was discussed" in m.body


def test_unverified_session_cannot_build_summary():
    with pytest.raises(ValueError):
        build_email_summary(SessionState.new(), R)


@pytest.mark.parametrize(
    "raw,exp",
    [
        ("margaret@email.com", "m*******@email.com"),
        ("a@x.com", "*@x.com"),
        ("ab@x.com", "a*@x.com"),
        ("not an email", None),
        (None, None),
    ],
)
def test_mask_email(raw, exp):
    assert mask_email(raw) == exp
