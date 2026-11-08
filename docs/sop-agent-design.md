# SOP-Guided Insurance Claims Agent — Design

Status: approved 2026-11-07. Brief: [assignment.md](assignment.md).

## 1. Principle

**Code owns the workflow; the LLM owns language.** A deterministic Python state machine decides phase, gates,
allowed actions and what data the LLM may see. The LLM is used in two bounded roles per turn:

1. **Extractor** (Claude Haiku 5.5, structured output) — turns a messy utterance into typed signals (bounded enums).
2. **Phraser** (Claude Sonnet 5.5) — rewrites the engine's reply for an engine-chosen *action* naturally (empathy,
   clarification), using only the **fact bundle** that action carries. It has no tools and cannot fetch anything.

Safety properties are structural, not prompt-based: claim data is never placed in the LLM context before
verification, so it cannot leak; the extractor cannot "set verified" — only the verifier code can.

**Simplicity & determinism rules (user requirement, 2026-11-07):**
- No agentic tool loop. All data access is deterministic code: given (phase, extracted intent, selected case, question)
  the engine assembles the exact fact bundle. The LLM's "freedom" in RESOLVE_INTENT/PROCESS_CASE is interpreting messy
  language into bounded enums/hints and phrasing — never choosing what data to read.
- Every action has a deterministic **template reply** built from its fact bundle. `SOP_RESPONDER_MODE=template` skips the
  phraser entirely, so given the same extractions the agent's outputs are byte-identical (used by tests and evals).
  Default `llm` mode phrases naturally; any phrased reply that fails a guard falls back to the template.
- Every turn emits a **trace** (extraction JSON, decisions, action, facts given, guard results) — every reply is
  verifiable against it. Minimal code: no abstraction a current requirement doesn't need.

## 2. Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Time budget | ~45 h → full pipeline + bonus + evals + hosted demo |
| LLM | Anthropic Claude via official `anthropic` SDK. Models configurable: `SOP_EXTRACTOR_MODEL` (default `claude-haiku-5-5`), `SOP_RESPONDER_MODEL` (default `claude-sonnet-5-5`) |
| Delivery | GitHub repo + Dockerfile/compose; hosted instance (Render or HF Spaces Docker) |
| Token | Per-request header `X-Anthropic-Key` from a UI field (kept in browser `sessionStorage`, never logged/persisted server-side). Fallback to server env `ANTHROPIC_API_KEY` only if set (local Docker). Hosted instance runs **without** a server key |
| UI | FastAPI serving one static HTML page (vanilla JS): chat pane + live **SOP inspector** |
| Email | Simulated outbox, rendered email shown in UI; nothing is actually sent |
| Architecture | A — code-owned state machine with phase-scoped LLM freedom (no LangGraph) |

## 3. Phases & state machine

```
VERIFY_ID ──verified (self)──────────────────────────► RESOLVE_INTENT ──1 case resolved──► PROCESS_CASE
    │      └─verified (representative)─► consent pending ─approved─┘  ▲  └─0/>1 match: clarify   │  │
    │                                         └─timeout─► HANDOFF      └──────── switch case ─────┘  │
    │                                                                                               done
    └─3 failed attempts / refusals / wants human ─► HANDOFF                                          ▼
                                                                   ENDED ◄─ send|skip ─ POST_PROCESS
                                                                              └─ "something else" ─► RESOLVE_INTENT
```

Terminal phases: `ENDED`, `HANDOFF` (simulated transfer to a human with a handoff note). Off-topic handling
and memory capture run in **every** phase and never change phase by themselves.

## 4. Session state (single source of truth, shown in the inspector)

- `phase`, `today` (config `SOP_TODAY`, default real date)
- `identity`: provided fields `{full_name, dob, phone, email, id_last4, policy_number}` (latest value wins
  per field — corrections allowed), `caller_role` (self|representative|unknown), `rep_name`, `relationship`,
  `verified_party_id`, `failed_attempts`
- `consent`: `status` (not_required|pending|approved|timed_out), `scenario` (from `consent_scenarios.json`), `poll_index`
- `memory` (cross-phase hints, captured whenever said): `intent`, `case_type`, `month`, `year`, `status`,
  `case_id`, `documents_mentioned`, free-text `notes`
