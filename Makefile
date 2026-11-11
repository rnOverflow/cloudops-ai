SHELL := /bin/bash
PY := PYTHONPATH=backend uv run
.DEFAULT_GOAL := help

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

bootstrap: ## Install deps and generate a local .env with random secrets
	uv sync --all-packages --python 3.12
	npm ci --prefix frontend
	./scripts/bootstrap_env.sh

migrate: ## Apply database migrations
	cd backend && uv run alembic upgrade head

dev-backend: ## Run the API + control loop (reload)
	uv run uvicorn --app-dir backend --factory app.main:app_factory --reload --port 8000

dev-frontend: ## Run the UI dev server (proxies /api to :8000)
	npm --prefix frontend run dev

test: ## Run all Python tests (SQLite) + frontend unit tests
	$(PY) pytest
	npm --prefix frontend exec vitest run

test-postgres: ## Run all Python tests against PostgreSQL (TEST_DATABASE_URL)
	TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+psycopg://localhost:5432/cloudops_ai_test} $(PY) pytest

e2e: ## Run only the end-to-end incident recovery tests
	$(PY) pytest tests/e2e -v

demo: ## Scripted end-to-end demo against a running API (default http://localhost:8000)
	uv run python scripts/demo.py --base $${BASE:-http://localhost:8000}

lint: ## Lint Python + typecheck frontend
	uv run ruff check backend/app ai-agent tests
	uv run ruff format --check backend/app ai-agent tests
	npx --prefix frontend tsc -b frontend

security: ## SAST + dependency audit
	uv run bandit -q -r backend/app ai-agent/cloudops_agent services/demo_service -ll
	npm audit --prefix frontend --audit-level=high

images: ## Build all container images
	docker build -f backend/Dockerfile -t cloudops-ai/backend:local .
	docker build -t cloudops-ai/frontend:local frontend
	docker build -t cloudops-ai/demo-service:local services

up: ## Start platform + observability with docker compose
	docker compose up -d --build

up-all: ## Also start the real demo microservices and load generator
	docker compose --profile services up -d --build

down: ## Stop the compose stack
	docker compose --profile services down

k8s-local: ## Deploy to a local kind cluster (build, load, secrets, apply, smoke test)
	./scripts/k8s_local.sh

k8s-down: ## Delete the local kind cluster
	kind delete cluster --name cloudops

tf-validate: ## Validate Terraform
	cd infrastructure/terraform/aws && terraform init -backend=false -input=false >/dev/null && terraform validate

smoke: ## Smoke-test a running stack
	./scripts/smoke_test.sh $${BASE:-http://localhost:8000}

.PHONY: help bootstrap migrate dev-backend dev-frontend test test-postgres e2e demo lint security images up up-all down k8s-local k8s-down tf-validate smoke
