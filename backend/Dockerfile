FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv --no-cache-dir

# Copy dependency files first for layer caching
COPY pyproject.toml .
RUN uv sync --no-dev

# Copy application code
COPY app/ app/

# Cloud Run sets PORT env var; fall back to 8765
ENV FINCOACH_PORT=8080

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
