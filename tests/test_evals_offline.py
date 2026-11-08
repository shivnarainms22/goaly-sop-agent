from evals.run import check
from evals.scenarios import KNOWN_EXPECT_KEYS, SCENARIOS
from sop_agent.config import Settings
from sop_agent.data.repository import Repository
from sop_agent.sop.actions import Action, ActionKind
from sop_agent.sop.engine import Trace, TurnResult
from sop_agent.sop.state import SessionState


def _repo():
    return Repository.load(Settings().fixtures_dir)


def _result(reply, kinds):
    trace = Trace(
        extraction={},
        phase_before="VERIFY_ID",
        phase_after="VERIFY_ID",
        actions=[Action(kind=ActionKind(k)) for k in kinds],
        mode="template",
        guard={},
    )
    return TurnResult(reply=reply, trace=trace)


def test_scenarios_load_with_unique_names_and_known_expect_keys():
    names = [s.name for s in SCENARIOS]
    assert len(names) == 9 and len(set(names)) == 9
    for s in SCENARIOS:
        assert s.turns
        for t in s.turns:
            assert set(t.expect) <= KNOWN_EXPECT_KEYS


def test_check_passes_when_state_and_trace_match():
    ok = {
        "phase": "VERIFY_ID",
        "verified": False,
        "actions_include": ["ASK_IDENTITY"],
        "outbox": 0,
        "no_claim_leak": True,
    }
    assert check(ok, _result("Please verify first.", ["ASK_IDENTITY"]), SessionState.new(), _repo()) == []


def test_check_reports_each_unmet_expectation():
    bad = {
        "phase": "ENDED",
        "verified": True,
        "selected_case": "CL-2048",
        "actions_include": ["EMAIL_SENT"],
        "outbox": 1,
        "reply_contains_any": ["pathology"],
    }
    failures = check(bad, _result("Please verify first.", ["ASK_IDENTITY"]), SessionState.new(), _repo())
    assert len(failures) == 6


def test_check_flags_claim_leak_in_reply():
    leak = _result("Your claim CL-2048 was denied.", [])
    assert check({"no_claim_leak": True}, leak, SessionState.new(), _repo()) == ["reply leaks claim data"]