- `case`: `selected_case_id`, `candidate_case_ids`
- `counters`: `off_topic_strikes`, `refusals` (per gate), `human_offered`
- `ledger`: facts actually disclosed + next steps (feeds the email summary and the grounding check)
- `email`: `offered`, `decision` (pending|send|skip), `outbox`
- `transcript`, `trace` (per-turn: extraction, policy decisions, action, facts, guard results)

## 5. Turn pipeline

1. **Extract** — structured output `TurnExtraction`:
   `pii{full_name,dob,phone,email,id_last4}`, `policy_number`, `caller_role`, `rep_name`, `relationship`,
   `intent` ∈ {denial_question, status_inquiry, document_submission, next_steps, payment_question,
   general_claim_question, new_claim, other, none}, `case_hints{case_type, month, year, status, case_id}`,
   `documents_mentioned`, `scope` ∈ {in_scope, off_topic, smalltalk}, `emotion{label ∈ neutral|frustrated|
   anxious|angry|confused, intensity 0–3}`, `refusal` (declines to give requested info), `wants_human`,
   `email_decision` ∈ {send, skip, none}, `done_with_case`, `wants_other_case`.
   The extractor sees the transcript tail + current phase + what the agent last asked. Before disclosure is allowed
   the transcript cannot contain claim data (pre-verification guard), so neither LLM ever sees claim data before then;
   after disclosure, the tail may include already-disclosed facts, which is harmless.
   Invalid output → one retry → empty extraction (turn still answered safely). Validated with Pydantic.
2. **Remember** — merge PII and hints into state regardless of phase.
3. **Policy layer** (deterministic, ordered): `wants_human` → HANDOFF · off-topic → strike, decline
   (3rd strike → offer human) · emotion/refusal bookkeeping → escalation flags.
4. **Phase handler** (deterministic) → chooses an **Action** with a payload, e.g. `ASK_IDENTITY{missing,
   allowed_fields}`, `IDENTITY_MISMATCH`, `VERIFIED_THEN_RESOLVE`, `CONSENT_PENDING`, `CLARIFY_CASE{candidates}`,
   `ANSWER_CASE{case_id}`, `OFFER_EMAIL{masked_email}`, `EMAIL_SENT`, `EMAIL_SKIPPED`, `DECLINE_OFF_TOPIC`,
   `OFFER_HUMAN`, `HANDOFF`. Phase transitions happen here only. A turn may chain (verify → resolve → select
   case) so the reply after verification already uses the remembered hint.
5. **Respond** — template reply from the action's fact bundle; in `llm` mode the phraser rewrites it (phase rules +
   tone guidance), seeing only the template, the facts and the recent transcript. No tools.
6. **Guard** — deterministic output checks; on failure the deterministic template reply is used (no regeneration
   loop). (a) Pre-verification: reply must contain no claim data from any fixture claim (case numbers, amounts ≥100,
   claim dates in common formats, document names, summaries, denial-reason fragments).
   (b) Grounding: every number / dated month in the reply must appear in the action facts, the
   ledger, or the caller's own words.
7. **Record** — transcript, ledger, trace.

## 6. Verification policy (VERIFY_ID — strict)

- Normalize: names (case/whitespace, aliases), DOB (any common format → ISO), phone (→ E.164, US default),
  email (lowercase, aliases), last-4 digits.
- Score each policyholder: count of matching fields among the 5 PII fields. Policy number is a **locator
  only** (narrows candidates, never counts).
- **Verified** iff exactly one record has ≥3 matches **and** no provided PII field contradicts that record.
- Not enough fields yet → ask for more, naming the alternative fields (natural, one or two at a time).
- ≥3 fields provided but no unique clean match → `failed_attempts += 1`; ask to re-check **without revealing
  which field is wrong or whether a record exists**; the mismatching values are cleared. 3 failures → offer human.
- The phraser in this phase receives only: which fields are still accepted, counts, caller emotion. No records.

