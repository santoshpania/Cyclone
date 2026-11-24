.PHONY: db-up db-migrate api worker web dev test lint gen-api check-terms

db-up:            ## start local PostGIS
	docker compose up -d --wait db

db-migrate:       ## migrate + enable app_backend login (needs backend/.env)
	cd backend && uv run python scripts/dev_db.py

api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

worker:
	cd backend && uv run procrastinate --app=app.workers.app.app worker --queues=imports

web:
	cd web && pnpm dev

test:             ## backend (not live) + web unit tests
	cd backend && uv run pytest
	cd web && pnpm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd web && pnpm lint && pnpm typecheck
	./scripts/check_no_industry_terms.sh

gen-api:          ## regenerate the typed web client from the backend's OpenAPI
	cd backend && uv run python scripts/export_openapi.py ../web/openapi.json
	cd web && pnpm gen:api

check-terms:
	./scripts/check_no_industry_terms.sh
