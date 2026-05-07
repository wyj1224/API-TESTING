import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.agent.planner import generate_test_plan
from app.agent.schemas import TestPlan, TestType
from app.core.config import Settings, get_settings
from app.openapi.models import ParsedOpenAPISchema


CompletionClient = Callable[[dict[str, Any]], dict[str, Any]]
SUBMIT_TEST_PLAN_TOOL_NAME = "submit_test_plan"


class LLMPlannerResult(BaseModel):
    plan: TestPlan
    used_llm: bool
    fallback_reason: str | None = None
    raw_output: dict[str, Any] | None = None


def generate_test_plan_with_optional_llm(
    parsed_schema: ParsedOpenAPISchema,
    *,
    test_types: list[TestType] | None = None,
    enabled: bool = False,
    settings: Settings | None = None,
    completion_client: CompletionClient | None = None,
) -> LLMPlannerResult:
    deterministic_plan = generate_test_plan(parsed_schema, test_types)
    if not enabled:
        return LLMPlannerResult(plan=deterministic_plan, used_llm=False)

    settings = settings or get_settings()
    if completion_client is None and not settings.llm_api_key:
        return LLMPlannerResult(
            plan=deterministic_plan,
            used_llm=False,
            fallback_reason="LLM planner is enabled, but LLM_API_KEY is not configured.",
        )

    try:
        payload = _build_chat_payload(parsed_schema, deterministic_plan, settings)
        assistant_message = (
            completion_client(payload)
            if completion_client is not None
            else _call_openai_compatible_chat(
                payload,
                settings,
            )
        )
        llm_plan = _parse_tool_call_plan(assistant_message)
        llm_plan = _normalize_plan_against_schema(llm_plan, parsed_schema)
        _validate_plan_against_schema(llm_plan, parsed_schema, deterministic_plan.test_types)
    except (LLMPlannerError, ValidationError, httpx.HTTPError) as exc:
        return LLMPlannerResult(
            plan=deterministic_plan,
            used_llm=False,
            fallback_reason=str(exc),
            raw_output=assistant_message if "assistant_message" in locals() else None,
        )

    return LLMPlannerResult(plan=llm_plan, used_llm=True, raw_output=assistant_message)


class LLMPlannerError(ValueError):
    """Raised when LLM planner output cannot be used safely."""


def _build_chat_payload(
    parsed_schema: ParsedOpenAPISchema,
    deterministic_plan: TestPlan,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "model": settings.llm_model,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "tool_choice": {
            "type": "function",
            "function": {"name": SUBMIT_TEST_PLAN_TOOL_NAME},
        },
        "tools": [_submit_test_plan_tool()],
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate API test plans by calling exactly one tool. "
                    "Do not execute HTTP requests. Do not decide pass/fail. "
                    f"Call {SUBMIT_TEST_PLAN_TOOL_NAME} with a JSON object that "
                    "matches the provided function schema. Never call any other tool."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "schema": _schema_brief(parsed_schema),
                        "allowed_test_types": deterministic_plan.test_types,
                        "deterministic_case_count": deterministic_plan.total_cases,
                        "instructions": [
                            "Keep cases safe and suitable for black-box API testing.",
                            "Improve names and sample payloads where useful.",
                            "Only use endpoints and HTTP methods present in schema.",
                            "Only use the requested test_types.",
                            "Use expected_status from the API contract or deterministic plan.",
                            "Do not include real credentials, API keys, cookies, or tokens.",
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
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    response = httpx.post(
        url,
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
        raise LLMPlannerError("LLM response did not contain message content.") from exc
    if not isinstance(message, dict):
        raise LLMPlannerError("LLM response message was not an object.")
    return message


def _parse_tool_call_plan(assistant_message: dict[str, Any]) -> TestPlan:
    tool_calls = assistant_message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        raise LLMPlannerError("LLM planner did not call submit_test_plan.")

    matching_calls = [
        tool_call
        for tool_call in tool_calls
        if _tool_call_name(tool_call) == SUBMIT_TEST_PLAN_TOOL_NAME
    ]
    if len(matching_calls) != 1:
        raise LLMPlannerError("LLM planner must call submit_test_plan exactly once.")

    arguments = _tool_call_arguments(matching_calls[0])
    try:
        decoded = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise LLMPlannerError("LLM planner tool arguments were invalid JSON.") from exc
    return TestPlan.model_validate(decoded)


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
        raise LLMPlannerError("LLM planner tool call did not contain a function object.")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise LLMPlannerError("LLM planner tool arguments were not a JSON string.")
    return arguments


def _submit_test_plan_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": SUBMIT_TEST_PLAN_TOOL_NAME,
            "description": (
                "Submit a structured APITestAgent test plan. This tool only "
                "submits planned test cases; it does not execute HTTP requests "
                "and does not decide pass/fail."
            ),
            "parameters": _submit_test_plan_parameters(),
        },
    }


def _submit_test_plan_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schema_title": {
                "type": "string",
                "description": "Title of the OpenAPI schema, if known.",
            },
            "test_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "happy_path",
                        "missing_required_field",
                        "wrong_type",
                        "not_found",
                        "unauthorized_access",
                    ],
                },
            },
            "cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "case_id": {"type": "string"},
                        "test_type": {
                            "type": "string",
                            "enum": [
                                "happy_path",
                                "missing_required_field",
                                "wrong_type",
                                "not_found",
                                "unauthorized_access",
                            ],
                        },
                        "path": {"type": "string"},
                        "method": {
                            "type": "string",
                            "enum": [
                                "get",
                                "post",
                                "put",
                                "patch",
                                "delete",
                                "options",
                                "head",
                                "trace",
                            ],
                        },
                        "operation_id": {"type": "string"},
                        "name": {"type": "string"},
                        "expected_status": {"type": "integer"},
                        "path_params": {"type": "object"},
                        "query_params": {"type": "object"},
                        "headers": {"type": "object"},
                        "body": {"type": "object"},
                    },
                    "required": [
                        "case_id",
                        "test_type",
                        "path",
                        "method",
                        "name",
                        "expected_status",
                    ],
                },
            },
        },
        "required": ["test_types", "cases"],
    }


