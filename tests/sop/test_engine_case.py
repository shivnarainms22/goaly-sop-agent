import json

from sop_agent.sop.extraction import PII, CaseHints, TurnExtraction
from tests.sop.test_engine_verify import CLAIM_TOKENS, kinds

AMBIGUOUS = CaseHints(case_type="healthcare", month=1)
DEMO_TEXT = "I'm Margaret Chen, POL-9921, about my denied healthcare claim from January"


def verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, script=(), **kw):
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, *script], **kw)
    eng.handle_turn(state, DEMO_TEXT)
    return eng, llm, state


def test_demo_turn_selects_and_answers_the_remembered_intent(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION], mode="template")
    res = eng.handle_turn(state, DEMO_TEXT)
    assert kinds(res) == ["VERIFIED", "CASE_SELECTED", "ANSWER_CASE"]
    for expected in ("pathology report", "office note", "2026-03-18", "has passed", "human representative"):
        assert expected in res.reply
    assert res.reply.endswith("anything else I can help with?")
    texts = [e.text for e in state.ledger if e.kind == "fact"]
    assert any("Denial reason" in t for t in texts) and any("has passed" in t for t in texts)


def test_ambiguous_hints_clarify_without_claim_details_then_year_selects(make_engine, P9_DEMO_EXTRACTION):
    first = P9_DEMO_EXTRACTION.model_copy(update={"case_hints": AMBIGUOUS})
    eng, llm, state = make_engine([first, TurnExtraction(case_hints=CaseHints(year=2026))])
    res = eng.handle_turn(state, DEMO_TEXT)
    assert kinds(res) == ["VERIFIED", "CLARIFY_CASE"] and state.phase.name == "RESOLVE_INTENT"
    assert "CL-2048" in res.reply and "CL-2011" in res.reply
    assert not any(t in json.dumps(llm.calls) for t in ("pathology", "1450", "missing"))
    res = eng.handle_turn(state, "the 2026 one")
    assert kinds(res) == ["CASE_SELECTED", "ANSWER_CASE"] and state.case.selected_case_id == "CL-2048"


def test_ungrounded_phrasing_falls_back_to_template(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION], replies=["The appeal deadline is 2026-05-01."])
    res = eng.handle_turn(state, DEMO_TEXT)
    assert res.trace.guard["grounding"] == "fallback" and "2026-05-01" not in res.reply
    assert "pathology report" in res.reply


def test_other_partys_claim_is_never_selectable(make_engine, P9_DEMO_EXTRACTION):
    ex = P9_DEMO_EXTRACTION.model_copy(update={"case_hints": CaseHints(case_id="CL-3001")})
    eng, llm, state = make_engine([ex], mode="template")
    res = eng.handle_turn(state, DEMO_TEXT)
    assert kinds(res) == ["VERIFIED", "CLARIFY_CASE"] and state.case.selected_case_id is None
    assert "CL-3001" not in res.reply and state.phase.name == "RESOLVE_INTENT"


def test_status_inquiry_shows_status_and_amounts(make_engine, P9_DEMO_EXTRACTION):
    ask = TurnExtraction(intent="status_inquiry")
    eng, llm, state = verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, [ask], mode="template")
    reply = eng.handle_turn(state, "what's the status?").reply
    assert "status: denied" in reply and "net pay: $0.00" in reply


def test_followup_question_adds_next_step_once(make_engine, P9_DEMO_EXTRACTION):
    ask = TurnExtraction(intent="next_steps")
    eng, llm, state = verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, [ask, ask], mode="template")
    reply = eng.handle_turn(state, "how long after I submit the documents?").reply
    assert "usually less than a week" in reply
    before = list(state.ledger)
    eng.handle_turn(state, "how long after I submit the documents?")
    assert before and state.ledger == before and any(e.kind == "next_step" for e in before)


def test_document_submission_gives_guidance_and_alternative(make_engine, P9_DEMO_EXTRACTION):
    ask = TurnExtraction(intent="document_submission")
    eng, llm, state = verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, [ask], mode="template")
    reply = eng.handle_turn(state, "how do I send the documents?").reply
    assert "pathology report:" in reply and "office note:" in reply and "If you can't get it:" in reply


def test_unmatched_followup_uses_fallback(make_engine, P9_DEMO_EXTRACTION):
    ask = TurnExtraction(intent="payment_question")
    eng, llm, state = verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, [ask], mode="template")
    assert "separate claim-specific rule" in eng.handle_turn(state, "what is a deductible?").reply


def test_switching_to_another_claim_reanswers(make_engine, P9_DEMO_EXTRACTION):
    switch = TurnExtraction(
        intent="status_inquiry", wants_other_case=True, case_hints=CaseHints(case_type="auto")
    )
    eng, llm, state = verified_in_process_case(make_engine, P9_DEMO_EXTRACTION, [switch], mode="template")
    res = eng.handle_turn(state, "what about my auto claim?")
    assert kinds(res) == ["CASE_SELECTED", "ANSWER_CASE"] and state.case.selected_case_id == "CL-2102"


def test_wants_other_case_without_hints_asks_which(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = verified_in_process_case(
        make_engine, P9_DEMO_EXTRACTION, [TurnExtraction(wants_other_case=True)], mode="template"
    )
    res = eng.handle_turn(state, "I have another claim")
    assert kinds(res) == ["ASK_INTENT"] and state.phase.name == "RESOLVE_INTENT"


def test_done_with_case_offers_masked_email(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = verified_in_process_case(
        make_engine, P9_DEMO_EXTRACTION, [TurnExtraction(done_with_case=True)], mode="template"
    )
    res = eng.handle_turn(state, "that's all")
    assert kinds(res) == ["OFFER_EMAIL"] and state.phase.name == "POST_PROCESS"
    assert "m*******@email.com" in res.reply and "margaret@" not in res.reply


def test_four_turn_script_is_deterministic(make_engine, P9_DEMO_EXTRACTION):
    script = [
        P9_DEMO_EXTRACTION,
        TurnExtraction(intent="denial_question"),
        TurnExtraction(intent="next_steps"),
        TurnExtraction(done_with_case=True),
    ]
    texts = [DEMO_TEXT, "why was it denied?", "how long after I submit?", "that's all"]
    runs = []
    for _ in range(2):
        eng, llm, state = make_engine(script, mode="template")
        runs.append(([eng.handle_turn(state, t).reply for t in texts], state.trace))
        assert all(c["role"] == "extract" for c in llm.calls)
    assert runs[0] == runs[1] and runs[0][1][-1]["phase_after"] == "POST_PROCESS"


def test_no_claim_data_before_verification(make_engine):
    eng, llm, state = make_engine([TurnExtraction(pii=PII(full_name="Margaret Chen"))], mode="template")
    res = eng.handle_turn(state, "Margaret Chen")
    assert not any(t in res.reply for t in CLAIM_TOKENS)
