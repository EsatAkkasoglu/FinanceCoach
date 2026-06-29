FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv --no-cache-dir

# Copy dependency files first for layer caching
COPY pyproject.toml .
RUN uv sync --no-dev

# Copy application code
COPY app/ app/

# Drop root: run as an unprivileged user (defense-in-depth — a container escape
# starts without root). appuser owns /app so the synced venv, joblib cache, and
# any local Chroma/SQLite paths stay writable at runtime.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Cloud Run sets PORT env var; fall back to 8765
ENV FINCOACH_PORT=8080

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
