FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install uv (the package manager your project actually uses)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy dependency files first (better Docker layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen

# Copy the rest of the application
COPY . .

# Expose the port Render provides
EXPOSE 8000

# Run migrations, seeders, then start the server
CMD sh -c "uv run alembic upgrade head && uv run python -m ycpa.seeders.seed_rbac && uv run python -m ycpa.seeders.seed_subscription_plans && uv run uvicorn ycpa.main:app --host 0.0.0.0 --port $PORT"