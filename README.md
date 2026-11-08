# SOP-guided insurance claims agent

A conversational insurance support agent that follows a fixed business workflow
(`VERIFY_ID -> RESOLVE_INTENT -> PROCESS_CASE -> POST_PROCESS`) yet talks naturally. Includes a chat UI with a live
**SOP inspector** that shows, for every turn, what was extracted, what the code decided and why.

**Principle: code owns the workflow, the LLM owns language.** A deterministic Python state machine decides the phase,
the gates, the allowed actions and which data the LLM may see. Claude is used in two bounded roles: an *extractor*
(messy utterance -> typed signals) and a *phraser* (rewrites an engine-chosen template reply). There is no tool loop:
the LLM can never choose what data to read or relax a gate.

Design (source of truth): [`docs/sop-agent-design.md`](docs/sop-agent-design.md). Brief: [`docs/assignment.md`](docs/assignment.md).

## Architecture

```
 browser (sop_agent/web/index.html)          X-Anthropic-Key header (per request, never stored/logged)
   chat + SOP inspector  ───────────►  FastAPI  (sop_agent/api)  ── in-memory sessions (TTL, cap, per-session lock)
                                           │
                                           ▼  SOPEngine.handle_turn(state, text)
   1. EXTRACT   Haiku, structured output ─► TurnExtraction (bounded enums; cannot set "verified")
   2. REMEMBER  merge PII + hints into state, in ANY phase
   3. POLICY    wants human · off-topic strikes · refusal/emotion counters
   4. PHASE     deterministic handler -> Actions (+ fact bundle); the ONLY place phase changes
   5. RESPOND   template per action; in llm mode Sonnet rephrases it (no tools, sees only template + facts)
   6. GUARD     pre-verification leak check + grounding check; failure -> template reply
   7. RECORD    transcript, ledger, per-turn trace  ─►  {reply, state snapshot, trace}

 VERIFY_ID ─verified─► RESOLVE_INTENT ─1 case─► PROCESS_CASE ─done─► POST_PROCESS ─send|skip─► ENDED
   │  └─representative: consent (pending -> approved | timeout)        ▲ other claim ◄──────────┘
   └─ 3 failed attempts / refusals / asks for a human ──────────────────────────────────────► HANDOFF
```

Data: `apps/insurance_claims/fixtures/*.json` (read-only starter data).

## Phase freedom

| Phase | Freedom | Code-enforced rules |
|---|---|---|
| VERIFY_ID | Strict | Verified only when exactly one record has >= 3 of 5 PII matches and none contradict it; policy number only locates. Mismatch never says which field is wrong; 3 failures offer a human. No claim data in any LLM context or reply before verification (and consent, for representatives). |
| RESOLVE_INTENT | Flexible, bounded | LLM interprets language into hints; deterministic resolver filters the caller's own claims. Exactly one match selects; zero/many always asks, never "first match". |
| PROCESS_CASE | Freest | Fact bundle built by code from the selected claim + guidance; phraser may only use those facts (grounding guard). Disclosures go to a ledger. |
| POST_PROCESS | Strict choice | Email summary built deterministically from the ledger; caller chooses send or skip. Simulated outbox. |
| Every phase | - | Memory capture, off-topic handling, human escalation. These never change the phase by themselves. |

## Brief requirement -> mechanism -> test

| Requirement | Mechanism | Tests |
|---|---|---|
| 4-phase workflow, code-controlled order | `sop/engine.py` phase handlers are the only writers of `state.phase` | `tests/sop/test_engine_post.py::test_full_brief_workflow` |
| >= 3 PII of name/DOB/phone/email/SSN-4; alternates, partial answers | `sop/verification.py`, `data/normalize.py` | `tests/sop/test_verification.py`, `test_normalize.py`, `test_engine_verify.py` |
| No disclosure before verification | Structural: no claim data in LLM context; leak guard on replies | `test_engine_verify.py::test_partial_identity_stays_in_verify_and_no_claim_data_in_llm_context`, `test_leaky_reply_in_verify_is_replaced`, `tests/sop/test_guards.py` |
| Prompt injection ("I'm already verified") | Only verifier code sets `verified_party_id` | `test_engine_verify.py::test_prompt_injection_cannot_verify` |
| Refusals, mismatches, no field hints | `ASK_IDENTITY` / `IDENTITY_MISMATCH` carry no record data | `test_mismatch_does_not_reveal_field_and_counts_attempt`, `test_three_mismatches_offer_human` |
| Representative + consent (default / timeout) | Rep match + consent poll sequence from `consent_scenarios.json` | `test_representative_default_consent_flow`, `test_representative_timeout_consent`, `test_unknown_representative_is_rejected` |
| Remember hints from earlier phases | `merge_into_state` runs every turn, every phase | `test_engine_verify.py::test_brief_demo_turn_verifies_and_uses_remembered_hint`, `tests/sop/test_extraction.py` |
| Resolve case / ambiguity | `sop/case_resolver.py` | `tests/sop/test_case_resolver.py`, `test_engine_case.py::test_ambiguous_hints_clarify_without_claim_details_then_year_selects`, `test_other_partys_claim_is_never_selectable` |
| Grounded answers only | Fact bundle (`case_facts.py`) + grounding guard | `tests/sop/test_case_facts.py`, `test_engine_case.py::test_ungrounded_phrasing_falls_back_to_template` |
| Email summary, send or skip | `sop/summary.py`, outbox in state | `tests/sop/test_summary.py`, `test_engine_post.py::test_send_emails_summary_and_ends`, `test_skip_ends_without_email` |
| Out-of-scope rejected; human after repeated tries | Scope label + strike counter (3rd strike offers human) | `test_engine_post.py::test_off_topic_strikes_then_human_offer_then_handoff`, `tests/sop/test_policies.py` |
| Bonus: empathy, explain why, alternatives, escalate | Emotion/refusal in extraction; tone + explanation in templates; escalation policy | `test_engine_verify.py::test_frustrated_refusal_stays_in_verify_with_empathy_and_no_claim_data`, `test_second_refusal_adds_human_offer`, `test_engine_post.py::test_very_angry_caller_is_offered_a_human_alongside_the_answer` |
| LLM failure is safe | Template fallback; bad key -> 401 | `test_engine_verify.py::test_llm_unavailable_uses_template`, `tests/llm/test_client.py`, `tests/api/test_app.py` |
| Determinism / verifiability | `SOP_RESPONDER_MODE=template`; per-turn trace | `test_engine_verify.py::test_template_mode_is_deterministic`, `test_engine_case.py::test_four_turn_script_is_deterministic` |
| Accepts an API token; simple test UI | `X-Anthropic-Key` header, `web/index.html` | `tests/api/test_app.py`, `tests/api/test_ui.py` |

