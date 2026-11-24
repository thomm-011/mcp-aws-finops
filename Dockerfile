# syntax=docker/dockerfile:1

## ---- Builder ----------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Install only the runtime dependency set (no dev group) into /app/.venv,
# layered separately from the source so dependency changes cache well.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src/ src/
COPY README.md LICENSE CHANGELOG.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

## ---- Runtime ------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ARG VERSION=0.2.0
LABEL org.opencontainers.image.title="mcp-aws-finops" \
      org.opencontainers.image.description="Read-only MCP server that answers AWS cost (FinOps) questions for AI agents" \
      org.opencontainers.image.source="https://github.com/thomm-011/mcp-aws-finops" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"

RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
WORKDIR /home/app

ENTRYPOINT ["mcp-aws-finops"]
CMD ["--demo"]
