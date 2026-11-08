from sop_agent.data.repository import Repository
from sop_agent.sop.guards import check_grounding, check_pre_verification

R = Repository.load()


def test_pre_verification_blocks_claim_details():
    assert not check_pre_verification("Your claim CL-2048 was denied.", R).ok
    assert not check_pre_verification(
        "It was missing the pathology report and the treating provider office note.", R
    ).ok
    assert not check_pre_verification("The allowed amount was $1,450.00", R).ok
    assert check_pre_verification(
        "I can help with that once I verify your identity. Could you share your phone number?", R
    ).ok


def test_pre_verification_blocks_claim_dates_in_any_format():
    assert not check_pre_verification("The deadline was 2026-03-18.", R).ok
    assert not check_pre_verification("The deadline was March 18, 2026.", R).ok
    assert not check_pre_verification("It was filed on January 12, 2026.", R).ok


def test_pre_verification_does_not_flag_ordinary_sentences():
    for text in [
        "May I have your date of birth, for example 1985-03-15?",
        "Please confirm the phone number ending in 2836, like 650.521.2836.",
        "I need three of these: name, date of birth, phone, email or last four digits of your ID.",
        "I'm sorry you're frustrated. I can transfer you to a human representative.",
    ]:
        assert check_pre_verification(text, R).ok, text


def test_grounding_accepts_supported_facts():
    ev = ['{"case_id":"CL-2048","appeal_deadline":"2026-03-18","allowed_max_amount":"1450.00"}']
    assert check_grounding(
        "Claim CL-2048 had an appeal deadline of March 18, 2026 and allowed $1,450.00.", ev
    ).ok


def test_grounding_rejects_invented_facts():
    ev = ['{"case_id":"CL-2048","appeal_deadline":"2026-03-18"}']
    r = check_grounding("You have until 2026-04-30 to appeal and will receive $900.00.", ev)
    assert not r.ok and r.reasons == ["ungrounded numbers: 0, 4, 30, 900"]


def test_grounding_rejects_invented_case_id_and_is_case_insensitive_otherwise():
    ev = ['{"case_id":"CL-2048"}', "my claim is cl-2048"]
    assert check_grounding("Claim cl-2048 is open.", ev).ok
    assert not check_grounding("Claim CL-2102 is open.", ev).ok


def test_grounding_amount_formats_are_equivalent():
    assert check_grounding("It is $900.", ['{"net_fee":"900.00"}']).ok
    assert not check_grounding("It is $900.", ['{"net_fee":"90.00"}']).ok


def test_grounding_no_facts_ok():
    assert check_grounding("I'm sorry to hear that. Let me check.", []).ok


def test_pre_verification_blocks_case_numbers_and_amounts_in_any_format():
    for text in ["About CL 2048.", "Re: claim 2048", "That is 1450 dollars.", "It was $1,450.00 in total."]:
        assert not check_pre_verification(text, R).ok, text


def test_pre_verification_blocks_claim_dates_in_short_formats():
    for text in [
        "Due 3/18/2026",
        "Due 03/18/2026",
        "Due 3/18",
        "Due march 18",
        "Due 18 March",
        "Due Mar 18th",
    ]:
        assert not check_pre_verification(text, R).ok, text


def test_pre_verification_ignores_small_numbers_and_ordinary_replies():
    for text in [
        "That is version 3.14, wait 10.00 min.",
        "Could you share your phone number or date of birth?",
        "I can help once you're verified.",
    ]:
        assert check_pre_verification(text, R).ok, text


def test_pre_verification_one_reason_per_kind():
    r = check_pre_verification("CL-2048 and CL-2102, $1,450.00", R)
    assert r.reasons == sorted(set(r.reasons), key=r.reasons.index)


def test_grounding_dates_need_evidence():
    assert not check_grounding("deadline 3/18/2026", []).ok
    assert check_grounding("deadline 3/18/2026", ["2026-03-18"]).ok
    assert not check_grounding("2026-05-01", ["2026-03-18"]).ok
    assert not check_grounding("May 1", ["2026-03-18"]).ok
    assert check_grounding("March 18", ["2026-03-18"]).ok


def test_grounding_amounts_need_evidence():
    assert check_grounding("1450 dollars", ["1450.00"]).ok
    assert not check_grounding("1450 dollars", []).ok