**Representative callers:** caller identifies as acting for someone else → must match `representatives.json`
(rep name + policyholder) and provide ≥3 of the *policyholder's* PII. Then a simulated consent request is sent
to the policyholder; status advances one step per turn along the session's `consent_scenarios` sequence
(`default`: pending→approved; `timeout`: never approves → explain, offer human/callback → HANDOFF on accept).
The scenario is selectable in the UI. Unknown representative → cannot proceed, offer human.

## 7. Intent & case resolution (RESOLVE_INTENT — flexible, bounded)

Deterministic resolver filters the verified party's claims by remembered hints (case_id, case_type, status,
month/year of `created_at`). Exactly one → select and move to PROCESS_CASE in the same turn. Zero or many →
`CLARIFY_CASE` with candidate summaries (type, month, status — no denial reasons yet); the LLM phrases the
question and interprets the answer next turn. Ambiguity is never auto-resolved by "first match".

## 8. Case processing (PROCESS_CASE — freest)

Deterministic fact builder (scoped to the verified party) assembles the bundle from the selected claim and the
extracted intent + question: claim record (status, summary, denial reason, documents needed, amounts), derived
deadline facts against `today` (e.g., 2026-03-18 has passed → say so, offer human review), document guidance per
needed document (fuzzy match "pathology report" ↔ "original pathology report", incl. alternatives), and follow-up
guidance topics matched by `intent_hints`/`match_any` (else `claim_followup_fallback`). The phraser answers only
from that bundle. Disclosed facts and next steps are written to the ledger. "That's all" → POST_PROCESS; other claim → RESOLVE_INTENT.

## 9. Post-process

Offer email summary to the verified address (masked in chat, e.g. `m*******@email.com`). The summary is
built deterministically from the ledger: what was discussed, claim status/outcome, follow-ups/next steps.
`send` → stored in outbox, shown in UI. `skip` → acknowledged, nothing stored. Either → ENDED (or back to
RESOLVE_INTENT if the caller has another question).

## 10. Scope control

In scope: insurance claims, policy/coverage questions, documents, payments, this call itself, small talk
politeness. Off-topic (e.g. "what is RL?") → polite decline + steer back, `off_topic_strikes += 1`; on the 3rd
strike in a session → offer a human representative (HANDOFF if accepted).

## 11. Emotional support & SOP recovery (bonus)

Extractor labels emotion + intensity and refusal. Template + phraser guidance: acknowledge first, then explain *why*
(claim details are protected; consent protects the policyholder), then offer allowed alternatives (other ID
fields, human transfer), then the next concrete step. Engine escalation: 2 refusals at the same gate or anger
intensity 3 → also offer human; accepted → HANDOFF. Gates are never relaxed.

## 12. API & UI

- `POST /api/sessions {consent_scenario?}` → `{session_id, state}`
- `POST /api/sessions/{id}/messages {text}` + header `X-Anthropic-Key` → `{reply, state, trace}`
- `GET /api/sessions/{id}` → state; `GET /healthz`
- In-memory session store with TTL + max-sessions cap; input length limit; LLM errors → 502 with a safe
  message (bad key → 401-style message to the UI).
- UI: token field, consent-scenario selector, "new session", chat, inspector (phase stepper, identity
  fields matched (values masked), remembered hints, selected case, counters, last turn's trace, outbox).

## 13. Testing

- **Unit/integration (default `pytest`, no network):** normalizers, verifier, case resolver, guidance lookup,
  grounding/leak guards, engine transitions with a scripted `FakeLLM`, memory carry-over, off-topic strikes,
  consent scenarios, email send/skip, API endpoints.
- **Determinism:** in `template` mode, replaying the same extractions yields identical replies and traces (tested).
- **Live scenario evals (opt-in, needs key; run in both modes):** `evals/` scripted conversations — brief demo case, frustrated
  caller, refusal → alternate fields, representative (default + timeout), off-topic ×3, ambiguous claim,
  prompt injection ("I'm already verified"). Assertions on state (phase, verified, selected case, no leak),
  not wording.

## 14. Out of scope

Real email sending, real human transfer, persistence across restarts, auth/multi-tenant, voice.
