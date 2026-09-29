run:
	docker compose up -d
	python scripts/pull_models.py

test:
	ruff check . && mypy . && pytest -x

dev:
	uvicorn doc_agent.main:app --reload
