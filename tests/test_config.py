from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from chapter_and_verse.config import Settings

MIGRATIONS = Path(__file__).parents[1] / "migrations"


@pytest.fixture
def no_claude_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Like the migration job: a database URL, no Claude key and no .env file.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_API_TOKEN", raising=False)
    path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    return path


def test_migrations_run_without_the_claude_key(no_claude_key: Path) -> None:
    # No ini file. With one, env.py runs fileConfig(), which replaces logging for later tests.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{no_claude_key}")
    tables = inspect(engine).get_table_names()
    engine.dispose()
    assert "answers" in tables


@pytest.mark.usefixtures("no_claude_key")
def test_api_settings_still_need_the_claude_key() -> None:
    with pytest.raises(ValidationError, match="claude_api_token"):
        Settings()
