FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Enable bytecode compilation and optimization
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    WS_HOST=0.0.0.0 \
    WS_PORT=8765

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy application files
COPY . .

# Final project sync
RUN uv sync --frozen --no-dev

# Put virtualenv in PATH
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8765

CMD ["python", "main.py"]
