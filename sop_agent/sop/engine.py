import json

from pydantic import BaseModel

from sop_agent.config import Settings
from sop_agent.data.repository import Repository
from sop_agent.llm.client import LLMClient, LLMUnavailableError
from sop_agent.llm.prompts import extractor_system, phraser_system, phraser_user
from sop_agent.sop.actions import Action, ActionKind
from sop_agent.sop.case_resolver import Kind, resolve_case
from sop_agent.sop.extraction import TurnExtraction, merge_into_state
from sop_agent.sop.guards import check_grounding, check_pre_verification
from sop_agent.sop.policies import disclosure_allowed, should_escalate
from sop_agent.sop.state import Phase, SessionState
from sop_agent.sop.templates import render
from sop_agent.sop.verification import (
    PII_FIELDS,
    REQUIRED_MATCHES,
    Status,
    verify_identity,
    verify_representative,
)

CONTEXT_MESSAGES = 6
MISMATCHES_BEFORE_HUMAN = 3
_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]  # fmt: skip


class Trace(BaseModel):
    """Everything needed to explain a reply: what was extracted, decided, said and checked."""

    extraction: dict
    phase_before: str
    phase_after: str
    actions: list[Action]
    mode: str
    guard: dict[str, str]
    fallback_reasons: list[str] = []


class TurnResult(BaseModel):
    reply: str
    trace: Trace


def _action(kind: ActionKind, **facts) -> Action:
    return Action(kind=kind, facts=facts)


