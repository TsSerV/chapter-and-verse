# Measurements

What one NVIDIA L4 GPU holds, how long a model takes to start, how it scales and how fast
it answers, measured on AWS.

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

## How it scales

Measured on 7 November 2026 with vLLM 0.31.0 and version 6 (Qwen3-1.7B, a batch of 16), on
`g6.xlarge` nodes. Karpenter asked for spot first each time. EC2 could not fulfil it, so
all three GPU nodes were on demand, about 10 seconds later.

Each GPU node was Ready 53 to 72 seconds after Karpenter created its NodeClaim. With no GPU
node at the start, the model was Ready 574 seconds after `kubectl apply`, 89 seconds more
than [on a node that was already running](#how-long-a-start-takes). The 574 seconds is
recorded on version 6 in the [registry](model-registry.md).

Then `serving/load.py` ran inside the cluster for 20 minutes with 32 clients, through the
Service. The times count from the moment the load pod was Ready:

| Stage | Seconds after the load started |
| --- | --- |
| KEDA scales to two replicas | 27 |
| The second GPU node is Ready | 91 |
| The second pod is Ready | 512 |
| KEDA scales back to one replica | 1,515 |
| Karpenter terminates the empty node | 1,601 |

The times come from Kubernetes timestamps, and the last one from the EC2 call in
CloudTrail.

Most of the 512 seconds is the pod starting on a node that has no image yet: 421 seconds
from node Ready to pod Ready. In [the earlier start through KServe](#how-long-a-start-takes),
the image pull was more than half of the time.

The second replica stays for 5 minutes after the load drops. The empty node was terminated
86 seconds after the change to one replica, because the NodePool waits one minute after a
node's last pod goes.

## How fast it answers

Measured on 14 November 2026 with vLLM 0.31.0 on one on-demand `g6.xlarge`. Each version
ran as one replica, so each table is one L4. `serving/benchmark.py` ran inside the cluster
and went through the Service. Each row is one measurement: that many clients, each asking
again as soon as its last answer ends, for 2 minutes after a 20 second warm up. Each prompt
is about 1,900 tokens of random words, different every time, so vLLM's prefix cache cannot
help. Each answer is exactly 256 tokens. Latency counts the requests that ran wholly inside
the 2 minutes. Tokens per second counts every output token that arrived inside them. Each
row is its own run in the [registry](model-registry.md).

TTFT is the time to the first token. TPOT is the time per output token after the first.
Tokens/s is output tokens per second across all clients.

### Version 4, Qwen3-8B-FP8

| Clients | Requests | TTFT p50 (ms) | TTFT p95 (ms) | TPOT p50 (ms) | TPOT p95 (ms) | Tokens/s | Failed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 11 | 738.6 | 760.3 | 34.96 | 35.19 | 26.5 | 0 |
| 2 | 20 | 1164.8 | 1568.1 | 37.81 | 39.23 | 47.5 | 0 |
| 4 | 32 | 1927.2 | 2312.3 | 43.16 | 47.45 | 80 | 0 |
| 8 | 49 | 2315.3 | 2337.9 | 58.07 | 63.82 | 119.4 | 0 |
| 8 | 49 | 2307.1 | 2337.6 | 58.03 | 63.69 | 119.4 | 0 |
| 16 | 62 | 2370.6 | 2459.6 | 93.32 | 98.32 | 151.4 | 0 |

### Version 3, Qwen3-8B in bf16

| Clients | Requests | TTFT p50 (ms) | TTFT p95 (ms) | TPOT p50 (ms) | TPOT p95 (ms) | Tokens/s | Failed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 6 | 574.8 | 586 | 61.16 | 61.31 | 15.8 | 0 |
| 2 | 10 | 906.1 | 1194.7 | 66.33 | 67.58 | 28.9 | 0 |
| 4 | 21 | 1642.9 | 1794.3 | 69.9 | 74.32 | 51.8 | 0 |
| 8 | 40 | 1712.2 | 1827.8 | 83.13 | 86.72 | 87.7 | 0 |
| 8 | 39 | 1759.4 | 1848.2 | 83.1 | 87.15 | 87.9 | 0 |
| 16 | 37 | 5089.6 | 23720.5 | 92.98 | 115.69 | 106.9 | 0 |

### Version 2, Qwen3-1.7B

| Clients | Requests | TTFT p50 (ms) | TTFT p95 (ms) | TPOT p50 (ms) | TPOT p95 (ms) | Tokens/s | Failed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 28 | 138.3 | 140.5 | 15.72 | 15.75 | 61.7 | 0 |
| 2 | 50 | 205.8 | 269.7 | 17.29 | 17.56 | 111 | 0 |
| 4 | 88 | 344.4 | 409.1 | 19.72 | 20.42 | 190.3 | 0 |
| 8 | 136 | 400 | 415.8 | 24.99 | 25.85 | 301.6 | 0 |
| 8 | 136 | 401.9 | 420.2 | 25.03 | 25.87 | 301.1 | 0 |
| 16 | 175 | 441.8 | 459.5 | 37.87 | 38.57 | 404.8 | 0 |

### What the numbers show

With one client, FP8 is slower to the first token than bf16, 739 ms against 575 ms, and
faster for each token after it, 35 ms against 61 ms. At 16 clients FP8 gives 151.4 tokens
per second against 106.9, 42% more. The bf16 KV cache holds 22,976 tokens
([above](#what-one-l4-holds)), about ten requests of 2,170 tokens, so at 16 clients some
requests wait for space. The first token shows it: at p95 it takes 23.7 seconds, nearly
five times the p50. The FP8 cache holds about 31 such requests, and at 16 clients its p95
first token is 2.5 seconds, 4% above its p50. Qwen3-1.7B gives 404.8 tokens per second at
16 clients, with the first token in under half a second at every level.

The two runs at 8 clients are within 3% of each other in every column, for all three
versions. As a cross-check, vLLM's own `vllm bench serve` ran at 8 clients on version 4
with the same shape of request. It measured a p50 TTFT of 2,445 ms and a p50 TPOT of
59.5 ms, within 6% of the rows above.
