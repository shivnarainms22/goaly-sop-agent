from datetime import date

from sop_agent.data.repository import Repository
from sop_agent.sop.case_facts import build_case_bundle, claim_facts, document_guidance, followup_guidance

R = Repository.load()
C = R.claim_for_party("P9", "CL-2048")


def test_deadline_passed_flag():
    assert claim_facts(C, date(2026, 11, 7))["appeal_deadline_passed"] is True
    early = claim_facts(C, date(2026, 3, 1))
    assert early["appeal_deadline_passed"] is False and early["days_until_appeal_deadline"] == 17


def test_deadline_day_itself_is_not_passed():
    assert claim_facts(C, date(2026, 3, 18))["appeal_deadline_passed"] is False


def test_closed_claim_has_no_deadline_fields():
    f = claim_facts(R.claim_for_party("P9", "CL-2011"), date(2026, 11, 7))
    assert "appeal_deadline_passed" not in f
    assert f["created_at"] == "2025-01-28" and f["net_pay"] == "780.00"


def test_document_guidance_fuzzy():
    g = document_guidance(R, "pathology report", "healthcare")
    assert g["matched_key"] == "original pathology report" and "replacement copy" in g["alternatives"]
    assert "treating provider" in g["case_type_guidance"]
    assert document_guidance(R, "office note", "healthcare")["matched_key"] == "treating provider office note"
    assert document_guidance(R, "blood sample", "healthcare")["matched_key"] is None


def test_unmatched_document_gets_default_guidance():
    g = document_guidance(R, "blood sample", "dental")
    assert g["guidance"] == R.guidelines["default_guidance"]["en"]
    assert g["alternatives"] == R.guidelines["document_alternative_guidance"]["default"]["en"]
    assert g["case_type_guidance"] is None


def test_followup_processing_time():
    text = " ".join(followup_guidance(R, C, "how long does it take after I submit?", "next_steps"))
    assert "usually less than a week" in text and "CL-2048" in text and "{" not in text


def test_followup_none_matches():
    assert followup_guidance(R, C, "can I visit in person?", "other") == []


def test_followups_skipped_when_claim_needs_no_documents():
    closed = R.claim_for_party("P9", "CL-2011")
    assert followup_guidance(R, closed, "how long does it take?", "status_inquiry") == []


def test_bundle_is_deterministic_and_has_fallback():
    a = build_case_bundle(R, C, "other", "can I visit in person?", date(2026, 11, 7))
    b = build_case_bundle(R, C, "other", "can I visit in person?", date(2026, 11, 7))
    assert a == b and a["followups"] == [] and a["fallback"]
    assert [d["matched_key"] for d in a["documents"]] == [
        "original pathology report",
        "treating provider office note",
    ]
