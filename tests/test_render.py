import pytest

from serving.render import VLLM_VERSION, hub_model, inference_service, serving_runtime

SOURCE = "hf://Qwen/Qwen3-1.7B:70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
VLLM_ARGS = "--max-model-len=8192 --reasoning-parser=qwen3"


def parse_quantity(value: str) -> float:
    # Enough for the values used here: whole CPUs and Gi.
    return float(value.removesuffix("Gi"))


def test_reads_the_repo_and_commit_from_the_source() -> None:
    assert hub_model(SOURCE) == (
        "Qwen/Qwen3-1.7B",
        "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
    )


@pytest.mark.parametrize("source", ["s3://bucket/qwen3", "hf://Qwen/Qwen3-1.7B"])
def test_refuses_a_source_without_a_pinned_commit(source: str) -> None:
    with pytest.raises(ValueError):
        hub_model(source)


def test_serves_the_registered_commit_with_its_flags() -> None:
    model = inference_service(SOURCE, VLLM_ARGS, "3", "eks")["spec"]["predictor"]["model"]

    # vllm serve needs the model first. The runtime adds no args of its own.
    assert model["args"] == [
        "Qwen/Qwen3-1.7B",
        "--revision=70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        "--port=8080",
        "--served-model-name=answerer",
        "--max-model-len=8192",
        "--reasoning-parser=qwen3",
    ]
    assert "args" not in serving_runtime("eks")["spec"]["containers"][0]


def test_huggingface_format_keeps_kserve_from_adding_containers() -> None:
    # Any other format without a storageUri makes KServe add a model puller.
    model = inference_service(SOURCE, VLLM_ARGS, "3", "eks")["spec"]["predictor"]["model"]

    assert model["modelFormat"] == {"name": "huggingface"}
    assert "storageUri" not in model


def test_eks_asks_for_the_gpu_and_tolerates_its_taint() -> None:
    predictor = inference_service(SOURCE, VLLM_ARGS, "3", "eks")["spec"]["predictor"]

    assert predictor["model"]["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert predictor["tolerations"][0]["key"] == "nvidia.com/gpu"


def test_kind_runs_on_cpu_with_a_small_kv_cache() -> None:
    predictor = inference_service(SOURCE, VLLM_ARGS, "3", "kind")["spec"]["predictor"]

    assert "nvidia.com/gpu" not in predictor["model"]["resources"]["limits"]
    assert "tolerations" not in predictor
    assert predictor["model"]["args"][-2:] == [
        "--enforce-eager",
        "--kv-cache-memory-bytes=536870912",
    ]


def test_kind_never_compiles_on_the_first_request() -> None:
    # vLLM's sampler calls torch.compile, and building it took the pod past 5Gi.
    model = inference_service(SOURCE, VLLM_ARGS, "3", "kind")["spec"]["predictor"]["model"]

    assert {"name": "TORCH_COMPILE_DISABLE", "value": "1"} in model["env"]


@pytest.mark.parametrize("target", ["eks", "kind"])
def test_sets_both_limits_above_the_requests(target: str) -> None:
    model = inference_service(SOURCE, VLLM_ARGS, "3", target)["spec"]["predictor"]["model"]
    requests, limits = model["resources"]["requests"], model["resources"]["limits"]

    for name in ("cpu", "memory"):
        assert parse_quantity(requests[name]) <= parse_quantity(limits[name])


@pytest.mark.parametrize("target", ["eks", "kind"])
def test_stops_the_old_pod_before_starting_the_new_one(target: str) -> None:
    # A rolling update would wait for a GPU the old pod never gives back.
    predictor = inference_service(SOURCE, VLLM_ARGS, "3", target)["spec"]["predictor"]

    assert predictor["deploymentStrategy"] == {"type": "Recreate"}


def test_labels_the_registry_version() -> None:
    isvc = inference_service(SOURCE, VLLM_ARGS, "3", "eks")

    assert isvc["metadata"]["labels"]["app.kubernetes.io/version"] == "3"


@pytest.mark.parametrize(
    ("target", "image"), [("eks", "vllm/vllm-openai"), ("kind", "vllm/vllm-openai-cpu")]
)
def test_runtime_pins_the_vllm_build_for_each_cluster(target: str, image: str) -> None:
    container = serving_runtime(target)["spec"]["containers"][0]

    assert container["image"] == f"{image}:{VLLM_VERSION}"
