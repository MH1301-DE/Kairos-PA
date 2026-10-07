from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kairos.agent import llm_client


@pytest.mark.asyncio
async def test_get_completion_raises_without_a_deployment_api_key() -> None:
    session = MagicMock()
    with (
        patch.object(llm_client.settings, "llm_api_key", None),
        pytest.raises(llm_client.NoLlmCredentialConfigured),
    ):
        await llm_client.get_completion(
            session, user_id=uuid4(), messages=[{"role": "user", "content": "hi"}]
        )


@pytest.mark.asyncio
async def test_get_completion_passes_model_key_messages_tools_through() -> None:
    user_id = uuid4()
    fake_setting = MagicMock(llm_model="anthropic/claude-sonnet-5")
    fake_response = MagicMock()

    with (
        patch.object(llm_client.settings, "llm_api_key", "sk-deployment-key"),
        patch.object(
            llm_client, "get_or_default_user_setting", new=AsyncMock(return_value=fake_setting)
        ),
        patch.object(
            llm_client.litellm, "completion", return_value=fake_response
        ) as mock_completion,
    ):
        session = MagicMock()
        messages = [{"role": "user", "content": "Wie erholt bin ich heute?"}]
        tools = [{"type": "function", "function": {"name": "query_health"}}]

        result = await llm_client.get_completion(
            session, user_id=user_id, messages=messages, tools=tools
        )

    assert result is fake_response
    mock_completion.assert_called_once()
    call_kwargs = mock_completion.call_args.kwargs
    assert call_kwargs["model"] == "anthropic/claude-sonnet-5"
    assert call_kwargs["messages"] == messages
    assert call_kwargs["tools"] == tools
    assert call_kwargs["api_key"] == "sk-deployment-key"
    assert call_kwargs["stream"] is False


@pytest.mark.asyncio
async def test_stream_completion_raises_without_a_deployment_api_key() -> None:
    with (
        patch.object(llm_client.settings, "llm_api_key", None),
        pytest.raises(llm_client.NoLlmCredentialConfigured),
    ):
        async for _ in llm_client.stream_completion(
            MagicMock(), user_id=uuid4(), messages=[{"role": "user", "content": "hi"}]
        ):
            pass


@pytest.mark.asyncio
async def test_stream_completion_streams_chunks_from_acompletion() -> None:
    async def _chunks():
        yield "a"
        yield "b"

    fake_setting = MagicMock(llm_model="anthropic/claude-sonnet-5")
    with (
        patch.object(llm_client.settings, "llm_api_key", "sk-deployment-key"),
        patch.object(
            llm_client, "get_or_default_user_setting", new=AsyncMock(return_value=fake_setting)
        ),
        patch.object(
            llm_client.litellm, "acompletion", new=AsyncMock(return_value=_chunks())
        ) as mock_acompletion,
    ):
        chunks = [
            c async for c in llm_client.stream_completion(
                MagicMock(), user_id=uuid4(), messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )
        ]

    assert chunks == ["a", "b"]
    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "anthropic/claude-sonnet-5"
    assert call_kwargs["api_key"] == "sk-deployment-key"
    assert call_kwargs["stream"] is True