def _raise_for_status_with_body(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:1000]
        raise LLMPlannerError(
            f"LLM API returned HTTP {response.status_code}: {body}"
        ) from exc


def _validate_plan_against_schema(
    plan: TestPlan,
    parsed_schema: ParsedOpenAPISchema,
    allowed_test_types: list[TestType],
) -> None:
    endpoint_keys = {
        (endpoint.path, endpoint.method) for endpoint in parsed_schema.endpoints
    }
    allowed_test_type_set = set(allowed_test_types)
    for test_case in plan.cases:
        if (test_case.path, test_case.method) not in endpoint_keys:
            raise LLMPlannerError(
                f"LLM generated case for unknown endpoint: {test_case.method} {test_case.path}."
            )
        if test_case.test_type not in allowed_test_type_set:
            raise LLMPlannerError(
                f"LLM generated disallowed test type: {test_case.test_type}."
            )


def _normalize_plan_against_schema(
    plan: TestPlan,
    parsed_schema: ParsedOpenAPISchema,
) -> TestPlan:
    endpoint_by_key = {
        (endpoint.path, endpoint.method): endpoint for endpoint in parsed_schema.endpoints
    }
    normalized_cases = []
    for test_case in plan.cases:
        if (test_case.path, test_case.method) in endpoint_by_key:
            normalized_cases.append(test_case)
            continue

        matched_endpoint, extracted_params = _match_concrete_path(
            test_case.path,
            test_case.method,
            parsed_schema,
        )
        if matched_endpoint is None:
            normalized_cases.append(test_case)
            continue

        normalized_cases.append(
            test_case.model_copy(
                update={
                    "path": matched_endpoint.path,
                    "path_params": {
                        **extracted_params,
                        **test_case.path_params,
                    },
                }
            )
        )
    return plan.model_copy(update={"cases": normalized_cases})


def _match_concrete_path(
    path: str,
    method: str,
    parsed_schema: ParsedOpenAPISchema,
):
    for endpoint in parsed_schema.endpoints:
        if endpoint.method != method or "{" not in endpoint.path:
            continue
        pattern, names = _path_template_regex(endpoint.path)
        match = pattern.fullmatch(path)
        if match:
            return endpoint, {
                name: _coerce_path_value(match.group(name))
                for name in names
            }
    return None, {}


def _path_template_regex(path_template: str) -> tuple[re.Pattern[str], list[str]]:
    names = re.findall(r"{([^}]+)}", path_template)
    escaped = re.escape(path_template)
    for name in names:
        escaped = escaped.replace(r"\{" + name + r"\}", f"(?P<{name}>[^/]+)")
    return re.compile(escaped), names


def _coerce_path_value(value: str) -> Any:
    return int(value) if value.isdigit() else value


def _schema_brief(parsed_schema: ParsedOpenAPISchema) -> dict[str, Any]:
    return {
        "title": parsed_schema.title,
        "version": parsed_schema.version,
        "endpoints": [
            {
                "path": endpoint.path,
                "method": endpoint.method,
                "operation_id": endpoint.operation_id,
                "requires_auth": endpoint.requires_auth,
                "parameters": _parameter_brief(endpoint),
                "request_body": _request_body_brief(endpoint, parsed_schema),
                "responses": [response.status_code for response in endpoint.responses],
            }
            for endpoint in parsed_schema.endpoints
        ],
    }


def _parameter_brief(endpoint) -> list[dict[str, Any]]:
    return [
        {
            "name": parameter.name,
            "in": parameter.location,
            "required": parameter.required,
            "type": (parameter.schema_ or {}).get("type", "string"),
        }
        for parameter in endpoint.parameters
    ]


def _request_body_brief(endpoint, parsed_schema: ParsedOpenAPISchema) -> dict[str, Any] | None:
    if endpoint.request_body is None:
        return None
    media = endpoint.request_body.content.get("application/json")
    if not isinstance(media, dict):
        return {"required": endpoint.request_body.required, "fields": []}
    schema = _resolve_schema(media.get("schema"), parsed_schema)
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required", []) if isinstance(schema, dict) else []
    fields: list[dict[str, Any]] = []
    if isinstance(properties, dict):
        for name, field_schema in properties.items():
            if isinstance(field_schema, dict):
                fields.append(
                    {
                        "name": name,
                        "type": field_schema.get("type", "string"),
                        "required": name in required,
                    }
                )
    return {"required": endpoint.request_body.required, "fields": fields}


def _resolve_schema(value: Any, parsed_schema: ParsedOpenAPISchema) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        current: Any = {"components": parsed_schema.components}
        for part in ref.removeprefix("#/").split("/"):
            if not isinstance(current, dict) or part not in current:
                return {}
            current = current[part]
        return current if isinstance(current, dict) else {}
    return value
