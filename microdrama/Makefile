# Reproducible offline checks for the micro-drama module (SPEC §13).
# Every target runs in OFFLINE_MOCK mode: no paid requests, no cloud resources,
# no public actions. PostgreSQL/Redis test servers are started automatically
# by the test suite as isolated temporary processes (see README.md).

VENV ?= .venv
PY ?= $(VENV)/bin/python
export PYTHONPATH := src
export MICRODRAMA_EXECUTION_MODE := OFFLINE_MOCK

.PHONY: help install contracts contracts-check lint format test-unit test-contract \
        test-integration test check services-up services-down pilot

help:
	@echo "install           create .venv from requirements.lock"
	@echo "contracts         regenerate contracts/ JSON schemas + examples, then validate them"
	@echo "contracts-check   fail if committed contracts/ drift from the Python source"
	@echo "lint              ruff lint + format check"
	@echo "test-unit         unit tests (starts isolated PostgreSQL/Redis as needed)"
	@echo "test-contract     contract tests"
	@echo "test-integration  integration tests"
	@echo "check             contracts-check + lint + all test suites"
	@echo "pilot             run the offline two-gate mock demo (runbooks/pilot.md)"

install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip==25.2
	$(VENV)/bin/pip install -r requirements.lock

contracts:
	$(PY) -m microdrama.contracts.build --write

contracts-check:
	$(PY) -m microdrama.contracts.build --check

lint:
	$(PY) -m ruff check src tests tools
	$(PY) -m ruff format --check src tests tools

format:
	$(PY) -m ruff format src tests tools
	$(PY) -m ruff check --fix src tests tools

test-unit:
	$(PY) -m pytest tests/unit

test-contract:
	$(PY) -m pytest tests/contract

test-integration:
	$(PY) -m pytest tests/integration

test:
	$(PY) -m pytest tests

check: contracts-check lint test-unit test-contract test-integration
	@echo "make check: all offline checks passed"

# One reproducible offline command: proposal → Gate 1 → episode → fake render →
# real FFmpeg edit → QA → Gate 2 (identity lock) → fake publish → social →
# analytics → janitors. No paid or public effects (runbooks/pilot.md).
pilot:
	$(PY) -m microdrama.pipeline.demo

# Long-lived local services for manual exploration (no Docker needed).
services-up:
	$(PY) -m microdrama.testing.services up

services-down:
	$(PY) -m microdrama.testing.services down
