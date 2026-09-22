from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from chapter_and_verse.config import Settings, get_settings
from chapter_and_verse.errors import UpstreamUnavailable

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 4096
SYSTEM_PROMPT = (
    "You answer questions about UK legislation. Answer briefly and plainly. "
    "If you are not sure, say so."
)

# Takes a question, returns an answer. The endpoint depends on this, not on Claude.
Answerer = Callable[[str], Awaitable[str]]


async def ask_claude(
    question: str, settings: Settings, client: httpx.AsyncClient
) -> str:
    headers = {
        "x-api-key": settings.claude_api_token.get_secret_value(),
        "anthropic-version": ANTHROPIC_VERSION,
    }
    body = {
        "model": settings.claude_model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": question}],
    }
    try:
        response = await _post_to_claude(client, headers, body)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise UpstreamUnavailable(
            f"Claude returned {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        # Timeouts and connection failures, after the last attempt.
        raise UpstreamUnavailable(f"Claude request failed: {exc!r}") from exc

    return extract_text(response)


# A request that got no response is retried. An error status is not.
@retry(
    retry=retry_if_exception_type(httpx.RequestError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,  # raise the last httpx error, not tenacity's RetryError
)
async def _post_to_claude(
    client: httpx.AsyncClient, headers: dict[str, str], body: dict[str, Any]
) -> httpx.Response:
    return await client.post(MESSAGES_URL, headers=headers, json=body)


def extract_text(response: httpx.Response) -> str:
    try:
        data: dict[str, Any] = response.json()
        blocks: list[dict[str, Any]] = data["content"]
        texts = [str(b["text"]) for b in blocks if b.get("type") == "text"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamUnavailable("Claude sent a response we cannot read") from exc

    # A refusal or an empty reply has no text block.
    if not texts:
        raise UpstreamUnavailable(
            f"No text in reply, stop_reason={data.get('stop_reason')}"
        )
    return "".join(texts)


def get_http_client(request: Request) -> httpx.AsyncClient:
    # Created once in the app lifespan, see main.py.
    client: httpx.AsyncClient = request.app.state.http_client
    return client


def get_answerer(
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> Answerer:
    return partial(ask_claude, settings=settings, client=client)
