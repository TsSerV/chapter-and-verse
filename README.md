[![CI](https://github.com/TsSerV/chapter-and-verse/actions/workflows/ci.yml/badge.svg)](https://github.com/TsSerV/chapter-and-verse/actions/workflows/ci.yml)

# Chapter and Verse

Chapter and Verse will answer questions about UK legislation. Each answer will cite the
exact provision behind every claim, at the version in force on the date you ask about.
If no provision supports a claim, it will not answer.

## Status

Early. Currently an HTTP API with two endpoints. `POST /ask` sends the question straight
to Claude and returns the reply. `GET /health` reports that the process can serve
requests. There is no legislation corpus, no retrieval and no citations yet, so the
answers today are only as good as the model's own knowledge.

## Run it

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
Python 3.13 for you.

```sh
git clone https://github.com/TsSerV/chapter-and-verse.git
cd chapter-and-verse
uv sync
```

`POST /ask` calls the Claude API, so it needs a key. Copy the example file and put your
own key in it:

```sh
cp .env.example .env
```

Then start the server:

```sh
uv run uvicorn chapter_and_verse.main:app --reload
```

Ask it something:

```sh
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "When did the Data Protection Act 2018 come into force?"}'
```

The reply looks like this:

```json
{"answer": "On 25 May 2018.", "latency_ms": 1432}
```

Interactive API docs are at http://127.0.0.1:8000/docs.

### Settings

Read from the environment, or from `.env`. The environment wins.

| Name | Required | Default | What it does |
| --- | --- | --- | --- |
| `CLAUDE_API_TOKEN` | yes | none | Your Claude API key. |
| `CLAUDE_MODEL` | no | `claude-haiku-4-5` | Which model answers. |
| `CLAUDE_TIMEOUT_SECONDS` | no | `60.0` | How long to wait for Claude. |

## Test it

```sh
uv run pytest
```

The tests never call Claude, so they need no key. Requests to the API are mocked with
`respx`, and the endpoint tests replace the answerer with a fake.

To run the same three checks CI runs:

```sh
make check
```

That is `ruff check`, `mypy` in strict mode, then `pytest`. CI runs them on every pull
request and on every push to `main`.

## Layout

```
src/chapter_and_verse/   the package
  main.py                FastAPI app and the two endpoints
  models.py              request and response shapes, with input limits
  llm.py                 the Claude call, behind a small Answerer type
  config.py              settings read from the environment
  errors.py              exception types and the handlers that hide internals
tests/                   one test file per module, plus shared fixtures
.github/workflows/       CI
```

## License

MIT. See [LICENSE](LICENSE).
