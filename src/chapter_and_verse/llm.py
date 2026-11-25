from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from chapter_and_verse.config import Settings, get_settings
from chapter_and_verse.db import Section
from chapter_and_verse.errors import UpstreamUnavailable
from chapter_and_verse.models import Claim, Draft

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 4096
SYSTEM_PROMPT = (
    "You answer questions about UK legislation, using only the sections given in the "
    "message. Answer as a list of claims. Each claim has three parts. text: one short, "
    "plain statement. section: the number of the section it comes from, as in its "
    "heading, for example 94 or 43B. quote: at least five words copied exactly from "
    "that section, in one unbroken run, that say what the claim says. If the sections "
    "do not answer the question, return no claims."
)
# The reply must be JSON of this shape. Claude builds it under the schema, so it parses.
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "section": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["text", "section", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}
CANNOT_ANSWER = "I cannot answer this from the sections of the Act that I found."

# Takes a prompt, returns the model's reply as JSON text. The endpoint depends on this,
# not on Claude.
Answerer = Callable[[str], Awaitable[str]]


def build_prompt(question: str, sections: list[Section]) -> str:
    # The sections first, the question last, where the model reads it best.
    parts = [f"Section {s.number}. {s.title}\n{s.text}" for s in sections]
    return "\n\n".join([*parts, f"Question: {question}"])


async def ask_claude(prompt: str, settings: Settings, client: httpx.AsyncClient) -> str:
    headers = {
        "x-api-key": settings.claude_api_token.get_secret_value(),
        "anthropic-version": ANTHROPIC_VERSION,
    }
    body = {
        "model": settings.claude_model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "output_config": {"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        "messages": [{"role": "user", "content": prompt}],
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


def parse_draft(text: str) -> list[Claim]:
    try:
        return Draft.model_validate_json(text).claims
    except ValidationError as exc:
        # Cut off at max_tokens, or a model that does not follow the schema.
        raise UpstreamUnavailable("The model sent claims we cannot read") from exc


def write_answer(claims: Sequence[Claim]) -> str:
    # Sequence, so a list of a Claim subclass is accepted too.
    if not claims:
        return CANNOT_ANSWER
    return " ".join(f"{claim.text} [s. {claim.section}]" for claim in claims)


def get_http_client(request: Request) -> httpx.AsyncClient:
    # Created once in the app lifespan, see main.py.
    client: httpx.AsyncClient = request.app.state.http_client
    return client


def get_answerer(
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> Answerer:
    return partial(ask_claude, settings=settings, client=client)
