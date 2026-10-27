"""Register open models as versions of one MLflow model, and choose which to serve."""

import argparse
import os

import httpx
import mlflow
from mlflow import MlflowClient
from mlflow.entities.model_registry import ModelVersion
from mlflow.exceptions import MlflowException

MODEL_NAME = "answerer"
DEFAULT_VLLM_ARGS = "--max-model-len=8192 --reasoning-parser=qwen3"


def connect() -> MlflowClient:
    # The server from deploy/mlflow, unless MLFLOW_TRACKING_URI points somewhere else.
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5050"))
    mlflow.set_experiment(MODEL_NAME)
    return MlflowClient()


def hub_revision(repo: str) -> str:
    # The commit the repo points to now, so a version always means the same weights.
    response = httpx.get(f"https://huggingface.co/api/models/{repo}", timeout=30)
    response.raise_for_status()
    return str(response.json()["sha"])


def source_and_run(version: ModelVersion) -> tuple[str, str]:
    # Every version register() adds has both. Without them it cannot be served.
    if version.source is None or version.run_id is None:
        raise SystemExit(f"Version {version.version} was not added with serving.registry.")
    return version.source, version.run_id


def register(client: MlflowClient, repo: str, vllm_args: str) -> str:
    revision = hub_revision(repo)
    with mlflow.start_run(run_name=repo.split("/")[-1]) as run:
        mlflow.log_params({"hf_repo": repo, "hf_revision": revision, "vllm_args": vllm_args})
    try:
        client.create_registered_model(MODEL_NAME)
    except MlflowException as error:
        if error.error_code != "RESOURCE_ALREADY_EXISTS":
            raise
    # The source names the exact weights. The run keeps the serving flags and the numbers.
    source = f"hf://{repo}:{revision}"
    version = client.create_model_version(MODEL_NAME, source, run_id=run.info.run_id)
    return str(version.version)


def record(
    client: MlflowClient, version: str, metrics: dict[str, float], tags: dict[str, str]
) -> None:
    # Measured numbers go on the run behind the version, next to its serving flags.
    _, run_id = source_and_run(client.get_model_version(MODEL_NAME, version))
    for name, value in metrics.items():
        client.log_metric(run_id, name, value)
    for name, text in tags.items():
        client.set_tag(run_id, name, text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("register", help="add a Hugging Face model as a new version")
    add.add_argument("repo", help="for example Qwen/Qwen3-1.7B")
    add.add_argument("--vllm-args", default=DEFAULT_VLLM_ARGS)

    alias = commands.add_parser("alias", help="point an alias at a version")
    alias.add_argument("alias")
    alias.add_argument("version")

    measured = commands.add_parser("record", help="log measured numbers for a version")
    measured.add_argument("version")
    measured.add_argument(
        "--metric", nargs=2, action="append", required=True, metavar=("NAME", "VALUE")
    )
    measured.add_argument(
        "--tag", nargs=2, action="append", default=[], metavar=("NAME", "VALUE")
    )

    args = parser.parse_args()
    client = connect()
    if args.command == "register":
        print(register(client, args.repo, args.vllm_args))
    elif args.command == "alias":
        client.set_registered_model_alias(MODEL_NAME, args.alias, args.version)
    else:
        metrics = {name: float(value) for name, value in args.metric}
        record(client, args.version, metrics, dict(args.tag))


if __name__ == "__main__":
    main()
