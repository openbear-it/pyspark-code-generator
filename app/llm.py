from time import perf_counter

import httpx
from fastapi import HTTPException

from app import config
from app.metrics import LLM_REQUEST_DURATION, LLM_REQUESTS
from app.schemas import ChatContext, ChatDetail, Operation


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
        "and state assumptions when schema or platform context is missing."
    )


def context_prompt(context: ChatContext) -> str:
    parts = [
        f"Programming language: {context.programming_language}.",
        f"PySpark or data libraries: {context.libraries}.",
    ]
    if context.requirements:
        parts.append(f"Additional requirements:\n{context.requirements}")
    if context.relevant_code:
        parts.append(f"Relevant code:\n```\n{context.relevant_code}\n```")
    return "\n\n".join(parts)


async def request_completion(chat: ChatDetail, operation: Operation) -> str:
    if not all((config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL)):
        raise HTTPException(
            status_code=503,
            detail="LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must be configured",
        )

    messages = [{"role": "system", "content": f"{system_prompt(operation)}\n\n{context_prompt(chat.context)}"}]
    messages.extend({"role": message.role, "content": message.content} for message in chat.messages)
    endpoint = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {"model": config.LLM_MODEL, "messages": messages, "temperature": 0.2}
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