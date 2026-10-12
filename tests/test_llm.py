import asyncio
import json

import pytest
from fastapi import HTTPException

import app.llm as llm
from app.schemas import ChatContext, ChatDetail, ContextFile


def test_request_completion_disables_ssl_verification(monkeypatch):
    captured_client_options = {}
    captured_payload = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Generated code"}}]}

    class AsyncClient:
        def __init__(self, **options):
            captured_client_options.update(options)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def post(self, *args, **kwargs):
            captured_payload.update(kwargs["json"])
            return Response()

    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(llm.config, "LLM_VERIFY_SSL", False)
    monkeypatch.setattr(llm.httpx, "AsyncClient", AsyncClient)

    chat = ChatDetail(
        id="chat-id",
        title="Test",
        created_at="now",
        updated_at="now",
        messages=[],
        context=ChatContext(),
    )

    assert asyncio.run(llm.request_completion(chat, "generate")) == "Generated code"
    assert captured_client_options == {"timeout": 90, "verify": False}
    assert "max_tokens" not in captured_payload


def test_stream_completion_omits_output_token_budget(monkeypatch):
    captured_payload = {}

    async def handler(request):
        captured_payload.update(json.loads(request.content))
        event = {"choices": [{"delta": {"content": "Done"}, "finish_reason": "stop"}]}
        body = f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n"
        return llm.httpx.Response(200, content=body.encode())

    original_async_client = llm.httpx.AsyncClient
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://llm.example")
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=llm.httpx.MockTransport(handler), **kwargs),
    )
    chat = ChatDetail(
        id="chat-id",
        title="Test",
        created_at="now",
        updated_at="now",
        messages=[],
        context=ChatContext(),
    )

    async def collect_stream():
        return [chunk async for chunk in llm.stream_completion(chat, "generate")]

    assert asyncio.run(collect_stream()) == ["Done"]
    assert "max_tokens" not in captured_payload
    assert captured_payload["stream"] is True


def test_stream_completion_consumes_done_after_finish_reason(monkeypatch):
    stream_state = {"done_seen": False}

    class EventStream(llm.httpx.AsyncByteStream):
        async def __aiter__(self):
            events = [
                {"choices": [{"delta": {"content": "Done"}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"completion_tokens": 1}},
                "[DONE]",
            ]
            for event in events:
                data = event if isinstance(event, str) else json.dumps(event)
                if event == "[DONE]":
                    stream_state["done_seen"] = True
                yield f"data: {data}\n\n".encode()

    async def handler(request):
        return llm.httpx.Response(200, stream=EventStream())

    original_async_client = llm.httpx.AsyncClient
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://llm.example")
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=llm.httpx.MockTransport(handler), **kwargs),
    )
    chat = ChatDetail(
        id="chat-id",
        title="Test",
        created_at="now",
        updated_at="now",
        messages=[],
        context=ChatContext(),
    )

    async def collect_stream():
        return [chunk async for chunk in llm.stream_completion(chat, "generate")]

    assert asyncio.run(collect_stream()) == ["Done"]
    assert stream_state["done_seen"]


def test_stream_completion_continues_after_output_limit(monkeypatch):
    captured_payloads = []
    segments = [("first part", "length"), (" second part", "stop")]

    async def handler(request):
        payload = json.loads(request.content)
        captured_payloads.append(payload)
        content, finish_reason = segments[len(captured_payloads) - 1]
        events = [
            {"choices": [{"delta": {"content": content}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": finish_reason}]},
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        body += "data: [DONE]\n\n"
        return llm.httpx.Response(200, content=body.encode())

    original_async_client = llm.httpx.AsyncClient
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://llm.example")
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(llm.config, "LLM_MAX_CONTINUATIONS", 2, raising=False)
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=llm.httpx.MockTransport(handler), **kwargs),
    )
    chat = ChatDetail(
        id="chat-id",
        title="Test",
        created_at="now",
        updated_at="now",
        messages=[],
        context=ChatContext(),
    )

    async def collect_stream():
        return "".join([chunk async for chunk in llm.stream_completion(chat, "generate")])

    assert asyncio.run(collect_stream()) == "first part second part"
    assert len(captured_payloads) == 2
    assert all("max_tokens" not in payload for payload in captured_payloads)
    continuation_messages = captured_payloads[1]["messages"]
    assert continuation_messages[-2] == {"role": "assistant", "content": "first part"}
    assert continuation_messages[-1]["role"] == "user"
    assert "Continue exactly" in continuation_messages[-1]["content"]


def test_stream_completion_stops_after_max_continuations(monkeypatch):
    request_count = 0

    async def handler(request):
        nonlocal request_count
        request_count += 1
        events = [
            {"choices": [{"delta": {"content": "part"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        body += "data: [DONE]\n\n"
        return llm.httpx.Response(200, content=body.encode())

    original_async_client = llm.httpx.AsyncClient
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://llm.example")
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(llm.config, "LLM_MAX_CONTINUATIONS", 1)
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=llm.httpx.MockTransport(handler), **kwargs),
    )
    chat = ChatDetail(
        id="chat-id",
        title="Test",
        created_at="now",
        updated_at="now",
        messages=[],
        context=ChatContext(),
    )

    async def collect_stream():
        return [chunk async for chunk in llm.stream_completion(chat, "generate")]

    with pytest.raises(HTTPException, match="remained truncated") as error:
        asyncio.run(collect_stream())

    assert error.value.status_code == 502
    assert request_count == 2


def test_system_prompt_requires_response_in_request_language():
    prompt = llm.system_prompt("generate")

    assert "same language as the user's latest request" in prompt
    assert "If it is in Italian" in prompt


def test_context_prompt_prioritizes_selected_editor_code():
    prompt = llm.context_prompt(ChatContext(
        relevant_code="entire file",
        selected_code="selected expression",
        files=[ContextFile(name="source.csv", content="", analysis="Columns (2): id, name")],
    ))

    assert "Selected editor code (address this directly)" in prompt
    assert "selected expression" in prompt
    assert "Structural analysis for context source source.csv" in prompt