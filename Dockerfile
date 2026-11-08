FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /uvx /bin/

ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 app && mkdir /app && chown app /app
WORKDIR /app
USER app

# Dependencies first (cached layer), then the code.
COPY --chown=app pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=app sop_agent ./sop_agent
COPY --chown=app apps ./apps
RUN uv sync --frozen --no-dev

ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request as u; u.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/healthz', timeout=2)"

CMD ["sh", "-c", "exec uvicorn sop_agent.api.app:app --host 0.0.0.0 --port ${PORT}"]
