from sop_agent.data.repository import Repository
from sop_agent.sop.case_resolver import Kind, resolve_case
from sop_agent.sop.state import Memory

C = Repository.load().claims_for("P9")


def test_denied_healthcare_january_resolves_cl2048():
    r = resolve_case(Memory(case_type="healthcare", status="denied", month=1), C)
    assert r.kind is Kind.RESOLVED and r.case_id == "CL-2048"


def test_healthcare_january_alone_is_ambiguous():  # CL-2048 (2026-01) and CL-2011 (2025-01)
    r = resolve_case(Memory(case_type="healthcare", month=1), C)
    assert r.kind is Kind.AMBIGUOUS and set(r.candidates) == {"CL-2048", "CL-2011"} and r.case_id is None


def test_year_disambiguates():
    assert resolve_case(Memory(case_type="healthcare", month=1, year=2025), C).case_id == "CL-2011"


def test_explicit_case_id_wins_and_is_scoped():
    assert resolve_case(Memory(case_id="cl-2102"), C).case_id == "CL-2102"
    assert resolve_case(Memory(case_id="CL-3001"), C).kind is Kind.NO_MATCH


def test_explicit_case_id_beats_conflicting_hints():
    assert resolve_case(Memory(case_id="CL-2102", case_type="healthcare"), C).case_id == "CL-2102"


def test_single_claim_of_type():
    assert resolve_case(Memory(case_type="auto"), C).case_id == "CL-2102"


def test_no_hints():
    assert resolve_case(Memory(), C).kind is Kind.NO_HINTS
    assert resolve_case(Memory(intent="denial_question"), C).kind is Kind.NO_HINTS


def test_no_match():
    assert resolve_case(Memory(case_type="life"), C).kind is Kind.NO_MATCH


def test_no_claims_at_all():
    assert resolve_case(Memory(case_type="auto"), []).kind is Kind.NO_MATCH
