import json
from collections.abc import AsyncIterator
from time import perf_counter

import httpx
from fastapi import HTTPException

from app import config
from app.metrics import LLM_REQUEST_DURATION, LLM_REQUESTS
from app.schemas import ChatContext, ChatDetail, Operation


def validate_llm_configuration() -> None:
    if not all((config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL)):
        raise HTTPException(
            status_code=503,
            detail="LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must be configured",
        )


def system_prompt(operation: Operation) -> str:
    goals = {
        "generate": "Generate production-ready PySpark code for the requested task.",
        "analyze": "Analyze the supplied PySpark code or files. Identify correctness, performance, and data-quality issues.",
        "improve": "Improve the supplied PySpark code. Return the revised code first, then concise reasoning.",
        "comment": "Add useful, concise comments and documentation to the supplied code without changing its behavior.",
    }
    return (
        "You are a senior data engineer specializing in Apache Spark and PySpark. "
        f"{goals[operation]} Use idiomatic PySpark DataFrame APIs, account for scale, "
        "and state assumptions when schema or platform context is missing. "
        "Respond in the same language as the user's latest request. If it is in Italian, "
        "write the response in Italian, except for code and established technical terms."
    )


def context_prompt(context: ChatContext) -> str:
    parts = [
        f"Programming language: {context.programming_language}.",
        f"PySpark or data libraries: {context.libraries}.",
    ]
    if context.selected_code:
        parts.append(f"Selected editor code (address this directly):\n```\n{context.selected_code}\n```")
    for file in context.files:
        if file.analysis:
            parts.append(f"Structural analysis for context source {file.name}:\n{file.analysis}")
        if file.content:
            parts.append(f"Context file: {file.name}\n```\n{file.content}\n```")
    if context.requirements:
        parts.append(f"Additional requirements:\n{context.requirements}")
    if context.relevant_code:
        parts.append(f"Relevant code:\n```\n{context.relevant_code}\n```")
    return "\n\n".join(parts)


async def request_completion(chat: ChatDetail, operation: Operation) -> str:
    validate_llm_configuration()

    messages = [{"role": "system", "content": f"{system_prompt(operation)}\n\n{context_prompt(chat.context)}"}]
    messages.extend({"role": message.role, "content": message.content} for message in chat.messages)
    endpoint = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": config.LLM_MAX_OUTPUT_TOKENS,
    }
    started_at = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=90, verify=config.LLM_VERIFY_SSL) as client:
            response = await client.post(endpoint, headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        LLM_REQUESTS.labels(operation, "success").inc()
        return content
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as error:
        LLM_REQUESTS.labels(operation, "error").inc()
        raise HTTPException(status_code=502, detail=f"LLM request failed: {error}") from error
    finally:
        LLM_REQUEST_DURATION.labels(operation).observe(perf_counter() - started_at)


async def request_code_suggestion(context: ChatContext, code: str, cursor: int) -> str:
    validate_llm_configuration()
    before_cursor = code[:cursor]
    after_cursor = code[cursor:]
    prompt = (
        "Suggest the shortest useful continuation at the cursor for the current PySpark code. "
        "Return only code to insert, with no Markdown fences, explanation, or repeated existing lines. "
        "Limit the suggestion to 12 lines.\n\n"
        f"{context_prompt(context)}\n\n"
        f"Code before cursor:\n```\n{before_cursor}\n```\n\n"
        f"Code after cursor:\n```\n{after_cursor}\n```"
    )
    endpoint = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {"model": config.LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    started_at = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30, verify=config.LLM_VERIFY_SSL) as client:
            response = await client.post(endpoint, headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}, json=payload)
            response.raise_for_status()
            suggestion = response.json()["choices"][0]["message"]["content"].strip()
        if suggestion.startswith("```"):
            suggestion = "\n".join(suggestion.splitlines()[1:-1]).strip()
        LLM_REQUESTS.labels("suggest", "success").inc()
        return suggestion
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as error:
        LLM_REQUESTS.labels("suggest", "error").inc()
        raise HTTPException(status_code=502, detail=f"LLM suggestion failed: {error}") from error
    finally:
        LLM_REQUEST_DURATION.labels("suggest").observe(perf_counter() - started_at)


async def stream_completion(chat: ChatDetail, operation: Operation) -> AsyncIterator[str]:
    validate_llm_configuration()

    messages = [{"role": "system", "content": f"{system_prompt(operation)}\n\n{context_prompt(chat.context)}"}]
    messages.extend({"role": message.role, "content": message.content} for message in chat.messages)
    endpoint = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": config.LLM_MAX_OUTPUT_TOKENS,
        "stream": True,
    }
    started_at = perf_counter()
    stream_finished = False
    try:
        async with httpx.AsyncClient(timeout=90, verify=config.LLM_VERIFY_SSL) as client:
            async with client.stream("POST", endpoint, headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = line.removeprefix("data:").strip()
                    if event == "[DONE]":
                        stream_finished = True
                        break
                    choice = json.loads(event)["choices"][0]
                    content = choice.get("delta", {}).get("content")
                    if content:
                        yield content
                    finish_reason = choice.get("finish_reason")
                    if finish_reason is not None:
                        stream_finished = True
                        if finish_reason == "length":
                            LLM_REQUESTS.labels(operation, "error").inc()
                            raise HTTPException(status_code=502, detail="LLM response was truncated at its output length limit")
        if not stream_finished:
            raise HTTPException(status_code=502, detail="LLM stream ended before completion")
        LLM_REQUESTS.labels(operation, "success").inc()
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        LLM_REQUESTS.labels(operation, "error").inc()
        raise HTTPException(status_code=502, detail=f"LLM request failed: {error}") from error
    finally:
        LLM_REQUEST_DURATION.labels(operation).observe(perf_counter() - started_at)