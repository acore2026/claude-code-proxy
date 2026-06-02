FROM ghcr.io/astral-sh/uv:bookworm-slim

ENV UV_PYTHON=3.11

# Copy the project into the image
ADD . /app

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app
RUN uv sync --locked --no-dev

CMD ["uv", "run", "--no-sync", "claude-code-proxy"]
