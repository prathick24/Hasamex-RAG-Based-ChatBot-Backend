.PHONY: setup run run-ui test test-cov lint lint-fix format check clean help

help: ## Show available commands
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies with uv
	@echo "==> Installing dependencies"
	uv sync --dev

run: ## Start the FastAPI backend
	@echo "==> Starting FastAPI backend on :8000"
	uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

run-ui: ## Start the Streamlit frontend
	@echo "==> Starting Streamlit frontend on :8501"
	uv run streamlit run frontend/app.py

test: ## Run the test suite
	uv run pytest tests/ -v

test-cov: ## Run tests with coverage report
	@clear 2>NUL || cls
	uv run coverage run -m pytest tests/
	uv run coverage report
	uv run coverage xml
	uv run diff-cover coverage.xml --fail-under=80 --quiet

lint: ## Lint with Ruff
	uv run ruff check src

lint-fix: ## Auto-fix lint issues
	uv run ruff check --fix src

format: ## Format with Ruff
	uv run ruff format src

check: ## Lint + format check
	@echo "==> Lint"
	uv run ruff check src
	@echo "==> Format check"
	uv run ruff format --check src

clean: ## Remove cache files
	rm -rf __pycache__ .pytest_cache .ruff_cache .mypy_cache htmlcov coverage.xml .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true