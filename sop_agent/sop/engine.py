import json
import re

from pydantic import BaseModel

from sop_agent.config import Settings
from sop_agent.data.normalize import mask_email
from sop_agent.data.repository import Repository
from sop_agent.llm.client import LLMClient, LLMError, LLMUnavailableError
from sop_agent.llm.prompts import extractor_system, phraser_system, phraser_user
from sop_agent.sop.actions import Action, ActionKind
from sop_agent.sop.case_facts import build_case_bundle
from sop_agent.sop.case_resolver import Kind, resolve_case
from sop_agent.sop.extraction import Emotion, TurnExtraction, merge_into_state
from sop_agent.sop.guards import MONTHS, check_grounding, check_pre_verification
from sop_agent.sop.policies import disclosure_allowed, should_escalate
from sop_agent.sop.state import LedgerEntry, Memory, Phase, SessionState
from sop_agent.sop.summary import build_email_summary
from sop_agent.sop.templates import answer_parts, render
from sop_agent.sop.verification import (
    PII_FIELDS,
    REQUIRED_MATCHES,
    Status,
    verify_identity,
    verify_representative,
)

CONTEXT_MESSAGES = 6
MISMATCHES_BEFORE_HUMAN = 3
OFF_TOPIC_STRIKES_BEFORE_HUMAN = 3
TERMINAL_PHASES = (Phase.ENDED, Phase.HANDOFF)
MASKED = "***"
SKIPPED_GUARDS = {"pre_verification": "skipped", "grounding": "skipped"}


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


def _masked_extraction(ex: TurnExtraction) -> dict:
    """The extraction for the trace, identity values hidden (which fields were given stays visible)."""
    dumped = ex.model_dump()
    dumped["pii"] = {k: MASKED if v else None for k, v in dumped["pii"].items()}
    for key in ("policy_number", "rep_name"):
        dumped[key] = MASKED if dumped[key] else None
    return dumped


def _plain_text(text: str) -> str:
    """The chat UI shows plain text: drop Markdown emphasis and heading markers the phraser may add."""
    return re.sub(r"^#+\s*", "", re.sub(r"\*\*|__", "", text), flags=re.MULTILINE)


def _tone(ex: TurnExtraction) -> str:
    return "empathize" if ex.emotion.strong else ""


