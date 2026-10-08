from time import perf_counter

from fastapi import Request
from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "pyspark_generator_http_requests_total",
    "HTTP requests processed by the service.",
    ("method", "path", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "pyspark_generator_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "path"),
)
LLM_REQUESTS = Counter(
    "pyspark_generator_llm_requests_total",
    "LLM completion requests by result.",
    ("operation", "result"),
)
LLM_REQUEST_DURATION = Histogram(
    "pyspark_generator_llm_request_duration_seconds",
    "LLM completion request duration in seconds.",
    ("operation",),
)


async def collect_request_metrics(request: Request, call_next):
    started_at = perf_counter()
    response = await call_next(request)
    path = request.url.path
    HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
    HTTP_REQUEST_DURATION.labels(request.method, path).observe(perf_counter() - started_at)
    return response