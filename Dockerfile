# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder

ARG COMMIT_HASH=unknown

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci

COPY frontend/ ./
RUN VITE_COMMIT_HASH=${COMMIT_HASH} npm run build \
    && find dist -name '*.map' -delete


# Stage 2: Install Python dependencies (uv stays in this stage only)
FROM python:3.13-slim AS python-deps

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


# Stage 3: Final runtime (no uv, no source maps)
FROM python:3.13-slim

ARG COMMIT_HASH=unknown

WORKDIR /app

ENV COMMIT_HASH=${COMMIT_HASH} \
    PATH="/app/.venv/bin:$PATH"

# Copy installed venv from deps stage
COPY --from=python-deps /app/.venv ./.venv

# Copy dependency metadata (pyproject.toml needed by app for version info)
COPY pyproject.toml ./

# Copy application code
COPY app/ ./app/

# Copy license attributions
COPY LICENSES.md ./

# Copy built frontend from first stage (source maps already stripped)
COPY --from=frontend-builder /build/dist ./frontend/dist

# Create data directory for SQLite database
RUN mkdir -p /app/data

EXPOSE 8000

# Run uvicorn directly from the venv (no uv needed at runtime)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
