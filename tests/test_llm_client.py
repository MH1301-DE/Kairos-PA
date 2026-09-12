from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kairos.agent import llm_client


@pytest.mark.asyncio
async def test_get_completion_raises_without_a_connection() -> None:
    session = MagicMock()
    scalars_result = MagicMock()
    scalars_result.first.return_value = None
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result
    session.execute = AsyncMock(return_value=execute_result)

    with pytest.raises(llm_client.NoLlmCredentialConfigured):
        await llm_client.get_completion(
            session, user_id=uuid4(), messages=[{"role": "user", "content": "hi"}]
        )


@pytest.mark.asyncio
async def test_get_completion_passes_model_key_messages_tools_through() -> None:
    user_id = uuid4()
    fake_setting = MagicMock(llm_model="anthropic/claude-sonnet-5")
    fake_response = MagicMock()

    with (
        patch.object(
            llm_client, "get_or_default_user_setting", new=AsyncMock(return_value=fake_setting)
        ),
        patch.object(
            llm_client, "_load_llm_api_key", new=AsyncMock(return_value="decrypted-key-123")
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
    assert call_kwargs["api_key"] == "decrypted-key-123"
    assert call_kwargs["stream"] is False
