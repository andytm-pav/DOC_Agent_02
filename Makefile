.PHONY: run test dev build

run:
	docker compose up -d
	python scripts/pull_models.py

test:
	ruff check . && mypy . && pytest -x

dev:
	uvicorn doc_agent.main:app --reload

build:
	docker compose build
