import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.agent.reflection import AgentReflection
from app.agent.workflow import RunSummary
from app.core.config import Settings, get_settings


ReflectionClient = Callable[[dict[str, Any]], dict[str, Any]]
SUBMIT_REFLECTION_TOOL_NAME = "submit_reflection"


class LLMReflectionResult(BaseModel):
    reflection: AgentReflection
    used_llm: bool
    fallback_reason: str | None = None
    raw_output: dict[str, Any] | None = None


class LLMReflectionError(ValueError):
    """Raised when LLM reflection output cannot be used safely."""


def generate_reflection_with_optional_llm(
    *,
    summary: RunSummary,
    enabled: bool,
    settings: Settings | None = None,
    reflection_client: ReflectionClient | None = None,
) -> LLMReflectionResult:
    deterministic_reflection = _deterministic_reflection(summary)
    if not enabled:
        return LLMReflectionResult(
            reflection=deterministic_reflection,
            used_llm=False,
        )

    settings = settings or get_settings()
    if reflection_client is None and not settings.llm_api_key:
        return LLMReflectionResult(
            reflection=deterministic_reflection,
            used_llm=False,
            fallback_reason="LLM reflection is enabled, but LLM_API_KEY is not configured.",
        )

    try:
        payload = _build_reflection_payload(summary, settings)
        assistant_message = (
            reflection_client(payload)
            if reflection_client is not None
            else _call_openai_compatible_chat(payload, settings)
        )
        reflection = _parse_reflection_tool_call(assistant_message)
    except (LLMReflectionError, ValidationError, httpx.HTTPError) as exc:
        return LLMReflectionResult(
            reflection=deterministic_reflection,
            used_llm=False,
            fallback_reason=str(exc),
            raw_output=assistant_message if "assistant_message" in locals() else None,
        )

    return LLMReflectionResult(
        reflection=reflection,
        used_llm=True,
        raw_output=assistant_message,
    )


def _deterministic_reflection(summary: RunSummary) -> AgentReflection:
    if summary.failed == 0:
        return AgentReflection(
            key_findings=["All generated test cases passed."],
            suspected_root_causes=[],
            needs_more_tests=False,
            next_test_focus=[],
            recommended_next_action="finish_run",
            reason="No contract violations were detected by deterministic validation.",
        )

    failed_focus = sorted({failed_case.test_type for failed_case in summary.failed_cases})
    causes = sorted({failed_case.diagnosis for failed_case in summary.failed_cases})
    return AgentReflection(
        key_findings=[
            f"{summary.failed} of {summary.total} test cases failed deterministic validation."
        ],
        suspected_root_causes=causes,
        needs_more_tests=False,
        next_test_focus=failed_focus,
        recommended_next_action="finish_run",
        reason="The current run already exposed clear contract failures.",
    )


def _build_reflection_payload(
    summary: RunSummary,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "model": settings.llm_model,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "tool_choice": {
            "type": "function",
            "function": {"name": SUBMIT_REFLECTION_TOOL_NAME},
        },
        "tools": [_submit_reflection_tool()],
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are reflecting on API test observations. "
                    "Call submit_reflection exactly once. Do not decide pass/fail; "
                    "pass/fail was already computed by deterministic backend code."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "summary": summary.model_dump(mode="json"),
                        "instructions": [
                            "Explain what the failures suggest.",
                            "Recommend whether more tests are needed.",
                            "Do not invent executions that did not happen.",
                        ],
                    },
                    separators=(",", ":"),
                ),
            },
        ],
    }


def _call_openai_compatible_chat(
    payload: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    response = httpx.post(
        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        json={**payload, "model": settings.llm_model},
        timeout=max(settings.llm_timeout_seconds, 60.0),
    )
    _raise_for_status_with_body(response)
    data = response.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMReflectionError("LLM response did not contain message content.") from exc
    if not isinstance(message, dict):
        raise LLMReflectionError("LLM response message was not an object.")
    return message


def _parse_reflection_tool_call(assistant_message: dict[str, Any]) -> AgentReflection:
    tool_calls = assistant_message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        raise LLMReflectionError("LLM reflector did not call submit_reflection.")

    matching_calls = [
        tool_call
        for tool_call in tool_calls
        if _tool_call_name(tool_call) == SUBMIT_REFLECTION_TOOL_NAME
    ]
    if len(matching_calls) != 1:
        raise LLMReflectionError("LLM reflector must call submit_reflection exactly once.")

    arguments = _tool_call_arguments(matching_calls[0])
    try:
        decoded = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise LLMReflectionError("LLM reflection tool arguments were invalid JSON.") from exc
    return AgentReflection.model_validate(decoded)


def _submit_reflection_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": SUBMIT_REFLECTION_TOOL_NAME,
            "description": (
                "Submit structured reflection about deterministic API test results. "
                "This tool does not execute tests and does not decide pass/fail."
            ),
            "parameters": _submit_reflection_parameters(),
        },
    }


def _submit_reflection_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key_findings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "suspected_root_causes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "needs_more_tests": {"type": "boolean"},
            "next_test_focus": {
                "type": "array",
                "items": {"type": "string"},
            },
            "recommended_next_action": {
                "type": "string",
                "enum": ["finish_run", "add_more_tests"],
            },
            "reason": {"type": "string"},
        },
        "required": ["reason"],
    }


def _raise_for_status_with_body(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:1000]
        raise LLMReflectionError(
            f"LLM API returned HTTP {response.status_code}: {body}"
        ) from exc


def _tool_call_name(tool_call: Any) -> str | None:
    if not isinstance(tool_call, dict):
        return None
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    return name if isinstance(name, str) else None


def _tool_call_arguments(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        raise LLMReflectionError("LLM reflection tool call did not contain a function object.")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise LLMReflectionError("LLM reflection tool arguments were not a JSON string.")
    return arguments
