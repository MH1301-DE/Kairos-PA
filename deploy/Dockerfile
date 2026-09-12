# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build

# curl_cffi ships prebuilt wheels for manylinux, but keep build tools around
# in this throwaway stage in case pip needs to compile anything else.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

# curl is used by the compose healthcheck (deploy/docker-compose.yml)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system kairos && useradd --system --gid kairos --create-home kairos

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

USER kairos
EXPOSE 8000
CMD ["uvicorn", "kairos.api:app", "--host", "0.0.0.0", "--port", "8000"]
