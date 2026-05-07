from demo_apis.normal_shop_api.main import app as normal_shop_app

from app.openapi.parser import parse_openapi_schema


def test_parse_openapi_schema_returns_structured_endpoints() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    assert parsed.title == "Normal Shop API"
    assert parsed.openapi_version is not None
    assert len(parsed.endpoints) == 6


def test_parse_openapi_schema_extracts_operation_details() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    register = _find_endpoint(parsed, "/register", "post")
    assert register.operation_id == "register_register_post"
    assert register.request_body is not None
    assert "application/json" in register.request_body.content
    assert any(response.status_code == "201" for response in register.responses)

    read_item = _find_endpoint(parsed, "/items/{item_id}", "get")
    assert read_item.operation_id == "read_item_items__item_id__get"
    assert read_item.parameters[0].name == "item_id"
    assert read_item.parameters[0].location == "path"
    assert read_item.parameters[0].required is True

    users_me = _find_endpoint(parsed, "/users/me", "get")
    assert users_me.requires_auth is True
    assert users_me.security[0].schemes


def _find_endpoint(parsed, path: str, method: str):
    return next(
        endpoint
        for endpoint in parsed.endpoints
        if endpoint.path == path and endpoint.method == method
    )
