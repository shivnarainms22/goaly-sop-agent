from sop_agent.sop.extraction import CaseHints, Emotion, TurnExtraction
from tests.sop.test_engine_verify import CLAIM_TOKENS, kinds

OFF_TOPIC = TurnExtraction(scope="off_topic")
DONE = TurnExtraction(done_with_case=True)


def at_post_process(make_engine, P9_DEMO_EXTRACTION, script=()):
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, DONE, *script], mode="template")
    eng.handle_turn(state, "demo")
    eng.handle_turn(state, "that's all")
    assert state.phase.name == "POST_PROCESS"
    return eng, llm, state


def test_send_emails_summary_and_ends(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = at_post_process(
        make_engine, P9_DEMO_EXTRACTION, [TurnExtraction(email_decision="send")]
    )
    res = eng.handle_turn(state, "yes please")
    assert kinds(res) == ["EMAIL_SENT"] and state.phase.name == "ENDED" and "m*******@email.com" in res.reply
    assert [m.to for m in state.email.outbox] == ["margaret@email.com"]
    assert state.email.decision == "send"
    assert kinds(eng.handle_turn(state, "hello?")) == ["CLOSED"] and state.phase.name == "ENDED"


def test_skip_ends_without_email(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = at_post_process(
        make_engine, P9_DEMO_EXTRACTION, [TurnExtraction(email_decision="skip")]
    )
    res = eng.handle_turn(state, "no thanks")
    assert kinds(res) == ["EMAIL_SKIPPED"] and state.phase.name == "ENDED" and state.email.outbox == []


def test_unclear_answer_reasks_yes_or_no(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = at_post_process(make_engine, P9_DEMO_EXTRACTION, [TurnExtraction()])
    res = eng.handle_turn(state, "hmm")
    assert kinds(res) == ["OFFER_EMAIL"] and "yes or no" in res.reply and state.phase.name == "POST_PROCESS"


def test_new_claim_question_after_offer_goes_back_to_resolve(make_engine, P9_DEMO_EXTRACTION):
    again = TurnExtraction(intent="status_inquiry", case_hints=CaseHints(case_type="auto"))
    eng, llm, state = at_post_process(make_engine, P9_DEMO_EXTRACTION, [again])
    res = eng.handle_turn(state, "actually what about my auto claim?")
    assert kinds(res) == ["CASE_SELECTED", "ANSWER_CASE"] and state.case.selected_case_id == "CL-2102"


def test_off_topic_strikes_then_human_offer_then_handoff(make_engine):
    eng, llm, state = make_engine([OFF_TOPIC] * 3 + [TurnExtraction(wants_human=True)], mode="template")
    results = [eng.handle_turn(state, "what's the weather?") for _ in range(3)]
    assert [kinds(r) for r in results] == [
        ["DECLINE_OFF_TOPIC", "ASK_IDENTITY"],
        ["DECLINE_OFF_TOPIC", "ASK_IDENTITY"],
        ["DECLINE_OFF_TOPIC", "ASK_IDENTITY", "OFFER_HUMAN"],
    ]
    assert state.counters.off_topic_strikes == 3 and state.phase.name == "VERIFY_ID"
    assert "verify your identity" in results[0].reply
    assert kinds(eng.handle_turn(state, "yes, a person")) == ["HANDOFF"] and state.phase.name == "HANDOFF"


def test_off_topic_during_verify_keeps_memory_and_phase(make_engine):
    hints = TurnExtraction(intent="denial_question", case_hints=CaseHints(status="denied"))
    eng, llm, state = make_engine([hints, OFF_TOPIC], mode="template")
    eng.handle_turn(state, "my claim was denied")
    before = state.memory.model_copy(deep=True)
    eng.handle_turn(state, "tell me a joke")
    assert state.memory == before and state.phase.name == "VERIFY_ID"


def test_smalltalk_is_answered_without_a_strike(make_engine):
    eng, llm, state = make_engine([TurnExtraction(scope="smalltalk")], mode="template")
    res = eng.handle_turn(state, "hi there!")
    assert kinds(res) == ["SMALLTALK", "ASK_IDENTITY"] and state.counters.off_topic_strikes == 0


def test_thanks_that_is_all_still_ends_the_case(make_engine, P9_DEMO_EXTRACTION):
    bye = TurnExtraction(scope="smalltalk", done_with_case=True)
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, bye], mode="template")
    eng.handle_turn(state, "demo")
    assert kinds(eng.handle_turn(state, "thanks, that's all")) == ["OFFER_EMAIL"]


def test_very_angry_caller_is_offered_a_human_alongside_the_answer(make_engine, P9_DEMO_EXTRACTION):
    angry = TurnExtraction(intent="denial_question", emotion=Emotion(label="angry", intensity=3))
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, angry], mode="template")
    eng.handle_turn(state, "demo")
    res = eng.handle_turn(state, "this is outrageous, why was it denied")
    assert kinds(res) == ["ANSWER_CASE", "OFFER_HUMAN"] and "sorry" in res.reply.lower()


def test_frustrated_phraser_call_gets_empathy_tone(make_engine):
    eng, llm, state = make_engine([TurnExtraction(emotion=Emotion(label="frustrated", intensity=2))])
    res = eng.handle_turn(state, "ugh")
    assert res.trace.actions[0].facts["tone"] == "empathize"
    assert "Caller is upset" in llm.calls[-1]["system"]


def test_full_brief_workflow(make_engine, P9_DEMO_EXTRACTION):
    script = [
        TurnExtraction(),
        P9_DEMO_EXTRACTION,
        TurnExtraction(intent="next_steps"),
        DONE,
        TurnExtraction(email_decision="send"),
    ]
    eng, llm, state = make_engine(script, mode="template")
    greeting = eng.handle_turn(state, "Hi, I need help with a claim")
    assert not any(t in greeting.reply for t in CLAIM_TOKENS)
    first = eng.handle_turn(state, "I'm Margaret Chen, POL-9921, my January healthcare claim was denied...")
    assert "2026-03-18" in first.reply and "has passed" in first.reply
    assert not any(
        t in str(llm.calls) for t in CLAIM_TOKENS
    )  # claim data never reached the LLM before this turn
    follow = eng.handle_turn(state, "how long does it take after I submit the documents?")
    assert "usually less than a week" in follow.reply
    eng.handle_turn(state, "that's all")
    eng.handle_turn(state, "yes send it")
    assert state.phase.name == "ENDED" and len(state.email.outbox) == 1
    email = state.email.outbox[0]
    assert email.to == "margaret@email.com" and "CL-2048" in email.body and "denied" in email.body
    assert "Next steps" in email.body and "usually less than a week" in email.body
