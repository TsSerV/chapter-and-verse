"""Measure how fast the served model answers, at each number of concurrent clients.

Prints one JSON line per measurement: time to first token, time per output token and
output tokens per second. Standard library only, so it also runs in a plain python image
inside the cluster.
"""

import argparse
import http.client
import json
import random
import statistics
import time
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

# Drawn at random, so no two prompts share a prefix that vLLM could reuse.
WORDS = (
    "act", "section", "provision", "amendment", "commencement", "schedule", "regulation",
    "court", "tribunal", "employer", "employee", "person", "duty", "right", "claim", "notice",
    "period", "order", "authority", "minister", "service", "contract", "liability", "damages",
    "breach", "appeal", "judgment", "evidence", "statute", "clause",
)


@dataclass
class Sample:
    started: float
    token_times: list[float] = field(default_factory=list)
    prompt_tokens: int = 0


def request_body(prompt_words: int, max_tokens: int) -> dict[str, Any]:
    prompt = " ".join(random.choices(WORDS, k=prompt_words))
    return {
        "model": "answerer",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        # Every answer has the same length, so the measurements compare.
        "ignore_eos": True,
        "stream": True,
        # The last chunk says how many tokens the prompt was.
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }


def read_stream(lines: Iterable[bytes], started: float, clock: Callable[[], float]) -> Sample:
    sample = Sample(started)
    for line in lines:
        arrived = clock()
        if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
            continue
        chunk = json.loads(line.removeprefix(b"data: "))
        if chunk.get("usage"):
            sample.prompt_tokens = chunk["usage"]["prompt_tokens"]
        # The first chunk has only the role. A token is a chunk with text in it.
        if any(choice["delta"].get("content") for choice in chunk["choices"]):
            sample.token_times.append(arrived)
    return sample


def ask(url: str, body: dict[str, Any]) -> Sample:
    request = urllib.request.Request(
        f"{url}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        return read_stream(response, started, time.perf_counter)


def client(
    url: str, prompt_words: int, max_tokens: int, deadline: float
) -> tuple[list[Sample], int]:
    # One user: asks again as soon as the last answer is complete.
    samples: list[Sample] = []
    failed = 0
    while time.perf_counter() < deadline:
        try:
            samples.append(ask(url, request_body(prompt_words, max_tokens)))
        except (OSError, http.client.HTTPException):
            failed += 1
            time.sleep(1)
    return samples, failed


def percentile(values: list[float], share: int) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[share - 1]


def time_per_token(sample: Sample) -> float:
    return (sample.token_times[-1] - sample.token_times[0]) / (len(sample.token_times) - 1)


def summarise(
    samples: list[Sample], failed: int, window_start: float, deadline: float
) -> dict[str, float]:
    # Latency counts the requests that ran wholly inside the window. Throughput counts every
    # token that arrived inside it, so requests cut by the edges still add their share.
    whole = [s for s in samples if s.started >= window_start and s.token_times[-1] <= deadline]
    if not whole:
        raise SystemExit(
            f"No request finished inside the window, and {failed} failed. "
            "Check --url and --prompt-words, or use a longer --seconds."
        )
    ttft = [(s.token_times[0] - s.started) * 1000 for s in whole]
    tpot = [time_per_token(s) * 1000 for s in whole]
    e2e = [s.token_times[-1] - s.started for s in whole]
    tokens = sum(window_start <= t <= deadline for s in samples for t in s.token_times)
    seconds = deadline - window_start
    return {
        "requests": len(whole),
        "failed": failed,
        "prompt_tokens": statistics.median(s.prompt_tokens for s in whole),
        "output_tokens": statistics.median(len(s.token_times) for s in whole),
        "ttft_p50_ms": round(percentile(ttft, 50), 1),
        "ttft_p95_ms": round(percentile(ttft, 95), 1),
        "tpot_p50_ms": round(percentile(tpot, 50), 2),
        "tpot_p95_ms": round(percentile(tpot, 95), 2),
        "e2e_p50_s": round(percentile(e2e, 50), 2),
        "e2e_p95_s": round(percentile(e2e, 95), 2),
        "output_tokens_per_second": round(tokens / seconds, 1),
    }


def measure(
    url: str, clients: int, seconds: int, warmup: int, prompt_words: int, max_tokens: int
) -> dict[str, dict[str, Any]]:
    # All clients start at once. The warm up leaves that first burst out of the numbers.
    window_start = time.perf_counter() + warmup
    deadline = window_start + seconds
    with ThreadPoolExecutor(clients) as pool:
        results = list(
            pool.map(lambda _: client(url, prompt_words, max_tokens, deadline), range(clients))
        )
    samples = [sample for found, _ in results for sample in found]
    failed = sum(bad for _, bad in results)
    settings = {
        "clients": clients,
        "seconds": seconds,
        "warmup": warmup,
        "prompt_words": prompt_words,
        "max_tokens": max_tokens,
    }
    return {"settings": settings, "results": summarise(samples, failed, window_start, deadline)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--clients", default="1,2,4,8,8,16", help="comma separated: one measurement each"
    )
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--prompt-words", type=int, default=1900)
    parser.add_argument("--max-tokens", type=int, default=256)
    args = parser.parse_args()

    for clients in args.clients.split(","):
        measurement = measure(
            args.url, int(clients), args.seconds, args.warmup, args.prompt_words, args.max_tokens
        )
        print(json.dumps(measurement), flush=True)


if __name__ == "__main__":
    main()
