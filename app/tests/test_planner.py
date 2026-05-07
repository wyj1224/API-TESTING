from demo_apis.normal_shop_api.main import app as normal_shop_app

from app.agent.planner import generate_test_plan
from app.agent.schemas import TestCase
from app.openapi.parser import parse_openapi_schema


def test_planner_generates_login_test_cases() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    plan = generate_test_plan(parsed)

    login_cases = [
        test_case
        for test_case in plan.cases
        if test_case.path == "/login" and test_case.method == "post"
    ]
    assert {test_case.test_type for test_case in login_cases} == {
        "happy_path",
        "missing_required_field",
        "wrong_type",
    }
    assert _case_with_body(login_cases, "happy_path").body == {
        "email": "test_value",
        "password": "test_value",
    }
    assert _case_with_body(login_cases, "missing_required_field", "password").body == {
        "email": "test_value"
    }
    assert _case_with_body(login_cases, "wrong_type", "email").body == {
        "email": 123,
        "password": "test_value",
    }


def test_planner_generates_item_test_cases() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    plan = generate_test_plan(parsed)

    create_item_cases = [
        test_case
        for test_case in plan.cases
        if test_case.path == "/items" and test_case.method == "post"
    ]
    assert _case_with_body(create_item_cases, "happy_path").body == {
        "name": "test_value",
        "price": 9.99,
    }
    assert _case_with_body(create_item_cases, "missing_required_field", "price").body == {
        "name": "test_value"
    }
    assert _case_with_body(create_item_cases, "wrong_type", "price").body == {
        "name": "test_value",
        "price": "wrong_type",
    }

    read_item_cases = [
        test_case
        for test_case in plan.cases
        if test_case.path == "/items/{item_id}" and test_case.method == "get"
    ]
    not_found_case = next(
        test_case for test_case in read_item_cases if test_case.test_type == "not_found"
    )
    assert not_found_case.expected_status == 404
    assert not_found_case.path_params == {"item_id": 999999}


def test_planner_generates_unauthorized_case_for_secured_endpoint() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    plan = generate_test_plan(parsed)

    users_me_cases = [
        test_case
        for test_case in plan.cases
        if test_case.path == "/users/me" and test_case.method == "get"
    ]
    unauthorized_case = next(
        test_case
        for test_case in users_me_cases
        if test_case.test_type == "unauthorized_access"
    )
    assert unauthorized_case.expected_status == 401
    assert unauthorized_case.headers == {}


def test_generated_test_cases_are_valid_pydantic_objects() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    plan = generate_test_plan(parsed)

    assert plan.total_cases > 0
    for test_case in plan.cases:
        assert TestCase.model_validate(test_case.model_dump()) == test_case


def _case_with_body(
    cases: list[TestCase],
    test_type: str,
    field_name: str | None = None,
) -> TestCase:
    candidates = [test_case for test_case in cases if test_case.test_type == test_type]
    if field_name is None:
        return candidates[0]
    return next(test_case for test_case in candidates if field_name in test_case.case_id)
