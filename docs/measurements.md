# Measurements

What one NVIDIA L4 GPU holds and how long a model takes to start, measured on AWS.

## What one L4 holds

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

The same numbers are recorded on versions 3 and 4 in the [registry](model-registry.md).

## How long a start takes

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
