check:
	uv run ruff check src tests
	uv run mypy src
	uv run pytest
