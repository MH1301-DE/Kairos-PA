.PHONY: up down logs migrate test lint dev

up:
	docker compose -f deploy/docker-compose.dev.yml up -d

down:
	docker compose -f deploy/docker-compose.dev.yml down

logs:
	docker compose -f deploy/docker-compose.dev.yml logs -f

migrate:
	.venv/bin/python -m alembic upgrade head || .venv/Scripts/python -m alembic upgrade head

test:
	.venv/bin/python -m pytest -q || .venv/Scripts/python -m pytest -q

lint:
	.venv/bin/python -m ruff check src tests || .venv/Scripts/python -m ruff check src tests
	.venv/bin/python -m mypy src || .venv/Scripts/python -m mypy src

dev:
	.venv/bin/uvicorn kairos.api:app --reload --host 0.0.0.0 --port 8000 || .venv/Scripts/uvicorn kairos.api:app --reload --host 0.0.0.0 --port 8000