class SOPEngine:
    def __init__(self, repo: Repository, llm: LLMClient, settings: Settings):
        self.repo, self.llm, self.settings = repo, llm, settings

    # -- one turn: extract -> remember -> policy -> phase handler -> respond -> guard -> record -------------

    def handle_turn(self, state: SessionState, user_text: str) -> TurnResult:
        state.transcript.append({"role": "user", "text": user_text})
        phase_before = state.phase
        fallback: list[str] = []
        try:
            ex = self.llm.extract(
                system=self._extractor_prompt(state), messages=self._extractor_messages(state)
            )
        except LLMUnavailableError:  # LLMAuthError is deliberately not caught: the API layer reports it
            ex = TurnExtraction()
            fallback.append("extractor unavailable")
        merge_into_state(state, ex)
        if ex.refusal:
            refusals = state.counters.refusals
            refusals[state.phase.value] = refusals.get(state.phase.value, 0) + 1

        actions = self._decide(state, ex)
        offered = any(a.kind is ActionKind.OFFER_HUMAN for a in actions)
        if should_escalate(state, ex) and not offered and state.phase not in (Phase.HANDOFF, Phase.ENDED):
            actions.append(self._offer_human(state))

        template = render(actions, ex.emotion)
        reply, guard = template, {"pre_verification": "skipped", "grounding": "skipped"}
        if self.settings.responder_mode == "llm":
            reply, guard, reasons = self._phrase_and_guard(state, ex, actions, template)
            fallback += reasons

        state.transcript.append({"role": "assistant", "text": reply})
        trace = Trace(
            extraction=ex.model_dump(),
            phase_before=phase_before.value,
            phase_after=state.phase.value,
            actions=actions,
            mode=self.settings.responder_mode,
            guard=guard,
            fallback_reasons=fallback,
        )
        state.trace.append(trace.model_dump(mode="json"))
        return TurnResult(reply=reply, trace=trace)

    # -- extraction context ---------------------------------------------------------------------------------

    def _extractor_prompt(self, state: SessionState) -> str:
        last_agent = next((m["text"] for m in reversed(state.transcript) if m["role"] == "assistant"), "")
        return extractor_system(state.phase.value, last_agent)

    def _extractor_messages(self, state: SessionState) -> list[dict]:
        tail = state.transcript[-CONTEXT_MESSAGES:]
        while tail[0]["role"] != "user":  # the API wants a conversation that starts with the caller
            tail = tail[1:]
        return [{"role": m["role"], "content": m["text"]} for m in tail]

    # -- response + guards ----------------------------------------------------------------------------------

    def _phrase_and_guard(self, state, ex, actions, template):
        tone = "empathize" if ex.emotion.label != "neutral" else ""
        facts = {
            "actions": [{"action": a.kind.value, **a.facts} for a in actions],
            "caller_emotion": ex.emotion.label,
        }
        allowed = disclosure_allowed(state)
        # Until disclosure is allowed the phraser works under the VERIFY_ID rules whatever the phase.
        system = phraser_system(
            state.phase.value if allowed else Phase.VERIFY_ID.value,
            tone,
            escalate=any(a.kind is ActionKind.OFFER_HUMAN for a in actions),
        )
        content = phraser_user(template, facts, state.transcript[-CONTEXT_MESSAGES:])
        guard = {"pre_verification": "skipped", "grounding": "ok"}
        try:
            reply = self.llm.phrase(system=system, messages=[{"role": "user", "content": content}])
        except LLMUnavailableError:
            guard["grounding"] = "skipped"
            return template, guard, ["phraser unavailable"]

        reasons: list[str] = []
        if not allowed:
            pre = check_pre_verification(reply, self.repo)
            guard["pre_verification"] = "ok" if pre.ok else "fallback"
            reasons += pre.reasons
        user_texts = [m["text"] for m in state.transcript if m["role"] == "user"]
        grounded = check_grounding(reply, [json.dumps(facts, default=str), template, *user_texts])
        guard["grounding"] = "ok" if grounded.ok else "fallback"
        reasons += grounded.reasons
        return (reply if not reasons else template), guard, reasons

    # -- policy + phase handlers (the only place phase changes) ---------------------------------------------

    def _decide(self, state: SessionState, ex: TurnExtraction) -> list[Action]:
        if state.phase in (Phase.ENDED, Phase.HANDOFF):
            return [_action(ActionKind.CLOSED)]
        if ex.wants_human:
            return self._handoff(state)
        # Task 11: off-topic handling goes here, before the phase handler.
        if state.phase is Phase.VERIFY_ID:
            return self._verify(state, ex)
        if state.phase is Phase.RESOLVE_INTENT:
            return self._resolve(state)
        return [_action(ActionKind.ASK_INTENT)]  # PROCESS_CASE / POST_PROCESS handlers arrive in Tasks 10-11

    def _handoff(self, state: SessionState) -> list[Action]:
        note = (
            f"Caller asked for a human in {state.phase.value}. "
            f"Verified: {disclosure_allowed(state)}. Intent: {state.memory.intent or 'unknown'}."
        )
        state.phase = Phase.HANDOFF
        return [_action(ActionKind.HANDOFF, note=note)]

    def _offer_human(self, state: SessionState) -> Action:
        state.counters.human_offered = True
        return _action(ActionKind.OFFER_HUMAN)

    def _identity_facts(self, state: SessionState, ex: TurnExtraction, **extra) -> dict:
        """Verification metadata only: never records, never which field was wrong."""
        provided = state.identity.provided
        return {
            "fields_still_accepted": [f for f in PII_FIELDS if f not in provided],
            "matched_count_needed": REQUIRED_MATCHES,
            "details_still_needed": max(0, REQUIRED_MATCHES - len(provided)),
            "failed_attempts": state.identity.failed_attempts,
            "caller_emotion": ex.emotion.label,
            "tone": "empathize" if ex.emotion.label != "neutral" else "",
            **extra,
        }

    def _verify(self, state: SessionState, ex: TurnExtraction) -> list[Action]:
        ident, consent = state.identity, state.consent
        if consent.status == "pending":
            return self._poll_consent(state)
        if consent.status == "timed_out":
            return [_action(ActionKind.CONSENT_TIMEOUT), self._offer_human(state)]

        is_rep = ident.caller_role == "representative"
        if is_rep and not ident.rep_name:  # a representative must say who they are before anything is checked
            facts = self._identity_facts(state, ex, refusal=ex.refusal, ask_rep_name=True)
            return [_action(ActionKind.ASK_IDENTITY, **facts)]
        if is_rep:
            result = verify_representative(ident.rep_name, ident.provided, ident.policy_number, self.repo)
        else:
            result = verify_identity(ident.provided, ident.policy_number, self.repo)

        if result.status is Status.VERIFIED:
            ident.verified_party_id = result.party_id
            if is_rep:
                consent.status, consent.poll_index = "pending", 0
                return [_action(ActionKind.CONSENT_PENDING)]
            return [_action(ActionKind.VERIFIED), *self._resolve(state)]

        if result.status is Status.MISMATCH:
            ident.failed_attempts += 1
            # Re-collect from scratch and never hint at what was wrong.
            ident.provided, ident.policy_number = {}, None
            actions = [_action(ActionKind.IDENTITY_MISMATCH, **self._identity_facts(state, ex))]
            if ident.failed_attempts >= MISMATCHES_BEFORE_HUMAN:
                actions.append(self._offer_human(state))
            return actions

        facts = self._identity_facts(state, ex, refusal=ex.refusal)
        return [_action(ActionKind.ASK_IDENTITY, **facts)]

    def _poll_consent(self, state: SessionState) -> list[Action]:
        consent = state.consent
        consent.poll_index += 1
        sequence = self.repo.consent_scenarios[consent.scenario]
        if consent.poll_index >= len(sequence):
            consent.status = "timed_out"
            return [_action(ActionKind.CONSENT_TIMEOUT), self._offer_human(state)]
        if sequence[consent.poll_index] == "approved":
            consent.status = "approved"
            return [_action(ActionKind.VERIFIED), *self._resolve(state)]
        return [_action(ActionKind.CONSENT_PENDING)]

    def _resolve(self, state: SessionState) -> list[Action]:
        """RESOLVE_INTENT: pick the caller's claim from remembered hints; never guess among several."""
        state.phase = Phase.RESOLVE_INTENT
        party = state.identity.verified_party_id
        claims = self.repo.claims_for(party)
        resolution = resolve_case(state.memory, claims)
        state.case.candidate_case_ids = resolution.candidates
        if resolution.kind is Kind.RESOLVED:
            claim = self.repo.claim_for_party(party, resolution.case_id)
            state.case.selected_case_id = claim.case_id
            state.phase = Phase.PROCESS_CASE
            facts = {"case_id": claim.case_id, "case_type": claim.case_type, "status": claim.status}
            return [_action(ActionKind.CASE_SELECTED, **facts)]
        if resolution.kind is Kind.NO_HINTS:
            return [_action(ActionKind.ASK_INTENT)]
        shown = [c for c in claims if c.case_id in resolution.candidates] or claims
        candidates = [
            {
                "case_id": c.case_id,
                "case_type": c.case_type,
                "month_name": _MONTHS[c.created_at.month - 1],
                "year": c.created_at.year,
                "status": c.status,
            }
            for c in shown
        ]
        return [_action(ActionKind.CLARIFY_CASE, candidates=candidates)]
