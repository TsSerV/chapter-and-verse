"""Keep chat requests in flight against the served model, one per client, for a while.

Standard library only, so it also runs in a plain python image inside the cluster.
"""

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

QUESTION = "Explain what the Equality Act 2010 does, in about 200 words."


def client(url: str, until: float) -> tuple[int, int]:
    # One user: asks again as soon as the last answer arrives.
    body = {
        "model": "answerer",
        "messages": [{"role": "user", "content": QUESTION}],
        "max_tokens": 300,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        f"{url}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    answered = failed = 0
    while time.monotonic() < until:
        try:
            # A new connection each time, so the Service spreads requests over replicas.
            with urllib.request.urlopen(request, timeout=300) as response:
                response.read()
            answered += 1
        except OSError:
            failed += 1
            time.sleep(1)
    return answered, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--seconds", type=int, default=300)
    args = parser.parse_args()

    until = time.monotonic() + args.seconds
    with ThreadPoolExecutor(args.clients) as pool:
        results = list(pool.map(lambda _: client(args.url, until), range(args.clients)))
    answered = sum(ok for ok, _ in results)
    failed = sum(bad for _, bad in results)
    print(f"{args.clients} clients, {args.seconds} s: {answered} answered, {failed} failed")


if __name__ == "__main__":
    main()
