.PHONY: help install dev lint format type test cov run docker-build docker-run clean

PY ?= python3
APP := docsifer.main:app
PORT ?= 7860
HOST ?= 0.0.0.0

help:  ## Show this help
	@awk 'BEGIN {FS=":.*##"; printf "Targets:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install runtime + dev dependencies (using pip + requirements.txt)
	$(PY) -m pip install --upgrade pip wheel
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install pytest pytest-asyncio ruff mypy fakeredis

dev: install  ## Install in editable / dev mode
	$(PY) -m pip install -e .

lint:  ## Lint with ruff
	ruff check .

format:  ## Format with ruff
	ruff format .

type:  ## Type-check with mypy
	mypy

test:  ## Run pytest
	pytest -q

cov:  ## Run pytest with coverage
	pytest --cov=docsifer --cov-report=term-missing

run:  ## Run the dev server (uvicorn, autoreload)
	uvicorn $(APP) --host $(HOST) --port $(PORT) --reload

docker-build:  ## Build the production Docker image
	docker build -t docsifer:local .

docker-run:  ## Run the Docker image on $(PORT)
	docker run --rm -p $(PORT):7860 --env-file .env docsifer:local

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
