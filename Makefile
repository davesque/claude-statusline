.PHONY: test lint format typecheck check smoke sync

## Run all tests with coverage
test:
	uv run pytest

## Lint with ruff
lint:
	uv run ruff check .

## Format with ruff (fix in place)
format:
	uv run ruff format .

## Type check with ty
typecheck:
	uv run ty check

## Run all checks (lint + format check + typecheck + test)
check: lint
	uv run ruff format --check .
	$(MAKE) typecheck
	$(MAKE) test

## Smoke test with sample JSON
smoke:
	echo '{"model":{"display_name":"Opus 4.6"},"session_id":"test","context_window":{"used_percentage":42,"context_window_size":200000,"total_input_tokens":50000,"total_output_tokens":10000},"cost":{"total_cost_usd":1.23,"total_duration_ms":312000},"workspace":{"current_dir":"/tmp"}}' | ./claude-statusline/statusline-command.py

## Install dev dependencies
sync:
	uv sync
