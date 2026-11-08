"""Live scenario evals (needs API key): `python -m evals.run [--only NAME] [--mode llm|template]`."""

import argparse
import sys

from evals.scenarios import SCENARIOS
from sop_agent.config import Settings
from sop_agent.data.repository import Repository
from sop_agent.llm.client import AnthropicLLM
from sop_agent.sop.engine import SOPEngine, TurnResult
from sop_agent.sop.guards import check_pre_verification
from sop_agent.sop.state import SessionState


def check(expect: dict, result: TurnResult, state: SessionState, repo: Repository) -> list[str]:
    """Return one failure message per unmet expectation (empty list = pass)."""
    kinds = [a.kind.value for a in result.trace.actions]
    failures = []
    if "phase" in expect and state.phase.value != expect["phase"]:
        failures.append(f"phase {state.phase.value} != {expect['phase']}")
    if "verified" in expect and (state.identity.verified_party_id is not None) != expect["verified"]:
        failures.append(f"verified != {expect['verified']}")
    if "selected_case" in expect and state.case.selected_case_id != expect["selected_case"]:
        failures.append(f"selected_case {state.case.selected_case_id} != {expect['selected_case']}")
    missing = [k for k in expect.get("actions_include", []) if k not in kinds]
    if missing:
        failures.append(f"missing actions {missing} (got {kinds})")
    if "outbox" in expect and len(state.email.outbox) != expect["outbox"]:
        failures.append(f"outbox {len(state.email.outbox)} != {expect['outbox']}")
    if expect.get("no_claim_leak") and not check_pre_verification(result.reply, repo).ok:
        failures.append("reply leaks claim data")
    needles = expect.get("reply_contains_any")
    if needles and not any(n in result.reply.lower() for n in needles):
        failures.append(f"reply lacks any of {needles}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="run a single scenario by name")
    parser.add_argument("--mode", choices=["llm", "template"], default="llm")
    args = parser.parse_args()
    scenarios = [s for s in SCENARIOS if args.only in (None, s.name)]
    if not scenarios:
        print(f"no scenario named {args.only!r}; known: {[s.name for s in SCENARIOS]}", file=sys.stderr)
        return 2
    settings = Settings(responder_mode=args.mode)
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set; live evals need it.", file=sys.stderr)
        return 2
    repo = Repository.load(settings.fixtures_dir)
    engine = SOPEngine(repo, AnthropicLLM(settings.anthropic_api_key, settings), settings)
    table = []
    for sc in scenarios:
        print(f"\n== {sc.name}")
        state = SessionState.new(consent_scenario=sc.consent_scenario)
        failed = []
        for i, turn in enumerate(sc.turns, 1):
            result = engine.handle_turn(state, turn.text)
            problems = check(turn.expect, result, state, repo)
            failed += [f"turn {i}: {p}" for p in problems]
            actions = ",".join(a.kind.value for a in result.trace.actions)
            verdict = "ok" if not problems else "FAIL " + "; ".join(problems)
            print(f"{i}. {state.phase.value} | {actions} | {verdict}")
            print(f"   > {result.reply[:160]!r}")
        table.append((sc.name, failed))
    print("\n" + "\n".join(f"{'PASS' if not f else 'FAIL'}  {n}" for n, f in table))
    return 1 if any(f for _, f in table) else 0


if __name__ == "__main__":
    sys.exit(main())
