FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY receptionist/ receptionist/
ENV PATH="/app/.venv/bin:$PATH"
USER 65532:65532
CMD ["sh", "-c", "exec uvicorn receptionist.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
