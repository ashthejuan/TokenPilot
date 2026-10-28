PYTHON ?= uv run

.PHONY: dev-api dev-web test lint demo

dev-api:
	cd backend && uv run uvicorn tokenpilot.main:create_app --factory --host 127.0.0.1 --port 8787 --reload

dev-web:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check . && uv run mypy tokenpilot

demo:
	bash demo/scripts/run_demo.sh
