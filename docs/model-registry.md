# Registering models in MLflow

How each model is recorded with its exact commit and flags, and how an alias chooses which
one is served.

## The model registry

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
The examples in this guide and the [GPU guide](gpu-on-aws.md) use six versions, registered
in this order:

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
a batch limit is served with autoscaling, see [Serve a model](gpu-on-aws.md#serve-a-model).

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
