import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from serving.benchmark import Sample, ask, measure, read_stream, request_body, summarise


def event(chunk: dict[str, Any]) -> bytes:
    return b"data: " + json.dumps(chunk).encode() + b"\n"


ROLE = event({"choices": [{"delta": {"role": "assistant", "content": ""}}]})
TOKEN = event({"choices": [{"delta": {"content": "law"}}]})
USAGE = event({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
DONE = b"data: [DONE]\n"
ANSWER = [ROLE, TOKEN, b"\n", TOKEN, b"\n", TOKEN, USAGE, DONE]


def test_every_prompt_is_different_and_every_answer_the_same_length() -> None:
    first, second = request_body(200, 64), request_body(200, 64)

    assert first["messages"] != second["messages"]
    assert (first["max_tokens"], first["ignore_eos"], first["stream"]) == (64, True, True)


def test_counts_only_chunks_with_text_as_tokens() -> None:
    times = iter(float(tick) for tick in range(1, 9))

    sample = read_stream(ANSWER, started=0.5, clock=lambda: next(times))

    # ROLE arrives at 1. The three tokens at 2, 4 and 6, with blank lines between them.
    assert sample.token_times == [2.0, 4.0, 6.0]
    assert sample.prompt_tokens == 12


def test_latency_counts_whole_requests_and_throughput_every_token() -> None:
    whole = Sample(10.0, [10.1, 10.3, 10.5])
    in_the_warm_up = Sample(5.0, [5.1, 5.2])
    cut_by_the_deadline = Sample(19.0, [19.5, 20.5])

    results = summarise([whole, in_the_warm_up, cut_by_the_deadline], 1, 10.0, 20.0)

    assert (results["requests"], results["failed"]) == (1, 1)
    assert results["ttft_p50_ms"] == pytest.approx(100.0)
    assert results["tpot_p50_ms"] == pytest.approx(200.0)
    # Three tokens from the whole request and one from the request cut by the deadline.
    assert results["output_tokens_per_second"] == pytest.approx(0.4)


def test_stops_when_no_request_finished_inside_the_window() -> None:
    with pytest.raises(SystemExit):
        summarise([Sample(5.0, [5.1, 5.2])], 0, 10.0, 20.0)


class FakeVllm(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b"".join(ANSWER))

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def fake_vllm() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVllm)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_reads_a_real_response(fake_vllm: str) -> None:
    sample = ask(fake_vllm, request_body(5, 3))

    assert (len(sample.token_times), sample.prompt_tokens) == (3, 12)


def test_measures_with_several_clients(fake_vllm: str) -> None:
    measurement = measure(fake_vllm, 2, 1, 0, 5, 3)

    assert measurement["settings"]["clients"] == 2
    assert measurement["results"]["requests"] >= 1
    assert measurement["results"]["failed"] == 0
