.PHONY: up down logs migrate test lint dev

up:
	docker compose -f deploy/docker-compose.dev.yml up -d

down:
	docker compose -f deploy/docker-compose.dev.yml down

logs:
	docker compose -f deploy/docker-compose.dev.yml logs -f

migrate:
	uv run alembic upgrade head

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run mypy src

dev:
	uv run uvicorn kairos.api:app --reload --host 0.0.0.0 --port 8000
