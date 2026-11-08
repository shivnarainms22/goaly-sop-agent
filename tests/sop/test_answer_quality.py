from sop_agent.sop.extraction import PII, CaseHints, Emotion, TurnExtraction
from tests.sop.test_engine_case import verified_in_process_case
from tests.sop.test_engine_verify import CLAIM_TOKENS, kinds

AUTO = CaseHints(case_type="auto")
WHY = "keeps the policyholder safe"


def ask_about(make_engine, P9_DEMO_EXTRACTION, extraction, hints=None):
    eng, llm, state = verified_in_process_case(
        make_engine,
        P9_DEMO_EXTRACTION,
        [extraction.model_copy(update={"case_hints": hints or CaseHints()})],
        mode="template",
    )
    return eng, state, eng.handle_turn(state, "question")


def test_next_steps_on_claim_without_documents_has_no_missing_files_talk(make_engine, P9_DEMO_EXTRACTION):
    ask = TurnExtraction(intent="next_steps", wants_other_case=True)
    _, _, res = ask_about(make_engine, P9_DEMO_EXTRACTION, ask, AUTO)
    assert "CL-2102" in res.reply and "missing files" not in res.reply
    assert "still being processed" in res.reply


def test_payment_question_shows_amounts(make_engine, P9_DEMO_EXTRACTION):
    _, _, res = ask_about(make_engine, P9_DEMO_EXTRACTION, TurnExtraction(intent="payment_question"))
    assert "expected reimbursement" in res.reply.lower() and "net pay" in res.reply


def test_denial_question_on_closed_claim_says_not_denied(make_engine, P9_DEMO_EXTRACTION):
    ask = TurnExtraction(intent="denial_question", wants_other_case=True)
    _, _, res = ask_about(make_engine, P9_DEMO_EXTRACTION, ask, CaseHints(case_type="dental"))
    assert "CL-1899 is not denied; its status is closed" in res.reply and "Denial reason" not in res.reply


def test_new_topic_does_not_repeat_facts_already_said(make_engine, P9_DEMO_EXTRACTION):
    _, _, res = ask_about(make_engine, P9_DEMO_EXTRACTION, TurnExtraction(intent="document_submission"))
    assert "Denial reason" not in res.reply and "pathology report:" in res.reply


def test_repeated_question_with_nothing_new_restates(make_engine, P9_DEMO_EXTRACTION):
    _, _, res = ask_about(make_engine, P9_DEMO_EXTRACTION, TurnExtraction(intent="denial_question"))
    assert "Denial reason" in res.reply


def test_brief_bonus_turn_empathizes_explains_and_lists_fields(make_engine):
    ex = TurnExtraction(intent="denial_question", emotion=Emotion(label="frustrated", intensity=2))
    eng, _, state = make_engine([ex], mode="template")
    reply = eng.handle_turn(state, "Why was my claim denied?! I'm tired of this").reply
    assert "sorry for the frustration" in reply and WHY in reply and "full name" in reply
    assert not any(t in reply for t in CLAIM_TOKENS)


def test_asking_why_gets_the_explanation(make_engine):
    eng, _, state = make_engine([TurnExtraction(asks_why=True)], mode="template")
    assert WHY in eng.handle_turn(state, "why do you need that?").reply
    eng, _, state = make_engine([TurnExtraction()], mode="template")
    assert WHY not in eng.handle_turn(state, "hi").reply


def test_consent_pending_explains_why(make_engine):
    ex = TurnExtraction(
        pii=PII(full_name="Margaret Chen", dob="1985-03-15", phone="+16505212836"),
        caller_role="representative",
        rep_name="David Chen",
    )
    eng, _, state = make_engine([ex], mode="template")
    assert "privacy" in eng.handle_turn(state, "I'm David").reply


def test_email_request_mid_case_sends_and_ends(make_engine, P9_DEMO_EXTRACTION):
    send = TurnExtraction(email_decision="send")
    eng, _, state = verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, [send], mode="template")
    res = eng.handle_turn(state, "can you email me a summary?")
    assert kinds(res) == ["EMAIL_SENT"] and state.phase.name == "ENDED"
    assert [m.to for m in state.email.outbox] == ["margaret@email.com"]


def test_skip_mid_case_is_ignored(make_engine, P9_DEMO_EXTRACTION):
    skip = TurnExtraction(email_decision="skip", intent="status_inquiry")
    eng, _, state = verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, [skip], mode="template")
    res = eng.handle_turn(state, "no email")
    assert state.phase.name == "PROCESS_CASE" and state.email.outbox == [] and "ANSWER_CASE" in kinds(res)


def test_verified_party_without_claims_is_told_and_offered_a_human(make_engine):
    ex = TurnExtraction(
        pii=PII(full_name="Yaven Li", email="yawen.li@example.com", dob="1989-12-03"), caller_role="self"
    )
    eng, _, state = make_engine([ex], mode="template")
    res = eng.handle_turn(state, "Yaven Li, born Dec 3 1989, yawen.li@example.com")
    assert kinds(res) == ["VERIFIED", "NO_CLAIMS", "OFFER_HUMAN"]
    assert "I don't see any claims on file for you." in res.reply
    assert state.phase.name == "RESOLVE_INTENT" and state.case.selected_case_id is None


def test_markdown_from_the_phraser_is_stripped_to_plain_text(make_engine, P9_DEMO_EXTRACTION):
    phrased = "## Next steps\n**How to send:** use the __member portal__ for claim CL-2048."
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION], replies=[phrased])
    reply = eng.handle_turn(state, "demo").reply
    assert reply == "Next steps\nHow to send: use the member portal for claim CL-2048."
