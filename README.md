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

Open models now run on a GPU in AWS, served by vLLM behind KServe on an EKS cluster that
exists only while it is in use. An MLflow model registry records which model is served,
at which exact commit, with which settings. `/ask` does not use them yet. It still calls
Claude.

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

### The model registry

Every model this project serves is a version of one registered model, `answerer`, in
[MLflow](https://mlflow.org/docs/latest/ml/model-registry/). A version holds:

- the source: a Hugging Face repository at an exact commit, such as
  `hf://Qwen/Qwen3-1.7B:70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`. A repository name can
  point at new weights tomorrow. A commit cannot.
- the vLLM flags to serve it with, such as the context length
- the numbers measured for it, such as how long it took to start and how much KV cache
  fits on the GPU

Serving reads an alias, never a version number. `champion` is the version for the GPU
cluster. `local` is a version small enough for kind. Moving an alias changes what is
served without changing any manifest.

Start MLflow. It listens on port 5050 of your own machine, because macOS uses 5000 for
AirPlay. The registry is kept in a Docker volume, in a compose project of its own, so
`docker compose down -v` at the root never deletes it:

```sh
docker compose -f deploy/mlflow/compose.yaml up -d
```

The UI is at http://127.0.0.1:5050. The commands below use this server unless
`MLFLOW_TRACKING_URI` points at another one.

`register` looks up the commit the repository points to now, adds a version and prints
its number. The default flags are `--max-model-len=8192 --reasoning-parser=qwen3`.
The examples in this README use six versions, registered in this order:

```sh
uv run python -m serving.registry register Qwen/Qwen3-0.6B \
  --vllm-args="--max-model-len=2048 --reasoning-parser=qwen3"
uv run python -m serving.registry register Qwen/Qwen3-1.7B
uv run python -m serving.registry register Qwen/Qwen3-8B
uv run python -m serving.registry register Qwen/Qwen3-8B-FP8
uv run python -m serving.registry register Qwen/Qwen3-0.6B \
  --vllm-args="--max-model-len=2048 --reasoning-parser=qwen3 --max-num-seqs=4"
uv run python -m serving.registry register Qwen/Qwen3-1.7B \
  --vllm-args="--max-model-len=8192 --reasoning-parser=qwen3 --max-num-seqs=16"
```

Version 1 has a short context, so vLLM's CPU build fits in the memory kind can give it.
Versions 5 and 6 are versions 1 and 2 with a batch limit, `--max-num-seqs`. A version with
a batch limit is served with autoscaling, see below.

`alias` points an alias at a version:

```sh
uv run python -m serving.registry alias local 5
uv run python -m serving.registry alias champion 6
```

`record` saves what you measured. The numbers go on the MLflow run behind the version,
next to its flags:

```sh
uv run python -m serving.registry record 2 --metric kserve_ready_seconds 485 \
  --tag measured_on g6.xlarge
```

### On AWS, with a GPU

This serves an open model on an NVIDIA L4 GPU with [vLLM](https://docs.vllm.ai/) behind
[KServe](https://kserve.github.io/website/), through an OpenAI compatible API. The
service does not use it yet: `/ask` still calls Claude.

Terraform in `infra/aws/` creates an EKS cluster in eu-west-2 (London) with one ARM
`t4g.medium` node for the system pods. GPU nodes come from Karpenter: it starts an NVIDIA
L4 node when a model needs one, and removes the node once it is empty. Only pods that
tolerate the GPU nodes' taint run there. The cluster is built to be destroyed after each
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
| GPU node, `g6.xlarge` on demand | $1.02 |
| System node, `t4g.medium` | $0.04 |

Karpenter starts a spot node when London has capacity, and an on-demand node when it has
none. With one GPU node the cluster costs $0.49 to $0.55 an hour on spot and $1.16 on
demand, plus a few cents for disks and public IP addresses.

**Run `terraform destroy` at the end of every session.** Left running, the cluster costs
about $3.40 a day with no GPU node, and $12 to $28 a day with one.

#### What you need

- An AWS account where you can create IAM roles, a VPC and an EKS cluster.
- Quota for G instances in eu-west-2. New accounts start at 0. In Service Quotas,
  [request](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html)
  8 vCPUs for "All G and VT Spot Instance Requests" and 8 for "Running On-Demand G and VT
  instances": room for two `g6.xlarge` nodes either way. Approval can take a day or two.
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
terraform -chdir=infra/aws apply
```

The apply takes about 12 minutes. Keep `TF_VAR_admin_cidr` set in this terminal:
`destroy` needs it too. If your IP address changes, kubectl times out. Export
`TF_VAR_admin_cidr` again and run the same apply.

Point kubectl at the cluster, then install the NVIDIA device plugin. The node's AMI brings
the NVIDIA driver, and the plugin makes the GPU visible to Kubernetes as `nvidia.com/gpu`:

```sh
eval "$(terraform -chdir=infra/aws output -raw kubeconfig_command)"
helm install nvdp nvidia-device-plugin --repo https://nvidia.github.io/k8s-device-plugin \
  --version 0.20.1 --namespace nvidia --create-namespace
```

Install Karpenter on the system node, and give it the NodePool. One replica, because the
chart's default is two on different nodes, and the cluster has one system node.

```sh
helm install karpenter oci://public.ecr.aws/karpenter/karpenter --version 1.15.1 \
  --namespace kube-system \
  --set settings.clusterName=chapter-and-verse \
  --set settings.interruptionQueue="$(terraform -chdir=infra/aws output -raw karpenter_queue)" \
  --set replicas=1 \
  --wait
kubectl apply -f deploy/aws/karpenter.yaml
```

Check that a pod can use the GPU. This Job runs `nvidia-smi` once. No GPU node runs yet.
Karpenter starts one for this Job, and removes it a minute after the Job is deleted.

```sh
kubectl apply -f deploy/aws/gpu-check.yaml
kubectl wait --for=condition=complete job/gpu-check --timeout=10m
kubectl logs job/gpu-check
kubectl delete job gpu-check
```

The log shows an NVIDIA L4 with 23,034 MiB of memory.

#### Serve a model

Install Prometheus and KEDA first. KEDA scales the model on vLLM's metrics, which
Prometheus collects. KServe looks for KEDA only when it starts, so KEDA goes in before
KServe.

```sh
helm install prometheus prometheus --repo https://prometheus-community.github.io/helm-charts \
  --version 29.37.0 --namespace monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set kube-state-metrics.enabled=false \
  --set prometheus-node-exporter.enabled=false \
  --set prometheus-pushgateway.enabled=false \
  --set server.persistentVolume.enabled=false \
  --set server.global.scrape_interval=15s \
  --wait
helm install keda keda --repo https://kedacore.github.io/charts --version 2.21.0 \
  --namespace keda --create-namespace --wait
```

KServe runs the model, and the registry says which one. Install cert-manager before
KServe, because KServe's webhooks need certificates. Then install KServe in Standard
mode: a plain Deployment and Service per model, with no Knative and no Istio. You reach
the model with `port-forward`, so KServe creates no Ingress.

```sh
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager --version v1.21.3 \
  --namespace cert-manager --create-namespace --set crds.enabled=true --wait
helm install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd --version v0.21.0 \
  --namespace kserve --create-namespace --wait
helm install kserve oci://ghcr.io/kserve/charts/kserve-resources --version v0.21.0 \
  --namespace kserve \
  --set kserve.controller.deploymentMode=Standard \
  --set kserve.controller.gateway.disableIngressCreation=true \
  --set kserve.controller.gateway.disableIstioVirtualHost=true \
  --wait
```

Both run on the system node. The GPU node's taint keeps them off the GPU.

With MLflow running, render the manifests for the `champion` alias and apply them:

```sh
kubectl create namespace models
uv run python -m serving.render | kubectl apply -n models -f -
kubectl wait --for=condition=Ready inferenceservice/answerer -n models --timeout=20m
```

`serving/render.py` prints two manifests. The ServingRuntime says how to run vLLM: the
image, the probes and the volumes. The InferenceService says what to run: the commit and
the flags of the version, and one GPU. Its `app.kubernetes.io/version` label is the
version number, so a running pod leads back to its exact weights and its measured
numbers. `--alias` and `--target` choose another alias or cluster. The defaults are
`champion` and `eks`.

A version registered with `--max-num-seqs` runs one or two replicas. KEDA counts the
requests inside vLLM, running or waiting, and adds a replica when they average more than
three quarters of the batch: 12 for a batch of 16. Waiting requests alone would drop to
zero as soon as the second replica took load, and it would be removed again. The second
replica stops 5 minutes after the load drops. Prometheus scrapes each pod twice, through
the pod and through the Service, because KServe copies the scrape annotations to both, so
the query counts the pod's own scrape only.

vLLM downloads the weights itself, not KServe's storage initializer. The initializer held
most of the model in memory while it downloaded, 2.6 GiB for Qwen3-1.7B. Its memory grows
with the model, and the GPU node has 16 GiB for everything.

With version 2, Qwen3-1.7B, the first start takes about 8 minutes, more than half of it
the image pull. To serve another version, move the alias and apply again:

```sh
uv run python -m serving.registry alias champion 4
uv run python -m serving.render | kubectl apply -n models -f -
```

After a change, wait with `kubectl rollout status deployment/answerer-predictor -n models`.
`kubectl wait` on the InferenceService can miss it, because KServe copies
`observedGeneration` from the Deployment
([kserve/kserve#6081](https://github.com/kserve/kserve/issues/6081)).

There is one GPU, so the old pod stops before the new one starts. Nothing answers until
the new pod is Ready.

To reach the model, keep this running in its own terminal:

```sh
kubectl port-forward -n models svc/answerer-predictor 8080:80
```

Then send a chat request. `model` is always `answerer`, whatever version is behind it:

```sh
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "answerer",
       "messages": [{"role": "user", "content": "In one sentence, what does the Equality Act 2010 do?"}],
       "max_tokens": 300,
       "chat_template_kwargs": {"enable_thinking": false}}'
```

The answer is in `choices[0].message.content`. `enable_thinking: false` skips Qwen3's
thinking step, so the answer comes back sooner. vLLM's Prometheus metrics are at
http://127.0.0.1:8080/metrics.

The same works on kind, without a GPU. Install Prometheus, KEDA, cert-manager and KServe
with the same commands, then render the `local` alias for kind:

```sh
kubectl create namespace models
uv run python -m serving.render --alias local --target kind | kubectl apply -n models -f -
```

This uses vLLM's CPU build, with no compile step and a small KV cache, so it fits in
about 5 GiB. An answer takes about 15 seconds. kind has room for one replica, so a second
one waits as Pending.

#### Destroy it

```sh
kubectl delete inferenceservice --all -n models
kubectl delete nodepool gpu
kubectl get nodeclaims
```

Run the last line until it says `No resources found`. Then:

```sh
kubectl delete ec2nodeclass gpu
terraform -chdir=infra/aws destroy
kubectl config delete-context eks-chapter-and-verse
```

Karpenter's nodes are not in Terraform's state. Deleting the NodePool makes Karpenter stop
them, and deleting the EC2NodeClass makes it delete the instance profile it created. Skip
these and a GPU node keeps running, and the destroy cannot delete the node role or the
VPC.

The destroy takes about 11 minutes. Then check that the region has no cluster, instance,
disk or instance profile left. In an account used only for this, each command prints an
empty list:

```sh
aws eks list-clusters --region eu-west-2 --query clusters
aws ec2 describe-instances --region eu-west-2 \
  --filters Name=instance-state-name,Values=pending,running,stopping \
  --query 'Reservations[].Instances[].InstanceId'
aws ec2 describe-volumes --region eu-west-2 --query 'Volumes[].VolumeId'
aws iam list-instance-profiles --path-prefix /karpenter/ --query 'InstanceProfiles[].InstanceProfileName'
```

#### What one L4 holds

Measured on 31 October 2026 with vLLM 0.31.0 on an on-demand `g6.xlarge`, with the
default flags `--max-model-len=8192 --reasoning-parser=qwen3`. vLLM used 92% of the GPU's
memory, its default.

| Version | Weights on the GPU | KV cache | Requests of 8,192 tokens at once |
| --- | --- | --- | --- |
| 3, Qwen3-8B in bf16 | 15.27 GiB | 22,976 tokens | 2.80 |
| 4, Qwen3-8B-FP8 | 8.9 GiB | 68,768 tokens | 8.39 |

FP8 stores each weight in one byte instead of two, so the weights take 6.4 GiB less. The
KV cache stays in bf16, and the freed memory holds three times as many tokens. The last
column is how many requests of the full context fit in the KV cache at the same time.
Shorter requests fit more. How FP8 changes the answers is not measured yet.

The same numbers are recorded on versions 3 and 4 in the registry.

#### How long a start takes

Measured on 24 October 2026 with Qwen3-1.7B, on a spot `g6.2xlarge`, with a plain vLLM
Deployment before KServe:

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

Through KServe, measured on 31 October 2026 with the same model on an on-demand
`g6.xlarge`, the InferenceService was Ready 485 seconds after `kubectl apply`. The image
pull took 269 of them. The `g6.xlarge` has half the vCPUs of the `g6.2xlarge`, so the
difference is not only what KServe adds.

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
serving/                 registry commands, KServe manifests from an alias, a load generator
deploy/kind/             Postgres for a local kind cluster only
deploy/mlflow/           the MLflow server for the model registry, on your own machine
deploy/aws/              Karpenter's GPU node pool, and the GPU check Job, for EKS
infra/aws/               Terraform for a temporary EKS cluster, and the IAM and queue for Karpenter
.github/workflows/       CI: the checks, the image build, the chart lint, the Terraform checks
```

## License

MIT. See [LICENSE](LICENSE).
