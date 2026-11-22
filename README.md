[![CI](https://github.com/TsSerV/chapter-and-verse/actions/workflows/ci.yml/badge.svg)](https://github.com/TsSerV/chapter-and-verse/actions/workflows/ci.yml)

# Chapter and Verse

Chapter and Verse will answer questions about UK legislation. Each answer will cite the
exact provision behind every claim, at the version in force on the date you ask about.
If no provision supports a claim, it will not answer.

## Status

Early. Currently an HTTP API with three endpoints. `POST /ask` finds the sections of the
Employment Rights Act 1996 closest in meaning to the question, gives them to Claude with
the question, and returns the answer with a citation after each claim and the sections it
was given. All requests share one pooled connection to Claude. A call that gets no
response, such as a timeout or a dropped connection, is retried up to three times with
backoff. An error status from Claude is not retried. Every successful answer is stored
with its question, the sections it was given and the date their text is in force from,
the model, latency and request ID, and `GET /answers/{answer_id}` reads it back.
`GET /health` reports that the process can serve requests.

Open models now run on a GPU in AWS, served by vLLM behind KServe on an EKS cluster that
exists only while it is in use. Karpenter starts a GPU node when a model needs one, and
KEDA adds a second replica under load. An MLflow model registry records which model is
served, at which exact commit, with which settings. A benchmark in `serving/benchmark.py`
measures time to first token, time per output token and throughput for each version, and
each measurement is its own run in MLflow. `/ask` does not use the open models yet. It
still calls Claude.

One Act is loaded: the Employment Rights Act 1996, 410 sections at the version in force
from 30 October 2026. The citations are not checked yet. Nothing verifies that a cited
section says what the answer claims, and the service does not refuse on its own when the
sections do not hold the answer. Both come next. [How it answers](docs/answers.md) has the
steps and a first look at the results.

## Results

Measured on AWS, on `g6.xlarge` nodes with one NVIDIA L4 GPU each. Each result links to
how it was measured.

| Measure | Model | Result |
| --- | --- | --- |
| Requests of 8,192 tokens at once on one L4 | Qwen3-8B in bf16 | [2.80](docs/measurements.md#what-one-l4-holds) |
| Requests of 8,192 tokens at once on one L4 | Qwen3-8B-FP8 | [8.39](docs/measurements.md#what-one-l4-holds) |
| Time to first token at p95, 16 clients on one L4 | Qwen3-8B in bf16 | [23.7 seconds](docs/measurements.md#how-fast-it-answers) |
| Time to first token at p95, 16 clients on one L4 | Qwen3-8B-FP8 | [2.5 seconds](docs/measurements.md#how-fast-it-answers) |
| Output tokens per second, 16 clients on one L4 | Qwen3-8B in bf16 | [106.9](docs/measurements.md#how-fast-it-answers) |
| Output tokens per second, 16 clients on one L4 | Qwen3-8B-FP8 | [151.4](docs/measurements.md#how-fast-it-answers) |
| `kubectl apply` to a Ready model through KServe | Qwen3-1.7B | [485 seconds](docs/measurements.md#how-long-a-start-takes) |
| Load start to a second replica Ready, on a new GPU node | Qwen3-1.7B | [512 seconds](docs/measurements.md#how-it-scales) |

## Run it

Clone the repository and copy the example settings file:

```sh
git clone https://github.com/TsSerV/chapter-and-verse.git
cd chapter-and-verse
cp .env.example .env
```

`POST /ask` calls the Claude API, so put your own key in `.env` as `CLAUDE_API_TOKEN`.

### With Docker Compose

This is the quickest way to run everything. You need
[Docker with Compose](https://docs.docker.com/compose/install/). It runs the API with
Postgres, the database it will use when deployed.

Set `POSTGRES_PASSWORD` in `.env` to a new password of letters and digits, for example
from `openssl rand -hex 24`. Then:

```sh
docker compose up --build
```

Compose starts Postgres and waits until it is healthy. Then it applies the migrations and
starts the API. The data stays in a Docker volume between runs. `docker compose down -v`
deletes it.

Load the Act once, from a second terminal. It stays in the volume:

```sh
docker compose run --rm api python -m chapter_and_verse.ingest ukpga/1996/18
```

### With uv, for development

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
Python 3.13 for you. You also need Docker, because `/ask` searches with pgvector and the
Postgres from Compose has it.

```sh
uv sync
```

Set `POSTGRES_PASSWORD` in `.env` as for Compose. Start Postgres, and point the service at
it for this terminal. Compose publishes it on port 5433, on your own machine only:

```sh
docker compose up -d db
export DATABASE_URL="postgresql+asyncpg://postgres:$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)@127.0.0.1:5433/postgres"
```

Create the tables and load the Act. The first run also downloads the embedding model:

```sh
uv run alembic upgrade head
uv run python -m chapter_and_verse.ingest ukpga/1996/18
```

Then start the server. `--reload` restarts it when you change the code:

```sh
uv run uvicorn chapter_and_verse.main:app --reload
```

Without `DATABASE_URL` the service uses a SQLite file, which is enough for the unit tests
and not for `/ask`.

### Ask it something

Compose, uv and [kind](docs/kubernetes.md) all serve the API on port 8000, reachable only
from your own machine.

```sh
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How much notice must my employer give me before ending my job?"}'
```

The reply looks like this. `sources` has five sections, cut to two here:

```json
{
  "answer_id": 2,
  "answer": "The notice your employer must give you depends on your length of continuous employment:\n\n- **Less than 2 years**: at least one week's notice [s. 86(1)(a)]\n- **2 years or more but less than 12 years**: at least one week's notice for each year of continuous employment [s. 86(1)(b)]\n- **12 years or more**: at least twelve weeks' notice [s. 86(1)(c)]\n\nThese requirements apply if you have been continuously employed for one month or more [s. 86(1)].",
  "sources": [
    {"act": "ukpga/1996/18", "number": "86", "title": "Rights of employer and employee to minimum notice.", "uri": "http://www.legislation.gov.uk/ukpga/1996/18/section/86", "valid_from": "2026-10-30"},
    {"act": "ukpga/1996/18", "number": "150", "title": "Resignation.", "uri": "http://www.legislation.gov.uk/ukpga/1996/18/section/150", "valid_from": "2026-10-30"}
  ],
  "latency_ms": 1885
}
```

Read the stored answer back by its ID:

```sh
curl http://127.0.0.1:8000/answers/2
```

It has the same answer and sources, shortened here, with the question, the model, the
request ID and the time it was stored:

```json
{
  "id": 2,
  "request_id": "c901bdff-2706-451f-ba0c-1c74adf31b2f",
  "question": "How much notice must my employer give me before ending my job?",
  "answer": "The notice your employer must give you depends on your length of continuous employment: ...",
  "sources": [
    {"act": "ukpga/1996/18", "number": "86", "title": "Rights of employer and employee to minimum notice.", "uri": "http://www.legislation.gov.uk/ukpga/1996/18/section/86", "valid_from": "2026-10-30"}
  ],
  "model": "claude-haiku-4-5",
  "latency_ms": 1885,
  "created_at": "2026-11-21T15:43:51.634819Z"
}
```

An ID that does not exist returns 404.

Logs are structured JSON, one object per line. Every line written during a request has a
`request_id`, and the response returns the same value in its `X-Request-ID` header, so
quote it when you report a problem. One `/ask` call logs a line like this:

```json
{"outcome": "ok", "question_length": 62, "sections": ["86", "150", "52", "142", "136"], "latency_ms": 1885, "event": "ask", "request_id": "c901bdff-2706-451f-ba0c-1c74adf31b2f", "level": "info", "timestamp": "2026-11-21T15:43:53.521307Z"}
```

The question itself is never logged, only its length and the sections found for it.

Interactive API docs are at http://127.0.0.1:8000/docs.

### Settings

Read from the environment, or from `.env`. The environment wins. On kind, the chart sets
them from `values.yaml` and [the two Secrets](docs/kubernetes.md).

| Name | Required | Default | What it does |
| --- | --- | --- | --- |
| `CLAUDE_API_TOKEN` | yes | none | Your Claude API key. |
| `CLAUDE_MODEL` | no | `claude-haiku-4-5` | Which model answers. |
| `CLAUDE_TIMEOUT_SECONDS` | no | `60.0` | How long to wait for Claude. |
| `DATABASE_URL` | no | `sqlite+aiosqlite:///./chapter_and_verse.db` | Which database to use. `/ask` needs Postgres with pgvector. Compose sets it to its own Postgres. |
| `POSTGRES_PASSWORD` | with compose or kind | none | Password for Postgres. Compose passes it to its container. On kind, it goes into the `postgres` Secret. |
| `TEST_DATABASE_URL` | no | none | A Postgres server for the retrieval tests. They create and drop a database of their own on it. |
| `FASTEMBED_CACHE_PATH` | no | the temp folder | Where the embedding model is kept. The image sets it to the copy inside the image. |

The last two are read from the environment only, not from `.env`.

## Guides

- [How it answers](docs/answers.md): loading an Act, finding sections, and a first look at
  the results.
- [Running on Kubernetes](docs/kubernetes.md): the service on a local kind cluster.
- [Registering models in MLflow](docs/model-registry.md): which model is served, at which
  commit, with which settings.
- [Serving models on a GPU in AWS](docs/gpu-on-aws.md): a temporary EKS cluster, what it
  costs, and how to create and destroy it.
- [Measurements](docs/measurements.md): what one NVIDIA L4 holds, how long a model takes
  to start, and how it scales.

## Test it

```sh
uv run pytest
```

The tests never call Claude, so they need no key. Requests to the API are mocked with
`respx`, and the endpoint tests replace the answerer with a fake. Each test gets its own
SQLite file. A test also checks that every relative link in the README and in `docs/`
leads to a file and a heading that exist.

The search needs pgvector, so its tests run against a real Postgres, in a database of
their own. They are skipped unless `TEST_DATABASE_URL` is set. CI sets it. To run them
against the Postgres from Compose:

```sh
docker compose up -d db
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)@127.0.0.1:5433/postgres"
uv run pytest
```

To run the same three checks CI runs:

```sh
make check
```

That is `ruff check`, `mypy` in strict mode, then `pytest`. CI runs them on every pull
request and on every push to `main`. CI also builds the Docker image and imports the app
inside it, so a change that breaks the image fails too. It also runs
`helm lint --strict` on the chart, and `terraform fmt -check` and `terraform validate` on
the Terraform, with no AWS credentials.

## Layout

```
src/chapter_and_verse/   the package
  main.py                FastAPI app, startup (client pool, database, logging), the endpoints
  models.py              request and response shapes, with input limits
  llm.py                 the prompt, the Claude call and its retries, behind a small Answerer type
  legislation.py         downloads an Act from legislation.gov.uk and reads its sections
  embeddings.py          text to vectors, with a small model on the CPU
  ingest.py              loads an Act: sections, chunks and their vectors
  retrieval.py           finds the sections closest in meaning to a question
  db.py                  the answers, sections and chunks tables, and a database session per request
  config.py              settings read from the environment
  errors.py              exception types and the handlers that hide internals
  middleware.py          gives each request an ID for the logs and a header
tests/                   tests per module, a concurrency test, shared fixtures
migrations/              Alembic migrations, one file per schema change
Dockerfile               two-stage image that runs as a non-root user
compose.yaml             Postgres with pgvector, then the migrations, then the API
charts/                  Helm chart: migrations as a Job, then the API and its Service
serving/                 registry commands, KServe manifests from an alias, a load generator, and a benchmark
deploy/kind/             Postgres for a local kind cluster only
deploy/mlflow/           the MLflow server for the model registry, on your own machine
deploy/grafana/          Grafana settings and the dashboard for vLLM
deploy/aws/              Karpenter's GPU node pool, and the GPU check Job, for EKS
infra/aws/               Terraform for a temporary EKS cluster, and the IAM and queue for Karpenter
docs/                    how it answers, guides for kind, the model registry and the GPU cluster, and the measurements
.github/workflows/       CI: the checks, the image build, the chart lint, the Terraform checks
```

## License

MIT. See [LICENSE](LICENSE).
