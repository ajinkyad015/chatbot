.PHONY: install dev test lint run down

install:
	python -m pip install -r requirements-dev.txt

infra:
	docker compose up -d db redis

down:
	docker compose down

run:
	uvicorn app:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest

lint:
	ruff check .
