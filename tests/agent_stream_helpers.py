from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

from litellm import ModelResponseStream
from litellm.types.utils import Delta, StreamingChoices


def text_chunk(text: str, finish_reason: str | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        choices=[StreamingChoices(delta=Delta(content=text), finish_reason=finish_reason)]
    )


def tool_call_chunk(index: int, call_id: str, name: str, arguments: str) -> ModelResponseStream:
    delta = Delta(tool_calls=[{
        "index": index, "id": call_id, "type": "function",
        "function": {"name": name, "arguments": arguments},
    }])
    return ModelResponseStream(choices=[StreamingChoices(delta=delta)])


def finish_chunk(finish_reason: str) -> ModelResponseStream:
    return ModelResponseStream(
        choices=[StreamingChoices(delta=Delta(), finish_reason=finish_reason)]
    )


async def chunks_of(chunks: list[ModelResponseStream]) -> AsyncIterator[ModelResponseStream]:
    for chunk in chunks:
        yield chunk


def stream_of(response: Any) -> AsyncIterator[ModelResponseStream]:
    # turns a fake non-streaming response (choices[0].message) into a chunk stream
    message = response.choices[0].message
    chunks: list[ModelResponseStream] = []
    if message.content:
        chunks.append(text_chunk(message.content))
    for index, tc in enumerate(message.tool_calls or []):
        chunks.append(tool_call_chunk(index, tc.id, tc.function.name, tc.function.arguments))
    chunks.append(finish_chunk("tool_calls" if message.tool_calls else "stop"))
    return chunks_of(chunks)


def stream_rounds(*responses: Any) -> MagicMock:
    return MagicMock(side_effect=[stream_of(r) for r in responses])


def stream_forever(response: Any) -> MagicMock:
    return MagicMock(side_effect=lambda *_args, **_kwargs: stream_of(response))
