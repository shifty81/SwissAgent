# SwissAgent Dockerfile
# Build:  docker build -t swissagent .
# Run:    docker run -p 8000:8000 -v $(pwd)/workspace:/app/workspace swissagent

FROM python:3.11-slim

# System deps (git required for git module)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || true

# Copy source
COPY . .

# Re-install in editable mode now that source is present
RUN pip install --no-cache-dir -e .

# Create runtime directories
RUN mkdir -p workspace projects cache models plugins logs

EXPOSE 8000

# Default: launch the web IDE (no browser auto-open inside container)
CMD ["python", "-m", "core.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
