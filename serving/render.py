"""Print a KServe runtime for vLLM, and the InferenceService for an alias's version."""

import argparse
import json
import shlex
from typing import Any

from serving.registry import MODEL_NAME, connect, source_and_run

VLLM_VERSION = "v0.31.0"
PORT = 8080
# The prometheus chart's server, installed in the monitoring namespace.
PROMETHEUS = "http://prometheus-server.monitoring.svc.cluster.local"
MAX_REPLICAS = 2


def hub_model(source: str) -> tuple[str, str]:
    # Registry sources look like hf://owner/model:commit.
    repo, _, revision = source.removeprefix("hf://").partition(":")
    if not source.startswith("hf://") or not revision:
        raise ValueError(f"Expected hf://owner/model:commit, got {source}")
    return repo, revision


def max_num_seqs(vllm_args: str) -> int | None:
    # The batch limit a version was registered with, if it has one.
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--max-num-seqs", type=int)
    known, _ = parser.parse_known_args(shlex.split(vllm_args))
    batch: int | None = known.max_num_seqs
    return batch


def autoscaling(batch: int) -> dict[str, Any]:
    # KServe copies the scrape annotations to the Service too, so Prometheus reads each
    # pod twice. Only the pod's own scrape counts.
    selector = f'{{model_name="{MODEL_NAME}", job="kubernetes-pods"}}'
    # Every request inside vLLM, running or waiting. Waiting alone drops to zero as soon
    # as a second replica takes load, and the autoscaler would remove it again.
    query = (
        f"sum(vllm:num_requests_running{selector})"
        f" + sum(vllm:num_requests_waiting{selector})"
    )
    return {
        "minReplicas": 1,
        "maxReplicas": MAX_REPLICAS,
        "autoScaling": {
            "metrics": [
                {
                    "type": "External",
                    "external": {
                        "metric": {
                            "backend": "prometheus",
                            "serverAddress": PROMETHEUS,
                            "query": query,
                        },
                        # KEDA compares this with the average per replica. A new replica
                        # starts at three quarters of the batch, before requests queue.
                        "target": {"type": "Value", "value": str(batch * 3 // 4)},
                    },
                }
            ],
            # A GPU pod takes minutes to start, so a short dip in load does not remove it.
            "behavior": {"scaleDown": {"stabilizationWindowSeconds": 300}},
        },
    }


def serving_runtime(target: str) -> dict[str, Any]:
    image = "vllm/vllm-openai" if target == "eks" else "vllm/vllm-openai-cpu"
    health = {"httpGet": {"path": "/health", "port": PORT}}
    return {
        "apiVersion": "serving.kserve.io/v1alpha1",
        "kind": "ServingRuntime",
        "metadata": {"name": "vllm"},
        "spec": {
            "supportedModelFormats": [
                {"name": "huggingface", "version": "1", "autoSelect": True}
            ],
            "containers": [
                {
                    "name": "kserve-container",
                    "image": f"{image}:{VLLM_VERSION}",
                    # No args. KServe puts the InferenceService's after these,
                    # and vLLM needs the model first.
                    "command": ["vllm", "serve"],
                    "ports": [{"containerPort": PORT, "protocol": "TCP"}],
                    # Download and load take minutes. Readiness waits until this passes.
                    "startupProbe": {**health, "periodSeconds": 10, "failureThreshold": 60},
                    "readinessProbe": {**health, "periodSeconds": 5},
                    "volumeMounts": [
                        {"name": "shm", "mountPath": "/dev/shm"},
                        {"name": "hf-cache", "mountPath": "/root/.cache/huggingface"},
                    ],
                }
            ],
            "volumes": [
                # vLLM's worker processes share tensors through /dev/shm.
                {"name": "shm", "emptyDir": {"medium": "Memory", "sizeLimit": "2Gi"}},
                # Survives a container restart, so a slow download resumes.
                {"name": "hf-cache", "emptyDir": {}},
            ],
        },
    }


def inference_service(
    source: str, vllm_args: str, version: str, target: str
) -> dict[str, Any]:
    repo, revision = hub_model(source)
    model: dict[str, Any] = {
        # With this format and no storageUri, KServe adds no storage initializer and no
        # model puller. vLLM downloads the exact commit itself. The initializer would hold
        # most of the model in memory while downloading, too much for one GPU node.
        "modelFormat": {"name": "huggingface"},
        "runtime": "vllm",
        "args": [
            repo,
            f"--revision={revision}",
            f"--port={PORT}",
            f"--served-model-name={MODEL_NAME}",
            *shlex.split(vllm_args),
        ],
    }
    predictor: dict[str, Any] = {
        "model": model,
        # One GPU: the old pod must stop before the new one can get it.
        "deploymentStrategy": {"type": "Recreate"},
    }
    if target == "eks":
        model["resources"] = {
            "requests": {"cpu": "3", "memory": "12Gi"},
            "limits": {"cpu": "4", "memory": "14Gi", "nvidia.com/gpu": "1"},
        }
        predictor["tolerations"] = [
            {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}
        ]
    else:
        # kind has no GPU and shares about 8 GB with the rest of Docker:
        # vLLM's CPU build, no compile step, and a small KV cache.
        model["args"] += ["--enforce-eager", "--kv-cache-memory-bytes=536870912"]
        # --enforce-eager leaves vLLM's sampler compiled. Building it with g++ on the
        # first request took the pod past 5Gi.
        model["env"] = [{"name": "TORCH_COMPILE_DISABLE", "value": "1"}]
        # The request is what vLLM uses, so kind never starts a second pod that cannot fit.
        model["resources"] = {
            "requests": {"cpu": "2", "memory": "4Gi"},
            "limits": {"cpu": "4", "memory": "5Gi"},
        }
    # Prometheus reads vLLM's metrics from every predictor pod.
    annotations = {
        "prometheus.io/scrape": "true",
        "prometheus.io/port": str(PORT),
        "prometheus.io/path": "/metrics",
    }
    batch = max_num_seqs(vllm_args)
    if batch is None:
        # No batch limit, so no way to tell when a replica is full: one replica.
        annotations["serving.kserve.io/autoscalerClass"] = "none"
    else:
        annotations["serving.kserve.io/autoscalerClass"] = "keda"
        predictor |= autoscaling(batch)
    return {
        "apiVersion": "serving.kserve.io/v1beta1",
        "kind": "InferenceService",
        "metadata": {
            "name": MODEL_NAME,
            "labels": {"app.kubernetes.io/version": version},
            "annotations": annotations,
        },
        "spec": {"predictor": predictor},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", default="champion")
    parser.add_argument("--target", choices=["eks", "kind"], default="eks")
    args = parser.parse_args()

    client = connect()
    version = client.get_model_version_by_alias(MODEL_NAME, args.alias)
    source, run_id = source_and_run(version)
    vllm_args = client.get_run(run_id).data.params["vllm_args"]
    isvc = inference_service(source, vllm_args, str(version.version), args.target)
    runtime = serving_runtime(args.target)
    manifests = {"apiVersion": "v1", "kind": "List", "items": [runtime, isvc]}
    print(json.dumps(manifests, indent=2))


if __name__ == "__main__":
    main()