class SOPEngine:
    def __init__(self, repo: Repository, llm: LLMClient, settings: Settings):
        self.repo, self.llm, self.settings = repo, llm, settings

    # -- one turn: extract -> remember -> policy -> phase handler -> respond -> guard -> record -------------

    def handle_turn(self, state: SessionState, user_text: str) -> TurnResult:
        phase_before = state.phase
        fallback: list[str] = []
        if phase_before in TERMINAL_PHASES:  # nothing to extract or remember: just say the session is over
            state.transcript.append({"role": "user", "text": user_text})
            actions = [_action(ActionKind.CLOSED)]
            reply = render(actions, Emotion())
            return self._record(
                state, TurnExtraction(), phase_before, actions, reply, dict(SKIPPED_GUARDS), []
            )
        try:
            ex = self.llm.extract(
                system=self._extractor_prompt(state), messages=self._extractor_messages(state, user_text)
            )
        except LLMUnavailableError:  # LLMAuthError is deliberately not caught: the API layer reports it
            ex = TurnExtraction()
            fallback.append("extractor unavailable")
        state.transcript.append({"role": "user", "text": user_text})  # only once the turn can proceed
        merge_into_state(state, ex)
        if ex.refusal:
            refusals = state.counters.refusals
            refusals[state.phase.value] = refusals.get(state.phase.value, 0) + 1

        actions = self._decide(state, ex, user_text)
        offered = any(a.kind is ActionKind.OFFER_HUMAN for a in actions)
        if should_escalate(state, ex) and not offered and state.phase not in TERMINAL_PHASES:
            actions.append(_action(ActionKind.OFFER_HUMAN))

        template = render(actions, ex.emotion)
        reply, guard = template, dict(SKIPPED_GUARDS)
        if self.settings.responder_mode == "llm":
            reply, guard, reasons = self._phrase_and_guard(state, ex, actions, template)
            fallback += reasons

        return self._record(state, ex, phase_before, actions, reply, guard, fallback)

    def _record(self, state, ex, phase_before, actions, reply, guard, fallback) -> TurnResult:
        state.transcript.append({"role": "assistant", "text": reply})
        trace = Trace(
            extraction=_masked_extraction(ex),
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

    def _extractor_messages(self, state: SessionState, user_text: str) -> list[dict]:
        tail = [*state.transcript, {"role": "user", "text": user_text}][-CONTEXT_MESSAGES:]
        while tail[0]["role"] != "user":  # the API wants a conversation that starts with the caller
            tail = tail[1:]
        return [{"role": m["role"], "content": m["text"]} for m in tail]

    # -- response + guards ----------------------------------------------------------------------------------

    def _phrase_and_guard(self, state, ex, actions, template):
        tone = _tone(ex)
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
            reply = _plain_text(
                self.llm.phrase(system=system, messages=[{"role": "user", "content": content}])
            )
        except LLMError:  # unavailable or key rejected: state already changed, so answer from the template
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

    def _decide(self, state: SessionState, ex: TurnExtraction, user_text: str) -> list[Action]:
        if ex.wants_human:
            return self._handoff(state)
        closing = ex.done_with_case or ex.email_decision != "none"
        off_topic = ex.scope == "off_topic"
        lead: list[Action] = []  # decline or chat first, then carry on with whatever the caller also gave us
        if off_topic or (ex.scope == "smalltalk" and not closing):
            state.counters.off_topic_strikes += off_topic
            lead = [_action(ActionKind.DECLINE_OFF_TOPIC if off_topic else ActionKind.SMALLTALK)]

        if state.phase is Phase.VERIFY_ID:
            actions = self._verify(state, ex)
        elif state.phase is Phase.RESOLVE_INTENT:
            actions = self._send_email(state) if ex.email_decision == "send" else self._resolve(state)
        elif state.phase is Phase.PROCESS_CASE:
            actions = self._process(state, ex)
        else:
            actions = self._post_process(state, ex)
        if state.phase is Phase.PROCESS_CASE:  # however we got here, the selected case is answered now
            if lead and not actions and ex.intent in ("none", "other"):  # chat only: don't repeat the answer
                actions.append(_action(ActionKind.ASK_INTENT))
            else:
                actions.append(self._answer(state, user_text))
        offered = any(a.kind is ActionKind.OFFER_HUMAN for a in actions)
        if off_topic and state.counters.off_topic_strikes >= OFF_TOPIC_STRIKES_BEFORE_HUMAN and not offered:
            actions.append(_action(ActionKind.OFFER_HUMAN))
        return lead + actions

    def _handoff(self, state: SessionState) -> list[Action]:
        note = (
            f"Caller asked for a human in {state.phase.value}. "
            f"Verified: {disclosure_allowed(state)}. Intent: {state.memory.intent or 'unknown'}."
        )
        state.phase = Phase.HANDOFF
        return [_action(ActionKind.HANDOFF, note=note)]

    def _identity_facts(self, state: SessionState, ex: TurnExtraction, **extra) -> dict:
        """Verification metadata only: never records, never which field was wrong."""
        provided = state.identity.provided
        return {
            "fields_still_accepted": [f for f in PII_FIELDS if f not in provided],
            "matched_count_needed": REQUIRED_MATCHES,
            "details_still_needed": max(0, REQUIRED_MATCHES - len(provided)),
            "failed_attempts": state.identity.failed_attempts,
            "caller_emotion": ex.emotion.label,
            "tone": _tone(ex),
            "explain": ex.refusal or ex.emotion.strong or ex.asks_why,
            **extra,
        }

    def _verify(self, state: SessionState, ex: TurnExtraction) -> list[Action]:
        ident, consent = state.identity, state.consent
        if consent.status == "pending":
            return self._poll_consent(state)
        if consent.status == "timed_out":
            return [_action(ActionKind.CONSENT_TIMEOUT), _action(ActionKind.OFFER_HUMAN)]

        is_rep = ident.caller_role == "representative"
        if is_rep and not ident.rep_name:  # a representative must say who they are before anything is checked
            facts = self._identity_facts(state, ex, ask_rep_name=True)
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
            unknown_rep = "rep_name" in result.conflicting_fields
            if unknown_rep:  # right policyholder details, but not a registered representative
                ident.rep_name = None
            # Re-collect from scratch and never hint at what was wrong.
            ident.provided, ident.policy_number = {}, None
            actions = [_action(ActionKind.IDENTITY_MISMATCH, **self._identity_facts(state, ex))]
            if unknown_rep or ident.failed_attempts >= MISMATCHES_BEFORE_HUMAN:
                actions.append(_action(ActionKind.OFFER_HUMAN))
            return actions

        facts = self._identity_facts(state, ex)
        return [_action(ActionKind.ASK_IDENTITY, **facts)]

    def _poll_consent(self, state: SessionState) -> list[Action]:
        consent = state.consent
        consent.poll_index += 1
        sequence = self.repo.consent_scenarios[consent.scenario]
        if consent.poll_index >= len(sequence):
            consent.status = "timed_out"
            return [_action(ActionKind.CONSENT_TIMEOUT), _action(ActionKind.OFFER_HUMAN)]
        if sequence[consent.poll_index] == "approved":
            consent.status = "approved"
            return [_action(ActionKind.VERIFIED), *self._resolve(state)]
        return [_action(ActionKind.CONSENT_PENDING)]

    def _process(self, state: SessionState, ex: TurnExtraction) -> list[Action]:
        """PROCESS_CASE: finish, or switch case. No actions means the selected case is simply answered."""
        if ex.email_decision == "send":  # asked for the summary mid-case: no need to offer it first
            return self._send_email(state)
        if ex.done_with_case:
            state.phase = Phase.POST_PROCESS
            return [self._offer_email(state)]
        if self._points_elsewhere(state, ex):
            return self._switch_case(state, ex)
        return []

    def _points_elsewhere(self, state: SessionState, ex: TurnExtraction) -> bool:
        """The caller is asking about a different claim than the selected one."""
        claims = self.repo.claims_for(state.identity.verified_party_id)
        other = resolve_case(Memory(**ex.case_hints.model_dump()), claims)
        return ex.wants_other_case or (
            other.kind is Kind.RESOLVED and other.case_id != state.case.selected_case_id
        )

    def _post_process(self, state: SessionState, ex: TurnExtraction) -> list[Action]:
        if self._points_elsewhere(state, ex):  # a new question never ends the call
            return self._switch_case(state, ex)
        if ex.email_decision == "send":
            return self._send_email(state)
        if ex.email_decision == "skip":
            state.email.decision, state.phase = "skip", Phase.ENDED
            return [_action(ActionKind.EMAIL_SKIPPED)]
        if ex.intent not in ("none", "other"):  # one more question about this claim: answer it
            state.phase = Phase.PROCESS_CASE
            return []
        return [self._offer_email(state, reprompt=True)]

    def _send_email(self, state: SessionState) -> list[Action]:
        message = build_email_summary(state, self.repo)
        state.email.outbox.append(message)
        state.email.decision, state.phase = "send", Phase.ENDED
        return [_action(ActionKind.EMAIL_SENT, masked_email=mask_email(message.to))]

    def _offer_email(self, state: SessionState, reprompt: bool = False) -> Action:
        state.email.offered = True
        email = self.repo.policyholder(state.identity.verified_party_id).email
        return _action(ActionKind.OFFER_EMAIL, masked_email=mask_email(email), reprompt=reprompt)

    def _switch_case(self, state: SessionState, ex: TurnExtraction) -> list[Action]:
        """The caller moved on to another claim: resolve afresh from the new hints.

        Hints the caller did not repeat are cleared (set to None), not kept from the old case.
        """
        for field, value in ex.case_hints:
            setattr(state.memory, field, value)
        return self._resolve(state)

    def _answer(self, state: SessionState, user_text: str) -> Action:
        claim = self.repo.claim_for_party(state.identity.verified_party_id, state.case.selected_case_id)
        intent = state.memory.intent or "other"
        bundle = build_case_bundle(self.repo, claim, intent, user_text, self.settings.today())
        said = [e.text for e in state.ledger if e.kind == "fact"]
        facts = {**bundle, "intent": intent, "already_said": said}
        shown_facts, next_steps = answer_parts(facts)
        for kind, texts in (("fact", shown_facts), ("next_step", next_steps)):
            for text in texts:
                entry = LedgerEntry(kind=kind, text=text, source=claim.case_id)
                if entry not in state.ledger:
                    state.ledger.append(entry)
        return _action(ActionKind.ANSWER_CASE, **facts)

    def _resolve(self, state: SessionState) -> list[Action]:
        """RESOLVE_INTENT: pick the caller's claim from remembered hints; never guess among several."""
        state.phase = Phase.RESOLVE_INTENT
        state.case.selected_case_id = None
        party = state.identity.verified_party_id
        claims = self.repo.claims_for(party)
        resolution = resolve_case(state.memory, claims)
        state.case.candidate_case_ids = resolution.candidates
        if not claims:
            return [_action(ActionKind.NO_CLAIMS), _action(ActionKind.OFFER_HUMAN)]
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
                "month_name": MONTHS[c.created_at.month - 1].title(),
                "year": c.created_at.year,
                "status": c.status,
            }
            for c in shown
        ]
        return [_action(ActionKind.CLARIFY_CASE, candidates=candidates)]
