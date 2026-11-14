import json
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


def benchmark_line(clients: int, requests: int, ttft: float) -> str:
    # One line in the shape serving.benchmark prints.
    results = {
        "requests": requests,
        "failed": 0,
        "ttft_p50_ms": ttft,
        "ttft_p95_ms": ttft + 50,
        "tpot_p50_ms": 34.96,
        "tpot_p95_ms": 35.19,
        "output_tokens_per_second": 26.5,
    }
    return json.dumps({"settings": {"clients": clients, "seconds": 120}, "results": results})


def test_each_benchmark_line_is_a_run_with_its_settings_and_results(
    client: MlflowClient, tmp_path: Path
) -> None:
    version = registry.register(client, "Qwen/Qwen3-1.7B", registry.DEFAULT_VLLM_ARGS)
    path = tmp_path / "benchmark.jsonl"
    path.write_text(f"{benchmark_line(1, 11, 738.6)}\n{benchmark_line(8, 40, 2100)}\n")

    run_ids = registry.record_benchmark(
        client, version, path, {"measured_on": "g6.xlarge"}
    )

    runs = [client.get_run(run_id) for run_id in run_ids]
    assert [run.data.params["clients"] for run in runs] == ["1", "8"]
    assert [run.data.metrics["ttft_p50_ms"] for run in runs] == [738.6, 2100]
    for run in runs:
        assert run.data.params["seconds"] == "120"
        assert run.data.tags["kind"] == "benchmark"
        assert run.data.tags["measured_on"] == "g6.xlarge"
        assert run.data.tags[MLFLOW_PARENT_RUN_ID] == version_run(client, version)


def test_a_benchmark_file_with_a_bad_line_adds_no_runs(
    client: MlflowClient, tmp_path: Path
) -> None:
    version = registry.register(client, "Qwen/Qwen3-1.7B", registry.DEFAULT_VLLM_ARGS)
    path = tmp_path / "benchmark.jsonl"
    # What kubectl logs saves when a sweep stops early.
    path.write_text(f"{benchmark_line(1, 11, 738.6)}\nNo request finished\n")

    with pytest.raises(json.JSONDecodeError):
        registry.record_benchmark(client, version, path, {})

    experiment = client.get_run(version_run(client, version)).info.experiment_id
    assert client.search_runs(
        [experiment], f"tags.mlflow.parentRunId = '{version_run(client, version)}'"
    ) == []


def test_the_table_shows_benchmark_runs_fewest_clients_first(
    client: MlflowClient, tmp_path: Path
) -> None:
    version = registry.register(client, "Qwen/Qwen3-1.7B", registry.DEFAULT_VLLM_ARGS)
    # A plain measurement is not a benchmark run, so it stays out of the table.
    registry.record(client, version, {"kserve_ready_seconds": 485.0}, {})
    path = tmp_path / "benchmark.jsonl"
    path.write_text(f"{benchmark_line(8, 40, 2100)}\n{benchmark_line(1, 11, 738.6)}\n")
    registry.record_benchmark(client, version, path, {})

    table = registry.benchmark_table(client, version).splitlines()

    assert table == [
        (
            "| Clients | Requests | TTFT p50 (ms) | TTFT p95 (ms) | TPOT p50 (ms) "
            "| TPOT p95 (ms) | Tokens/s | Failed |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        "| 1 | 11 | 738.6 | 788.6 | 34.96 | 35.19 | 26.5 | 0 |",
        "| 8 | 40 | 2100 | 2150 | 34.96 | 35.19 | 26.5 | 0 |",
    ]


def test_a_table_with_no_benchmark_runs_says_so(client: MlflowClient) -> None:
    version = registry.register(client, "Qwen/Qwen3-1.7B", registry.DEFAULT_VLLM_ARGS)

    with pytest.raises(SystemExit, match="no benchmark runs"):
        registry.benchmark_table(client, version)
