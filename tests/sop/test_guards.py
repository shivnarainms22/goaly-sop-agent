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
    assert not r.ok and len(r.reasons) == 2


def test_grounding_rejects_invented_case_id_and_is_case_insensitive_otherwise():
    ev = ['{"case_id":"CL-2048"}', "my claim is cl-2048"]
    assert check_grounding("Claim cl-2048 is open.", ev).ok
    assert not check_grounding("Claim CL-2102 is open.", ev).ok


def test_grounding_amount_formats_are_equivalent():
    assert check_grounding("It is $900.", ['{"net_fee":"900.00"}']).ok
    assert not check_grounding("It is $900.", ['{"net_fee":"90.00"}']).ok


def test_grounding_no_facts_ok():
    assert check_grounding("I'm sorry to hear that. Let me check.", []).ok
