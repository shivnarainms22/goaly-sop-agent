# Goaly take-home — SOP-guided insurance claims agent

Design: `docs/sop-agent-design.md` (source of truth). Brief: `docs/assignment.md`. Plan: `docs/sop-agent-plan.md`.

## Stack
- Python 3.12+ (dev machine has 3.13), managed with `uv`
- FastAPI + uvicorn, Pydantic v2, `anthropic` SDK
- Frontend: single static `sop_agent/web/index.html` (vanilla JS, no build step)
- Tests: pytest (+ httpx TestClient). Lint/format: ruff
- Docker: `Dockerfile` + `docker-compose.yml`

## Commands
- Install: `uv sync`
- Test (offline, default): `uv run pytest -q`
- Live evals (needs `ANTHROPIC_API_KEY`): `uv run python -m evals.run`
- Lint/format: `uv run ruff check . && uv run ruff format --check .` (fix: `uv run ruff check --fix . && uv run ruff format .`)
- Run locally: `uv run uvicorn sop_agent.api.app:app --reload --port 8000` → http://localhost:8000
- Docker: `docker compose up --build`

## Conventions
- Code owns the workflow; the LLM never decides phase transitions or gates. Never put claim data in an LLM
  context before `verified_party_id` is set (and consent approved for representatives).
- All LLM calls go through the `LLMClient` protocol so tests use `FakeLLM` — no network in `pytest`.
- Fixtures in `apps/insurance_claims/fixtures/` are starter data; do not edit them.
- No secrets in code or logs; the API key arrives per request (`X-Anthropic-Key`) or from env.
- Work on `feat/*` branches, never commit to `main` directly.
