check:
	uv run ruff check src tests migrations serving
	uv run mypy src serving
	uv run pytest
