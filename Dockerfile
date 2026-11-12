FROM ghcr.io/astral-sh/uv:0.13.4 AS uv
FROM python:3.11-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY scripts ./scripts
RUN uv sync --locked --no-dev && useradd --system --uid 10001 --no-create-home flight
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
CMD ["/app/.venv/bin/python", "-m", "scripts.relay"]
