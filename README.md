# Chapter and Verse

Chapter and Verse will answer questions about UK legislation. Each answer will cite the
exact provision behind every claim, at the version in force on the date you ask about.
If no provision supports a claim, it will not answer.

## Status

Early. The repository has the Python package, one smoke test and CI. There is no API yet.

## Run it

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
Python 3.13 for you.

```sh
git clone https://github.com/TsSerV/chapter-and-verse.git
cd chapter-and-verse
uv sync
uv run chapter-and-verse
```

For now the last command only prints a greeting.

## Test it

```sh
uv run pytest
```

CI runs `ruff`, `mypy` and `pytest` on every pull request.

## License

MIT. See [LICENSE](LICENSE).
