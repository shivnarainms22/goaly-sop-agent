from sop_agent.data.repository import Repository


def test_loads_fixtures():
    repo = Repository.load()
    assert {p.party_id for p in repo.policyholders} == {"P9", "P7", "P12", "P13"}
    assert [c.case_id for c in repo.claims_for("P9")] == ["CL-2048", "CL-2011", "CL-1899", "CL-2102"]
    assert repo.claims_for("P7") == []
    assert repo.representatives_for("P9")[0].rep_name == "David Chen"
    assert repo.consent_scenarios["default"] == ["pending", "approved"]


def test_policyholder_aliases_normalized():
    p = Repository.load().policyholder("P13")
    assert "yaven li" in p.name_set and "ya wen li" in p.name_set
    assert "yawen.li@example.com" in p.email_set


def test_claim_for_party_is_scoped():
    repo = Repository.load()
    assert repo.claim_for_party("P9", "CL-2048").status == "denied"
    assert repo.claim_for_party("P9", "CL-3001") is None  # belongs to P12
    assert repo.claim_for_party("P9", "cl-2048").case_id == "CL-2048"  # case-insensitive


def test_unknown_policyholder_is_none():
    assert Repository.load().policyholder("P404") is None
