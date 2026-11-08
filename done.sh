#!/usr/bin/env bash
# Project done-gate: offline tests + lint/format. Live evals need a key: uv run python -m evals.run
set -euo pipefail
cd "$(dirname "$0")"
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
