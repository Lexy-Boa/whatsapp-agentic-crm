FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pip dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy runtime source and local assets needed by both app and worker images.
COPY src/ ./src/
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY data/ ./data/
COPY scripts/ ./scripts/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
