from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.agent.schemas import TestCase, TestPlan, TestType
from app.openapi.models import EndpointDefinition, ParameterDefinition, ParsedOpenAPISchema


DEFAULT_TEST_TYPES: list[TestType] = [
    "happy_path",
    "missing_required_field",
    "wrong_type",
    "not_found",
    "unauthorized_access",
]


def generate_test_plan(
    parsed_schema: ParsedOpenAPISchema,
    test_types: list[TestType] | None = None,
) -> TestPlan:
    selected_test_types = test_types or DEFAULT_TEST_TYPES
    cases: list[TestCase] = []

    for endpoint in parsed_schema.endpoints:
        if "happy_path" in selected_test_types:
            cases.append(_build_happy_path_case(endpoint, parsed_schema))
        if "missing_required_field" in selected_test_types:
            cases.extend(_build_missing_required_field_cases(endpoint, parsed_schema))
        if "wrong_type" in selected_test_types:
            cases.extend(_build_wrong_type_cases(endpoint, parsed_schema))
        if "not_found" in selected_test_types:
            cases.extend(_build_not_found_cases(endpoint))
        if "unauthorized_access" in selected_test_types:
            unauthorized_case = _build_unauthorized_access_case(endpoint, parsed_schema)
            if unauthorized_case is not None:
                cases.append(unauthorized_case)

    return TestPlan(
        schema_title=parsed_schema.title,
        test_types=selected_test_types,
        cases=cases,
    )


def _build_happy_path_case(
    endpoint: EndpointDefinition,
    parsed_schema: ParsedOpenAPISchema,
) -> TestCase:
    return TestCase(
        case_id=_case_id(endpoint, "happy_path"),
        test_type="happy_path",
        path=endpoint.path,
        method=endpoint.method,
        operation_id=endpoint.operation_id,
        name=f"{endpoint.method.upper()} {endpoint.path} happy path",
        expected_status=_first_success_status(endpoint),
        path_params=_example_parameters(endpoint, "path", not_found=False),
        query_params=_example_parameters(endpoint, "query", not_found=False),
        headers=_auth_headers(endpoint),
        body=_example_request_body(endpoint, parsed_schema),
    )


def _build_missing_required_field_cases(
    endpoint: EndpointDefinition,
    parsed_schema: ParsedOpenAPISchema,
) -> list[TestCase]:
    schema = _request_json_schema(endpoint, parsed_schema)
    required_fields = _required_fields(schema)
    if not required_fields:
        return []

    base_body = _example_from_schema(schema, parsed_schema)
    if not isinstance(base_body, dict):
        return []

    cases: list[TestCase] = []
    for field_name in required_fields:
        body = deepcopy(base_body)
        body.pop(field_name, None)
        cases.append(
            TestCase(
                case_id=_case_id(endpoint, "missing_required_field", field_name),
                test_type="missing_required_field",
                path=endpoint.path,
                method=endpoint.method,
                operation_id=endpoint.operation_id,
                name=(
                    f"{endpoint.method.upper()} {endpoint.path} missing "
                    f"required field {field_name}"
                ),
                expected_status=422,
                path_params=_example_parameters(endpoint, "path", not_found=False),
                query_params=_example_parameters(endpoint, "query", not_found=False),
                headers=_auth_headers(endpoint),
                body=body,
            )
        )
    return cases


def _build_wrong_type_cases(
    endpoint: EndpointDefinition,
    parsed_schema: ParsedOpenAPISchema,
) -> list[TestCase]:
    schema = _request_json_schema(endpoint, parsed_schema)
    properties = _properties(schema)
    if not properties:
        return []

    base_body = _example_from_schema(schema, parsed_schema)
    if not isinstance(base_body, dict):
        return []

    cases: list[TestCase] = []
    for field_name, field_schema in properties.items():
        body = deepcopy(base_body)
        body[field_name] = _wrong_type_value(field_schema, parsed_schema)
        cases.append(
            TestCase(
                case_id=_case_id(endpoint, "wrong_type", field_name),
                test_type="wrong_type",
                path=endpoint.path,
                method=endpoint.method,
                operation_id=endpoint.operation_id,
                name=f"{endpoint.method.upper()} {endpoint.path} wrong type for {field_name}",
                expected_status=422,
                path_params=_example_parameters(endpoint, "path", not_found=False),
                query_params=_example_parameters(endpoint, "query", not_found=False),
                headers=_auth_headers(endpoint),
                body=body,
            )
        )
    return cases


def _build_not_found_cases(endpoint: EndpointDefinition) -> list[TestCase]:
    path_parameters = [parameter for parameter in endpoint.parameters if parameter.location == "path"]
    if not path_parameters:
        return []

    return [
        TestCase(
            case_id=_case_id(endpoint, "not_found"),
            test_type="not_found",
            path=endpoint.path,
            method=endpoint.method,
            operation_id=endpoint.operation_id,
            name=f"{endpoint.method.upper()} {endpoint.path} not found",
            expected_status=404,
            path_params=_example_parameters(endpoint, "path", not_found=True),
            query_params=_example_parameters(endpoint, "query", not_found=False),
            headers=_auth_headers(endpoint),
            body=None,
        )
    ]