## Quick start

Docker (needs a key only when you chat):

```bash
cp .env.example .env            # optional: set ANTHROPIC_API_KEY for local use
docker compose up --build       # http://localhost:8000
# or: docker build -t goaly-sop . && docker run --rm -p 8000:8000 goaly-sop
```

Without Docker (Python 3.12+, [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run uvicorn sop_agent.api.app:app --port 8000      # http://localhost:8000
```

`PORT` is honored in the container. Config is by environment (see `.env.example`): `SOP_RESPONDER_MODE` (`llm` |
`template`), `SOP_EXTRACTOR_MODEL`, `SOP_RESPONDER_MODEL`, `SOP_TODAY`, `SOP_SESSION_TTL_SECONDS`, `SOP_MAX_SESSIONS`.

## API key handling

- Paste your Anthropic key into the UI header field; it is kept in browser `sessionStorage` (this tab only) and sent
  per request as `X-Anthropic-Key`. The server never stores, logs or echoes it.
- Fallback: server env `ANTHROPIC_API_KEY` (handy for local Docker). The hosted image ships **without** a key.
- A key is needed even in `template` mode: extraction still calls Claude. `GET /api/config` tells the UI whether the
  server has a key. A rejected key returns 401 "Anthropic rejected the API key".

## Demo script

Use the UI chips or type these (consent select: `default`):

1. Demo line: *"I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied healthcare
   claim from January. DOB is 1985-03-15, SSN last four is 4472."* -> verified, remembered hint selects CL-2048
   immediately, denial reason answered from claim data (phases VERIFY_ID -> RESOLVE_INTENT -> PROCESS_CASE in one turn).
2. Ask a follow-up ("what documents do I need?", "how long after I submit?") -> grounded answers; ledger grows.
3. "That's all" -> email offered to the masked address; "yes send it" -> outbox shows the rendered email, phase ENDED.
4. Bonus: new session, send the frustrated line ("I already told you who I am. This is ridiculous...") -> empathy,
   why verification matters, allowed alternatives, still VERIFY_ID, no claim details.
5. Off-topic: "what is RL?" three times -> polite decline each time, human offered on the third strike.
6. Representative: "Hi, I'm David Chen calling for my mother Margaret Chen." -> provide her details; `default`
   consent approves on a later turn, `timeout` never approves and offers a human.

## Tests and evals

```bash
uv run pytest -q                                      # offline, no network (FakeLLM)
uv run ruff check . && uv run ruff format --check .
uv run python -m evals.run [--only N]                 # live scenario evals, needs ANTHROPIC_API_KEY
```

Live evals assert on state (phase, verified party, selected case, no leak), not wording.

## Design trade-offs

- **State machine over agent loop / LangGraph:** the SOP is small and fixed; plain code is easier to audit and test.
- **Structured extraction + templates:** every reply has a deterministic template, so the system stays correct if the
  LLM is down, refuses or hallucinates. The phraser is optional polish behind two guards.
- **Security by construction:** claim data is never put in an LLM context before verification, so prompts cannot leak it.
- **Strict verification:** a contradicting field blocks a match; failures reset collected fields and never name the bad one.
- **In-memory sessions:** simplest thing that fits a demo; per-session locks serialise concurrent messages.

## Limitations

- Sessions are lost on restart; single process only. No auth or multi-tenancy.
- Email and human transfer are simulated (outbox / handoff note).
- Guards are deterministic pattern checks (IDs, amounts, dates), not a semantic fact-checker; wording of the phrased
  reply can vary between runs in `llm` mode (use `template` mode for byte-identical output).
- Extraction quality depends on the model; unparseable output degrades to an empty extraction (the agent just re-asks).
- Free hosting tiers sleep when idle; the first request can be slow.
