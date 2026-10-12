import asyncio
import json

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
    monkeypatch.setattr(llm.config, "LLM_MAX_OUTPUT_TOKENS", 6144, raising=False)
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
    assert captured_payload["max_tokens"] == 6144


def test_stream_completion_uses_configured_output_token_budget(monkeypatch):
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
    monkeypatch.setattr(llm.config, "LLM_MAX_OUTPUT_TOKENS", 6144)
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
    assert captured_payload["max_tokens"] == 6144
    assert captured_payload["stream"] is True


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