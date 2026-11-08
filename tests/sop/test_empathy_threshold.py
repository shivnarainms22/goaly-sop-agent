from sop_agent.sop.actions import Action, ActionKind
from sop_agent.sop.extraction import PII, CaseHints, Emotion, TurnExtraction
from sop_agent.sop.templates import render

ASK = [Action(kind=ActionKind.ASK_INTENT)]


def test_mild_emotion_gets_no_empathy_opener():
    assert render(ASK, Emotion(label="confused", intensity=1)) == render(ASK, Emotion())


def test_clear_emotion_gets_empathy_opener():
    plain = render(ASK, Emotion())
    for label in ("frustrated", "anxious", "angry", "confused"):
        reply = render(ASK, Emotion(label=label, intensity=2))
        assert reply != plain and reply.endswith(plain)


def test_mild_emotion_does_not_ask_phraser_to_empathize(make_engine):
    ex = TurnExtraction(
        pii=PII(full_name="Margaret Chen"),
        emotion=Emotion(label="confused", intensity=1),
        case_hints=CaseHints(),
    )
    eng, llm, state = make_engine([ex])
    eng.handle_turn(state, "Margaret Chen, why was it denied?")
    assert "empathize" not in str(llm.calls[-1])
