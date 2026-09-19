import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from chapter_and_verse.config import Settings
from chapter_and_verse.errors import UpstreamUnavailable
from chapter_and_verse.llm import ANTHROPIC_VERSION, MESSAGES_URL, ask_claude

pytestmark = pytest.mark.anyio

QUESTION = "When did the Data Protection Act 2018 come into force?"


@pytest.fixture
def settings() -> Settings:
    # Passed in directly, so the test never depends on a real .env.
    return Settings(claude_api_token=SecretStr("test-token"), claude_model="test-model")


def claude_reply(
    *blocks: dict[str, str], stop_reason: str = "end_turn"
) -> httpx.Response:
    return httpx.Response(
        200, json={"content": list(blocks), "stop_reason": stop_reason}
    )


@respx.mock
async def test_returns_text_from_reply(settings: Settings) -> None:
    route = respx.post(MESSAGES_URL).mock(
        return_value=claude_reply(
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": "On 25 May 2018."},
        )
    )

    answer = await ask_claude(QUESTION, settings)

    assert answer == "On 25 May 2018."
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "test-token"
    assert sent.headers["anthropic-version"] == ANTHROPIC_VERSION
    body = json.loads(sent.content)
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": QUESTION}]


@respx.mock
async def test_server_error_raises_upstream_unavailable(settings: Settings) -> None:
    respx.post(MESSAGES_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings)


@respx.mock
async def test_timeout_raises_upstream_unavailable(settings: Settings) -> None:
    respx.post(MESSAGES_URL).mock(side_effect=httpx.ReadTimeout("too slow"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings)


@respx.mock
async def test_connection_error_raises_upstream_unavailable(settings: Settings) -> None:
    respx.post(MESSAGES_URL).mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings)


@respx.mock
async def test_reply_without_text_raises_upstream_unavailable(
    settings: Settings,
) -> None:
    respx.post(MESSAGES_URL).mock(return_value=claude_reply(stop_reason="refusal"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings)


@respx.mock
async def test_unreadable_reply_raises_upstream_unavailable(settings: Settings) -> None:
    respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, text="<html>"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings)
