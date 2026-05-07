from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.agent.schemas import TestCase


SECRET_HEADER_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "api-key",
}


class HttpExecutionResult(BaseModel):
    method: str
    url: str
    request_body: dict[str, Any] | None = None
    request_headers: dict[str, str] = Field(default_factory=dict)
    status_code: int | None = None
    response_body: Any = None
    response_body_is_json: bool = False
    latency_ms: float
    error_message: str | None = None


def execute_test_case(
    test_case: TestCase,
    *,
    base_url: str,
    timeout_seconds: float = 10.0,
) -> HttpExecutionResult:
    method = test_case.method.upper()
    url = _build_url(base_url, test_case)
    redacted_headers = redact_headers(test_case.headers)
    started_at = perf_counter()

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.request(
                method,
                url,
                params=test_case.query_params,
                headers=test_case.headers,
                json=test_case.body,
            )
        latency_ms = (perf_counter() - started_at) * 1000
        response_body, response_body_is_json = _decode_response_body(response)
        return HttpExecutionResult(
            method=method,
            url=str(response.request.url),
            request_body=test_case.body,
            request_headers=redacted_headers,
            status_code=response.status_code,
            response_body=response_body,
            response_body_is_json=response_body_is_json,
            latency_ms=round(latency_ms, 2),
        )
    except httpx.RequestError as exc:
        latency_ms = (perf_counter() - started_at) * 1000
        return HttpExecutionResult(
            method=method,
            url=url,
            request_body=test_case.body,
            request_headers=redacted_headers,
            latency_ms=round(latency_ms, 2),
            error_message=str(exc),
        )


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for name, value in headers.items():
        if _is_secret_header(name):
            redacted[name] = "[REDACTED]"
        else:
            redacted[name] = value
    return redacted


def _build_url(base_url: str, test_case: TestCase) -> str:
    path = test_case.path
    for name, value in test_case.path_params.items():
        path = path.replace("{" + name + "}", str(value))
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _decode_response_body(response: httpx.Response) -> tuple[Any, bool]:
    if response.status_code == 204 or not response.content:
        return None, False
    try:
        return response.json(), True
    except ValueError:
        return response.text, False


def _is_secret_header(name: str) -> bool:
    normalized = name.lower()
    return (
        normalized in SECRET_HEADER_NAMES
        or "token" in normalized
        or "secret" in normalized
    )