def _build_unauthorized_access_case(
    endpoint: EndpointDefinition,
    parsed_schema: ParsedOpenAPISchema,
) -> TestCase | None:
    if not endpoint.requires_auth:
        return None

    return TestCase(
        case_id=_case_id(endpoint, "unauthorized_access"),
        test_type="unauthorized_access",
        path=endpoint.path,
        method=endpoint.method,
        operation_id=endpoint.operation_id,
        name=f"{endpoint.method.upper()} {endpoint.path} unauthorized access",
        expected_status=401,
        path_params=_example_parameters(endpoint, "path", not_found=False),
        query_params=_example_parameters(endpoint, "query", not_found=False),
        headers={},
        body=_example_request_body(endpoint, parsed_schema),
    )


def _example_request_body(
    endpoint: EndpointDefinition,
    parsed_schema: ParsedOpenAPISchema,
) -> dict[str, Any] | None:
    schema = _request_json_schema(endpoint, parsed_schema)
    example = _example_from_schema(schema, parsed_schema)
    return example if isinstance(example, dict) else None


def _request_json_schema(
    endpoint: EndpointDefinition,
    parsed_schema: ParsedOpenAPISchema,
) -> dict[str, Any]:
    if endpoint.request_body is None:
        return {}
    media = endpoint.request_body.content.get("application/json")
    if not isinstance(media, Mapping):
        return {}
    return _resolve_schema(media.get("schema"), parsed_schema)


def _example_from_schema(schema: Mapping[str, Any], parsed_schema: ParsedOpenAPISchema) -> Any:
    resolved_schema = _resolve_schema(schema, parsed_schema)
    schema_type = _schema_type(resolved_schema)

    if "enum" in resolved_schema and isinstance(resolved_schema["enum"], list):
        return resolved_schema["enum"][0]
    if schema_type == "object":
        return {
            name: _example_from_schema(property_schema, parsed_schema)
            for name, property_schema in _properties(resolved_schema).items()
        }
    if schema_type == "array":
        items_schema = _resolve_schema(resolved_schema.get("items"), parsed_schema)
        return [_example_from_schema(items_schema, parsed_schema)]
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 9.99
    if schema_type == "boolean":
        return True
    return "test_value"


def _wrong_type_value(schema: Mapping[str, Any], parsed_schema: ParsedOpenAPISchema) -> Any:
    schema_type = _schema_type(_resolve_schema(schema, parsed_schema))
    if schema_type == "string":
        return 123
    if schema_type in {"integer", "number"}:
        return "wrong_type"
    if schema_type == "boolean":
        return "wrong_type"
    if schema_type == "array":
        return "wrong_type"
    if schema_type == "object":
        return "wrong_type"
    return None


def _example_parameters(
    endpoint: EndpointDefinition,
    location: str,
    *,
    not_found: bool,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for parameter in endpoint.parameters:
        if parameter.location != location:
            continue
        values[parameter.name] = _example_parameter_value(parameter, not_found=not_found)
    return values


def _example_parameter_value(parameter: ParameterDefinition, *, not_found: bool) -> Any:
    schema = parameter.schema_ or {}
    schema_type = _schema_type(schema)
    if not_found and parameter.location == "path":
        return 999999 if schema_type in {"integer", "number"} else "missing-test-value"
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 9.99
    if schema_type == "boolean":
        return True
    return "test_value"


def _auth_headers(endpoint: EndpointDefinition) -> dict[str, str]:
    if not endpoint.requires_auth:
        return {}
    return {"Authorization": "Bearer test_token"}


def _first_success_status(endpoint: EndpointDefinition) -> int:
    for response in endpoint.responses:
        if response.status_code.isdigit() and 200 <= int(response.status_code) < 300:
            return int(response.status_code)
    return 200


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


def _schema_type(schema: Mapping[str, Any]) -> str:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type
    if "properties" in schema:
        return "object"
    return "string"


def _properties(schema: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for name, property_schema in properties.items():
        if isinstance(name, str) and isinstance(property_schema, Mapping):
            result[name] = dict(property_schema)
    return result


def _required_fields(schema: Mapping[str, Any]) -> list[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [field for field in required if isinstance(field, str)]


def _case_id(endpoint: EndpointDefinition, test_type: TestType, field_name: str | None = None) -> str:
    operation = endpoint.operation_id or f"{endpoint.method}_{endpoint.path}"
    slug = "".join(char if char.isalnum() else "_" for char in operation).strip("_")
    parts = [slug.lower(), test_type]
    if field_name:
        field_slug = "".join(char if char.isalnum() else "_" for char in field_name).strip("_")
        parts.append(field_slug.lower())
    return "_".join(parts)
