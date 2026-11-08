from sop_agent.data.repository import Repository
from sop_agent.sop.verification import Status, verify_identity, verify_representative

R = Repository.load()


def test_brief_demo_case_verifies():
    r = verify_identity(
        {"full_name": "margaret chen", "dob": "1985-03-15", "id_last4": "4472"}, "POL-9921", R
    )
    assert r.status is Status.VERIFIED and r.party_id == "P9"


def test_two_fields_need_more_and_lists_alternatives():
    r = verify_identity({"full_name": "margaret chen", "dob": "1985-03-15"}, None, R)
    assert r.status is Status.NEED_MORE and r.party_id is None
    assert set(r.fields_still_accepted) == {"phone", "email", "id_last4"}


def test_policy_number_does_not_count():
    r = verify_identity({"full_name": "margaret chen", "dob": "1985-03-15"}, "POL-9921", R)
    assert r.status is Status.NEED_MORE


def test_alias_fields_count():
    r = verify_identity(
        {"full_name": "yaven li", "email": "yawen.li@example.com", "dob": "1989-12-03"}, None, R
    )
    assert r.status is Status.VERIFIED and r.party_id == "P13"


def test_national_id_last4_accepted_as_id_last4():
    r = verify_identity({"full_name": "ma tian", "dob": "1964-09-10", "id_last4": "6688"}, None, R)
    assert r.status is Status.VERIFIED and r.party_id == "P12"


def test_three_fields_one_wrong_is_mismatch_not_verified():
    r = verify_identity({"full_name": "margaret chen", "dob": "1985-03-15", "id_last4": "0000"}, None, R)
    assert r.status is Status.MISMATCH and r.party_id is None


def test_four_matching_plus_one_conflict_is_mismatch():
    r = verify_identity(
        {
            "full_name": "margaret chen",
            "dob": "1985-03-15",
            "id_last4": "4472",
            "phone": "+16505212836",
            "email": "wrong@x.com",
        },
        None,
        R,
    )
    assert r.status is Status.MISMATCH


def test_fields_from_different_people_do_not_combine():
    r = verify_identity({"full_name": "margaret chen", "dob": "1990-08-21", "id_last4": "9180"}, None, R)
    assert r.status is Status.MISMATCH  # Ava's dob/ssn


def test_policy_number_pointing_elsewhere_is_mismatch():
    r = verify_identity(
        {"full_name": "margaret chen", "dob": "1985-03-15", "id_last4": "4472"}, "POL-1044", R
    )
    assert r.status is Status.MISMATCH


def test_unknown_policy_number_is_mismatch_once_enough_fields():
    r = verify_identity(
        {"full_name": "margaret chen", "dob": "1985-03-15", "id_last4": "4472"}, "POL-0000", R
    )
    assert r.status is Status.MISMATCH


def test_empty_input():
    assert verify_identity({}, None, R).status is Status.NEED_MORE


def test_representative_verifies_for_policyholder():
    r = verify_representative(
        "david chen", {"full_name": "margaret chen", "dob": "1985-03-15", "phone": "+16505212836"}, None, R
    )
    assert r.status is Status.VERIFIED and r.party_id == "P9"


def test_unknown_representative_rejected():
    r = verify_representative(
        "eve smith", {"full_name": "margaret chen", "dob": "1985-03-15", "phone": "+16505212836"}, None, R
    )
    assert r.status is Status.MISMATCH and r.party_id is None


def test_representative_with_too_few_fields_needs_more():
    r = verify_representative("david chen", {"full_name": "margaret chen"}, None, R)
    assert r.status is Status.NEED_MORE
