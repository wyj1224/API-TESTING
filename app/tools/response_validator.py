from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.agent.schemas import TestCase
from app.openapi.models import EndpointDefinition, ParsedOpenAPISchema, ResponseDefinition
from app.tools.http_executor import HttpExecutionResult


class ResponseValidationResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)


def validate_response(
    *,
    test_case: TestCase,
    execution: HttpExecutionResult,
    endpoint: EndpointDefinition,
    parsed_schema: ParsedOpenAPISchema,
) -> ResponseValidationResult:
    errors: list[str] = []

    if execution.error_message is not None:
        errors.append(f"Request failed: {execution.error_message}")
        return ResponseValidationResult(passed=False, errors=errors)

    if execution.status_code != test_case.expected_status:
        errors.append(
            "Expected status "
            f"{test_case.expected_status}, got {execution.status_code}."
        )

    expected_response = _find_response(endpoint, str(test_case.expected_status))
    if _expects_json(expected_response):
        if not execution.response_body_is_json:
            errors.append("Expected response body to be valid JSON.")
        elif execution.status_code == test_case.expected_status:
            errors.extend(
                _validate_required_fields(
                    execution.response_body,
                    expected_response,
                    parsed_schema,
                )
            )

    return ResponseValidationResult(passed=not errors, errors=errors)


def _find_response(
    endpoint: EndpointDefinition,
    status_code: str,
) -> ResponseDefinition | None:
    for response in endpoint.responses:
        if response.status_code == status_code:
            return response
    return None


def _expects_json(response: ResponseDefinition | None) -> bool:
    return response is not None and "application/json" in response.content


def _validate_required_fields(
    response_body: Any,
    response: ResponseDefinition | None,
    parsed_schema: ParsedOpenAPISchema,
) -> list[str]:
    if response is None:
        return []

    media = response.content.get("application/json")
    if not isinstance(media, Mapping):
        return []

    schema = _resolve_schema(media.get("schema"), parsed_schema)
    required_fields = _required_fields(schema)
    if not required_fields:
        return []

    if not isinstance(response_body, Mapping):
        return ["Expected JSON object response body."]

    errors: list[str] = []
    for field_name in required_fields:
        if field_name not in response_body:
            errors.append(f"Missing required response field: {field_name}.")
    return errors


def _resolve_schema(value: Any, parsed_schema: ParsedOpenAPISchema) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}

    ref = value.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(ref, parsed_schema.components)
        if resolved is not None:
            return resolved

    return dict(value)


def _resolve_ref(ref: str, components: Mapping[str, Any]) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None

    current: Any = {"components": components}
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]

    return dict(current) if isinstance(current, Mapping) else None


def _required_fields(schema: Mapping[str, Any]) -> list[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [field for field in required if isinstance(field, str)]
