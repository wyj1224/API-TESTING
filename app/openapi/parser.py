from collections.abc import Mapping
from typing import Any

from app.openapi.models import (
    EndpointDefinition,
    ParameterDefinition,
    ParsedOpenAPISchema,
    RequestBodyDefinition,
    ResponseDefinition,
    SecurityRequirement,
)


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def parse_openapi_schema(schema: Mapping[str, Any]) -> ParsedOpenAPISchema:
    info = _as_mapping(schema.get("info"))
    global_security = _parse_security(schema.get("security"))
    endpoints: list[EndpointDefinition] = []

    for path, path_item in _as_mapping(schema.get("paths")).items():
        if not isinstance(path, str) or not isinstance(path_item, Mapping):
            continue

        path_parameters = _parse_parameters(path_item.get("parameters"))
        for method, operation in path_item.items():
            method_lower = str(method).lower()
            if method_lower not in HTTP_METHODS or not isinstance(operation, Mapping):
                continue

            operation_security = _operation_security(operation, global_security)
            endpoint = EndpointDefinition(
                path=path,
                method=method_lower,
                operation_id=_optional_str(operation.get("operationId")),
                parameters=[
                    *path_parameters,
                    *_parse_parameters(operation.get("parameters")),
                ],
                request_body=_parse_request_body(operation.get("requestBody")),
                responses=_parse_responses(operation.get("responses")),
                security=operation_security,
                requires_auth=bool(operation_security),
            )
            endpoints.append(endpoint)

    return ParsedOpenAPISchema(
        title=_optional_str(info.get("title")),
        version=_optional_str(info.get("version")),
        openapi_version=_optional_str(schema.get("openapi") or schema.get("swagger")),
        components=dict(_as_mapping(schema.get("components"))),
        endpoints=endpoints,
    )


def _parse_parameters(value: Any) -> list[ParameterDefinition]:
    if not isinstance(value, list):
        return []

    parameters: list[ParameterDefinition] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        location = item.get("in")
        if location not in {"query", "path", "header", "cookie"}:
            continue
        parameters.append(
            ParameterDefinition.model_validate(
                {
                    "name": str(item.get("name", "")),
                    "in": location,
                    "required": bool(item.get("required", False)),
                    "schema": _as_optional_dict(item.get("schema")),
                    "description": _optional_str(item.get("description")),
                }
            )
        )
    return parameters


def _parse_request_body(value: Any) -> RequestBodyDefinition | None:
    if not isinstance(value, Mapping):
        return None
    return RequestBodyDefinition(
        required=bool(value.get("required", False)),
        content=_parse_content(value.get("content")),
    )


def _parse_responses(value: Any) -> list[ResponseDefinition]:
    if not isinstance(value, Mapping):
        return []

    responses: list[ResponseDefinition] = []
    for status_code, response in value.items():
        if not isinstance(response, Mapping):
            continue
        responses.append(
            ResponseDefinition(
                status_code=str(status_code),
                description=_optional_str(response.get("description")),
                content=_parse_content(response.get("content")),
            )
        )
    return responses


def _parse_content(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}

    content: dict[str, dict[str, Any]] = {}
    for media_type, media_details in value.items():
        if isinstance(media_type, str) and isinstance(media_details, Mapping):
            content[media_type] = dict(media_details)
    return content


def _operation_security(
    operation: Mapping[str, Any],
    global_security: list[SecurityRequirement],
) -> list[SecurityRequirement]:
    if "security" in operation:
        return _parse_security(operation.get("security"))
    return global_security


def _parse_security(value: Any) -> list[SecurityRequirement]:
    if not isinstance(value, list):
        return []

    requirements: list[SecurityRequirement] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        schemes: dict[str, list[str]] = {}
        for scheme_name, scopes in item.items():
            if isinstance(scheme_name, str):
                schemes[scheme_name] = scopes if isinstance(scopes, list) else []
        requirements.append(SecurityRequirement(schemes=schemes))
    return requirements


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_optional_dict(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
