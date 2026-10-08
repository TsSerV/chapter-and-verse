[![CI](https://github.com/TsSerV/chapter-and-verse/actions/workflows/ci.yml/badge.svg)](https://github.com/TsSerV/chapter-and-verse/actions/workflows/ci.yml)

# Chapter and Verse

Chapter and Verse will answer questions about UK legislation. Each answer will cite the
exact provision behind every claim, at the version in force on the date you ask about.
If no provision supports a claim, it will not answer.

## Status

Early. Currently an HTTP API with three endpoints. `POST /ask` sends the question to
Claude and returns the reply. All requests share one pooled connection to Claude. A call
that gets no response, such as a timeout or a dropped connection, is retried up to three
times with backoff. An error status from Claude is not retried. Every successful answer
is stored with its question, model, latency and request ID, and
`GET /answers/{answer_id}` reads it back. `GET /health` reports that the process can
serve requests.

There is no legislation corpus, no retrieval and no citations yet, so the answers today
are only as good as the model's own knowledge.

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

### With uv, for development

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
Python 3.13 for you.

```sh
uv sync
```

Create the database. Unless you set `DATABASE_URL`, it is a SQLite file in the project
folder:

```sh
uv run alembic upgrade head
```

Then start the server. `--reload` restarts it when you change the code:

```sh
uv run uvicorn chapter_and_verse.main:app --reload
```

### On Kubernetes, with kind

This runs the service on a local Kubernetes cluster, the same way it runs when deployed.
You need Docker, [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation),
[kubectl](https://kubernetes.io/docs/tasks/tools/) and
[Helm 4](https://helm.sh/docs/intro/install/). Set `POSTGRES_PASSWORD` in `.env` as for
compose.

Create the cluster and a namespace:

```sh
kind create cluster --name chapter-and-verse
kubectl create namespace chapter-and-verse
kubectl config set-context --current --namespace chapter-and-verse
```

Create two Secrets from `.env`, one value in each. Only the API pods read the Claude key.
The migrations get the database password only.

```sh
kubectl create secret generic postgres \
  --from-literal=password="$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
kubectl create secret generic claude-api \
  --from-literal=CLAUDE_API_TOKEN="$(grep '^CLAUDE_API_TOKEN=' .env | cut -d= -f2-)"
```

Start Postgres. `deploy/kind/postgres.yaml` is for a local cluster only. A deployed
service uses a managed database.

```sh
kubectl apply -f deploy/kind/postgres.yaml
kubectl rollout status statefulset/postgres
```

Build the image and load it into the cluster. The kind node cannot see your local Docker
images:

```sh
docker build -t chapter-and-verse:dev .
kind load docker-image chapter-and-verse:dev --name chapter-and-verse
```

Install the chart:

```sh
helm upgrade --install chapter-and-verse charts/chapter-and-verse --wait
```

A Job applies the migrations first, then two API pods start. They run as a non-root user
with a read-only filesystem and pass the restricted Pod Security Standard. When a pod
stops, it finishes the requests it already has.

After a new build, load it again and run the same `helm upgrade` line to apply any new
migrations. Then run `kubectl rollout restart deployment/chapter-and-verse`. The tag
stays `dev`, so without the restart the pods keep the old image.

To reach the API, keep this running in its own terminal:

```sh
kubectl port-forward svc/chapter-and-verse 8000:8000
```

`kind delete cluster --name chapter-and-verse` removes everything, the stored answers
included.

### Ask it something

All three ways serve the API on port 8000, reachable only from your own machine.

```sh
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "When did the Data Protection Act 2018 come into force?"}'
```

The reply looks like this:

```json
{"answer_id": 1, "answer": "On 25 May 2018.", "latency_ms": 1432}
```

Read the stored answer back by its ID:

```sh
curl http://127.0.0.1:8000/answers/1
```

```json
{"id": 1, "request_id": "5f0c2d1e-8a47-4b8e-9d3a-2e61c7f4b0a9", "question": "When did the Data Protection Act 2018 come into force?", "answer": "On 25 May 2018.", "model": "claude-haiku-4-5", "latency_ms": 1432, "created_at": "2026-09-27T08:01:32"}
```

An ID that does not exist returns 404.

Logs are structured JSON, one object per line. Every line written during a request has a
`request_id`, and the response returns the same value in its `X-Request-ID` header, so
quote it when you report a problem. One `/ask` call logs a line like this:

```json
{"outcome": "ok", "question_length": 54, "latency_ms": 1432, "event": "ask", "request_id": "5f0c2d1e-8a47-4b8e-9d3a-2e61c7f4b0a9", "level": "info", "timestamp": "2026-09-27T08:01:32.740200Z"}
```

The question itself is never logged, only its length.

Interactive API docs are at http://127.0.0.1:8000/docs.

### Settings

Read from the environment, or from `.env`. The environment wins. On kind, the chart sets
them from `values.yaml` and the two Secrets.

| Name | Required | Default | What it does |
| --- | --- | --- | --- |
| `CLAUDE_API_TOKEN` | yes | none | Your Claude API key. |
| `CLAUDE_MODEL` | no | `claude-haiku-4-5` | Which model answers. |
| `CLAUDE_TIMEOUT_SECONDS` | no | `60.0` | How long to wait for Claude. |
| `DATABASE_URL` | no | `sqlite+aiosqlite:///./chapter_and_verse.db` | Which database to use. Compose sets it to its own Postgres. |
| `POSTGRES_PASSWORD` | with compose or kind | none | Password for Postgres. Compose passes it to its container. On kind, it goes into the `postgres` Secret. |

## Test it

```sh
uv run pytest
```

The tests never call Claude, so they need no key. Requests to the API are mocked with
`respx`, and the endpoint tests replace the answerer with a fake. Each test gets its own
SQLite file.

To run the same three checks CI runs:

```sh
make check
```

That is `ruff check`, `mypy` in strict mode, then `pytest`. CI runs them on every pull
request and on every push to `main`. CI also builds the Docker image and imports the app
inside it, so a change that breaks the image fails too. It also runs
`helm lint --strict` on the chart.

## Layout

```
src/chapter_and_verse/   the package
  main.py                FastAPI app, startup (client pool, database, logging), the endpoints
  models.py              request and response shapes, with input limits
  llm.py                 the Claude call and its retries, behind a small Answerer type
  db.py                  the answers table and a database session per request
  config.py              settings read from the environment
  errors.py              exception types and the handlers that hide internals
  middleware.py          gives each request an ID for the logs and a header
tests/                   tests per module, a concurrency test, shared fixtures
migrations/              Alembic migrations, one file per schema change
Dockerfile               two-stage image that runs as a non-root user
compose.yaml             Postgres, then the migrations, then the API
charts/                  Helm chart: migrations as a Job, then the API and its Service
deploy/kind/             Postgres for a local kind cluster only
.github/workflows/       CI: the checks, the image build and the chart lint
```

## License

MIT. See [LICENSE](LICENSE).
