from pathlib import Path

import mlflow
import pytest
from mlflow import MlflowClient
from mlflow.utils.mlflow_tags import MLFLOW_PARENT_RUN_ID

from serving import registry

COMMIT = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MlflowClient:
    # A real registry in a SQLite file, and a fixed commit instead of a call to the Hub.
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    monkeypatch.setattr(registry, "hub_revision", lambda repo: COMMIT)
    return registry.connect()


def version_run(client: MlflowClient, version: str) -> str:
    _, run_id = registry.source_and_run(
        client.get_model_version(registry.MODEL_NAME, version)
    )
    return run_id


def test_each_measurement_is_a_run_of_its_own_under_the_version(
    client: MlflowClient,
) -> None:
    version = registry.register(client, "Qwen/Qwen3-1.7B", registry.DEFAULT_VLLM_ARGS)

    first = registry.record(
        client, version, {"kserve_ready_seconds": 485.0}, {"measured_on": "g6.xlarge"}
    )
    second = registry.record(
        client, version, {"kserve_ready_seconds": 410.0}, {"measured_on": "g6.2xlarge"}
    )

    for run_id, seconds, instance in [
        (first, 485.0, "g6.xlarge"),
        (second, 410.0, "g6.2xlarge"),
    ]:
        run = client.get_run(run_id)
        assert run.data.tags[MLFLOW_PARENT_RUN_ID] == version_run(client, version)
        assert run.data.metrics == {"kserve_ready_seconds": seconds}
        assert run.data.tags["measured_on"] == instance


def test_the_version_run_keeps_only_its_serving_flags(client: MlflowClient) -> None:
    version = registry.register(client, "Qwen/Qwen3-1.7B", registry.DEFAULT_VLLM_ARGS)

    registry.record(
        client, version, {"kserve_ready_seconds": 485.0}, {"measured_on": "g6.xlarge"}
    )

    run = client.get_run(version_run(client, version))
    assert run.data.params["vllm_args"] == registry.DEFAULT_VLLM_ARGS
    assert run.data.metrics == {}
    assert "measured_on" not in run.data.tags


def test_a_measurement_goes_to_the_experiment_of_its_version(
    client: MlflowClient,
) -> None:
    version = registry.register(client, "Qwen/Qwen3-1.7B", registry.DEFAULT_VLLM_ARGS)
    mlflow.set_experiment("another")

    run_id = registry.record(client, version, {"kserve_ready_seconds": 485.0}, {})

    parent = client.get_run(version_run(client, version))
    assert client.get_run(run_id).info.experiment_id == parent.info.experiment_id
