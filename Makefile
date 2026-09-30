check:
	uv run ruff check src tests migrations
	uv run mypy src
	uv run pytest
