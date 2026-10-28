PYTHON ?= uv run

.PHONY: dev-api dev-web test lint types demo

dev-api:
	cd backend && uv run uvicorn tokenpilot.main:create_app --factory --host 127.0.0.1 --port 8787 --reload

dev-web:
	cd frontend && if [ -f ../.env ]; then set -a; . ../.env; set +a; fi; npm run dev -- -H 127.0.0.1 -p 3000

test:
	cd backend && uv run pytest -q
	cd frontend && npx vitest run

lint:
	cd backend && uv run ruff check . && uv run mypy tokenpilot
	cd frontend && npm run lint && npx tsc --noEmit

types:
	cd backend && uv run python -m tokenpilot.main --export-openapi ../frontend/openapi.json
	cd frontend && npx openapi-typescript openapi.json -o lib/api-types.ts

demo:
	bash demo/scripts/run_demo.sh
