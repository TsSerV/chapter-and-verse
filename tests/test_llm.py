import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from pydantic import SecretStr
from tenacity import wait_none

from chapter_and_verse.config import Settings
from chapter_and_verse.errors import UpstreamUnavailable
from chapter_and_verse.llm import (
    ANTHROPIC_VERSION,
    MESSAGES_URL,
    _post_to_claude,
    ask_claude,
)

pytestmark = pytest.mark.anyio

QUESTION = "When did the Data Protection Act 2018 come into force?"


@pytest.fixture
def settings() -> Settings:
    # Passed in directly, so the test never depends on a real .env.
    return Settings(claude_api_token=SecretStr("test-token"), claude_model="test-model")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # Stands in for the shared client the app creates at startup.
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same retry rules, without the waits between attempts.
    monkeypatch.setattr(_post_to_claude.retry, "wait", wait_none())


def claude_reply(
    *blocks: dict[str, str], stop_reason: str = "end_turn"
) -> httpx.Response:
    return httpx.Response(
        200, json={"content": list(blocks), "stop_reason": stop_reason}
    )


@respx.mock
async def test_returns_text_from_reply(
    settings: Settings, client: httpx.AsyncClient
) -> None:
    route = respx.post(MESSAGES_URL).mock(
        return_value=claude_reply(
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": "On 25 May 2018."},
        )
    )

    answer = await ask_claude(QUESTION, settings, client)

    assert answer == "On 25 May 2018."
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "test-token"
    assert sent.headers["anthropic-version"] == ANTHROPIC_VERSION
    body = json.loads(sent.content)
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": QUESTION}]


@respx.mock
async def test_transient_failure_is_retried(
    settings: Settings, client: httpx.AsyncClient
) -> None:
    route = respx.post(MESSAGES_URL).mock(
        side_effect=[
            httpx.ConnectTimeout("blip"),
            httpx.ConnectTimeout("blip"),
            claude_reply({"type": "text", "text": "On 25 May 2018."}),
        ]
    )

    answer = await ask_claude(QUESTION, settings, client)

    assert answer == "On 25 May 2018."
    assert route.call_count == 3


@pytest.mark.parametrize("status", [400, 500])
@respx.mock
async def test_error_status_is_not_retried(
    status: int, settings: Settings, client: httpx.AsyncClient
) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(status))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings, client)
    assert route.call_count == 1


@respx.mock
async def test_timeout_raises_upstream_unavailable(
    settings: Settings, client: httpx.AsyncClient
) -> None:
    route = respx.post(MESSAGES_URL).mock(side_effect=httpx.ReadTimeout("too slow"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings, client)
    assert route.call_count == 3


@respx.mock
async def test_connection_error_raises_upstream_unavailable(
    settings: Settings, client: httpx.AsyncClient
) -> None:
    route = respx.post(MESSAGES_URL).mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings, client)
    assert route.call_count == 3


@respx.mock
async def test_reply_without_text_raises_upstream_unavailable(
    settings: Settings, client: httpx.AsyncClient
) -> None:
    respx.post(MESSAGES_URL).mock(return_value=claude_reply(stop_reason="refusal"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings, client)


@respx.mock
async def test_unreadable_reply_raises_upstream_unavailable(
    settings: Settings, client: httpx.AsyncClient
) -> None:
    respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, text="<html>"))

    with pytest.raises(UpstreamUnavailable):
        await ask_claude(QUESTION, settings, client)
