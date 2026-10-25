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

Open models now run on a GPU in AWS, served by vLLM on an EKS cluster that exists only
while it is in use. `/ask` does not use them yet. It still calls Claude.

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

### On AWS, with a GPU

This serves an open model on an NVIDIA L4 GPU with [vLLM](https://docs.vllm.ai/), through
an OpenAI compatible API. The service does not use it yet: `/ask` still calls Claude.

Terraform in `infra/aws/` creates an EKS cluster in eu-west-2 (London) with two nodes: an
ARM `t4g.medium` for the system pods, and one spot NVIDIA L4 for models. Only pods that
tolerate the GPU node's taint run there. The cluster is built to be destroyed after each
session, and nothing in it keeps data.

There is no NAT gateway, because it charges by the hour and for every GB of image and
weights. The nodes are in public subnets instead, and their security group blocks inbound
traffic from the internet. The Kubernetes API accepts one IP address only.

#### What it costs

London prices in US dollars, checked in October 2026. Spot prices change.

| Part | Per hour |
| --- | --- |
| EKS control plane | $0.10 |
| GPU node, `g6.xlarge` on spot | $0.35 to $0.41 |
| GPU node, `g6.2xlarge` on spot | about $0.19 |
| System node, `t4g.medium` | $0.04 |

Both GPU sizes have the same L4, and the node group takes whichever has spot capacity.
With the GPU node running, the cluster costs $0.33 to $0.55 an hour, plus a few cents for
disks and public IP addresses.

**Run `terraform destroy` at the end of every session.** Left running, the cluster costs
$8 to $14 a day.

#### What you need

- An AWS account where you can create IAM roles, a VPC and an EKS cluster.
- Quota for spot G instances in eu-west-2. New accounts start at 0. In Service Quotas,
  [request](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html)
  8 vCPUs for "All G and VT Spot Instance Requests", so either size can launch. Approval
  can take a day or two.
- The [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html),
  signed in to that account. `aws sts get-caller-identity` shows which account it uses.
- [Terraform 1.16](https://developer.hashicorp.com/terraform/install), and kubectl and
  Helm 4 as for kind.

#### Create it

Run every command from the repository root. `admin_cidr` is your current public IP
address, the only one the Kubernetes API will accept:

```sh
export TF_VAR_admin_cidr="$(curl -s https://checkip.amazonaws.com)/32"
terraform -chdir=infra/aws init
terraform -chdir=infra/aws apply -var gpu_nodes=1
```

The apply takes about 12 minutes. Set `gpu_nodes` when you create the cluster, because the
node group ignores later changes to it. Keep `TF_VAR_admin_cidr` set in this terminal:
`destroy` needs it too. If your IP address changes, kubectl times out. Export
`TF_VAR_admin_cidr` again and run the same apply.

When London has no spot L4 capacity, the GPU node group fails after about 30 minutes. The
control plane and the system node still cost money, so run `terraform destroy` and try
again later.

Point kubectl at the cluster, then install the NVIDIA device plugin. The node's AMI brings
the NVIDIA driver, and the plugin makes the GPU visible to Kubernetes as `nvidia.com/gpu`:

```sh
eval "$(terraform -chdir=infra/aws output -raw kubeconfig_command)"
helm install nvdp nvidia-device-plugin --repo https://nvidia.github.io/k8s-device-plugin \
  --version 0.20.1 --namespace nvidia --create-namespace
```

Check that a pod can use the GPU. This Job runs `nvidia-smi` once:

```sh
kubectl apply -f deploy/aws/gpu-check.yaml
kubectl wait --for=condition=complete job/gpu-check --timeout=180s
kubectl logs job/gpu-check
```

The log shows an NVIDIA L4 with 23,034 MiB of memory.

#### Serve a model

```sh
kubectl apply -f deploy/aws/vllm.yaml
kubectl rollout status deployment/vllm --timeout=15m
```

It serves Qwen3-1.7B. The first start takes about 6 minutes, most of it the image pull. To
serve another model, change one value, for example
`kubectl set env deployment/vllm MODEL=Qwen/Qwen3-8B-FP8`.

To reach it, keep this running in its own terminal:

```sh
kubectl port-forward svc/vllm 8000:8000
```

Then send a chat request. `model` must be the model being served, which
`curl http://127.0.0.1:8000/v1/models` shows:

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen3-1.7B",
       "messages": [{"role": "user", "content": "In one sentence, what does the Equality Act 2010 do?"}],
       "max_tokens": 300,
       "chat_template_kwargs": {"enable_thinking": false}}'
```

The answer is in `choices[0].message.content`. `enable_thinking: false` skips Qwen3's
thinking step, so the answer comes back sooner.

#### Destroy it

```sh
terraform -chdir=infra/aws destroy
kubectl config delete-context eks-chapter-and-verse
```

The destroy takes about 11 minutes. Then check that the region has no cluster, instance or
disk left. In an account used only for this, each command prints an empty list:

```sh
aws eks list-clusters --region eu-west-2 --query clusters
aws ec2 describe-instances --region eu-west-2 \
  --filters Name=instance-state-name,Values=pending,running,stopping \
  --query 'Reservations[].Instances[].InstanceId'
aws ec2 describe-volumes --region eu-west-2 --query 'Volumes[].VolumeId'
```

#### How long a start takes

Measured on 24 October 2026 with Qwen3-1.7B, on a spot `g6.2xlarge`:

| Stage | Seconds |
| --- | --- |
| `terraform apply` until the GPU node is Ready | 632 |
| Image pull, 9 GB | 230 |
| Weights download | 19 |
| Weights load onto the GPU | 13 |
| Engine start: memory profile, KV cache, warm up | 50 |

Most of the apply is the control plane: the GPU node was Ready 105 seconds after its node
group was created. `torch.compile` takes 34 of the 50 seconds of engine start. From
`kubectl apply` to a Ready pod took 6 minutes 10 seconds.

Nothing is cached between pods, so each new pod downloads the weights and compiles again.
On the same node, it does not pull the image again.

### Ask it something

Compose, uv and kind all serve the API on port 8000, reachable only from your own machine.

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
`helm lint --strict` on the chart, and `terraform fmt -check` and `terraform validate` on
the Terraform, with no AWS credentials.

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
deploy/aws/              the GPU check Job and the vLLM Deployment, for EKS
infra/aws/               Terraform for a temporary EKS cluster with a spot GPU node
.github/workflows/       CI: the checks, the image build, the chart lint, the Terraform checks
```

## License

MIT. See [LICENSE](LICENSE).
