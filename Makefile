.PHONY: help install dev lint format test check run clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -r requirements.txt

dev: ## Install the package in editable mode with dev dependencies
	pip install -e ".[dev]"

lint: ## Run Ruff linter and formatter checks
	ruff check app tests
	ruff format --check app tests

format: ## Auto-format code with Ruff
	ruff format app tests
	ruff check --fix app tests

test: ## Run the pytest suite
	pytest

check: lint test ## Run linting and tests

run: ## Run the development server with auto-reload
	uvicorn app.main:app --reload

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
