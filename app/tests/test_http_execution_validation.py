import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import httpx
import pytest

from app.agent.schemas import TestCase
from app.openapi.loader import load_openapi_schema
from app.openapi.models import EndpointDefinition, ParsedOpenAPISchema
from app.openapi.parser import parse_openapi_schema
from app.tools.http_executor import execute_test_case
from app.tools.response_validator import validate_response


@pytest.fixture
def normal_api_url() -> Iterator[str]:
    yield from _run_uvicorn("demo_apis.normal_shop_api.main:app")


@pytest.fixture
def buggy_api_url() -> Iterator[str]:
    yield from _run_uvicorn("demo_apis.buggy_shop_api.main:app")


def test_execute_and_validate_normal_shop_api_cases(normal_api_url: str) -> None:
    parsed = _load_parsed_schema(normal_api_url)

    create_item = TestCase(
        case_id="normal_create_item_happy_path",
        test_type="happy_path",
        path="/items",
        method="post",
        name="Create item",
        expected_status=201,
        headers={"Authorization": "Bearer should-not-leak"},
        body={"name": "test_value", "price": 9.99},
    )
    create_result = execute_test_case(create_item, base_url=normal_api_url)
    assert create_result.request_headers["Authorization"] == "[REDACTED]"
    assert create_result.status_code == 201
    assert create_result.latency_ms >= 0
    assert (
        validate_response(
            test_case=create_item,
            execution=create_result,
            endpoint=_endpoint(parsed, "/items", "post"),
            parsed_schema=parsed,
        ).passed
        is True
    )

    login_missing_password = TestCase(
        case_id="normal_login_missing_password",
        test_type="missing_required_field",
        path="/login",
        method="post",
        name="Login missing password",
        expected_status=422,
        body={"email": "normal@example.com"},
    )
    login_result = execute_test_case(login_missing_password, base_url=normal_api_url)
    validation = validate_response(
        test_case=login_missing_password,
        execution=login_result,
        endpoint=_endpoint(parsed, "/login", "post"),
        parsed_schema=parsed,
    )
    assert login_result.status_code == 422
    assert validation.passed is True


def test_known_buggy_shop_api_cases_are_detected_as_failures(buggy_api_url: str) -> None:
    parsed = _load_parsed_schema(buggy_api_url)

    cases = [
        TestCase(
            case_id="buggy_login_missing_password",
            test_type="missing_required_field",
            path="/login",
            method="post",
            name="Login missing password",
            expected_status=422,
            body={"email": "buggy@example.com"},
        ),
        TestCase(
            case_id="buggy_get_missing_item",
            test_type="not_found",
            path="/items/{item_id}",
            method="get",
            name="Get missing item",
            expected_status=404,
            path_params={"item_id": 999999},
        ),
        TestCase(
            case_id="buggy_create_item_negative_price",
            test_type="wrong_type",
            path="/items",
            method="post",
            name="Create item with negative price",
            expected_status=422,
            body={"name": "bad", "price": -1},
        ),
        TestCase(
            case_id="buggy_users_me_missing_token",
            test_type="unauthorized_access",
            path="/users/me",
            method="get",
            name="Users me missing token",
            expected_status=401,
        ),
    ]

    failures: dict[str, list[str]] = {}
    for test_case in cases:
        result = execute_test_case(test_case, base_url=buggy_api_url)
        validation = validate_response(
            test_case=test_case,
            execution=result,
            endpoint=_endpoint(parsed, test_case.path, test_case.method),
            parsed_schema=parsed,
        )
        assert validation.passed is False
        failures[test_case.case_id] = validation.errors

    assert failures == {
        "buggy_login_missing_password": ["Expected status 422, got 500."],
        "buggy_get_missing_item": ["Expected status 404, got 200."],
        "buggy_create_item_negative_price": ["Expected status 422, got 201."],
        "buggy_users_me_missing_token": ["Expected status 401, got 500."],
    }


def test_buggy_duplicate_registration_is_detected(buggy_api_url: str) -> None:
    parsed = _load_parsed_schema(buggy_api_url)
    email = "duplicate-detection@example.com"
    first_register = TestCase(
        case_id="buggy_register_first",
        test_type="happy_path",
        path="/register",
        method="post",
        name="First registration",
        expected_status=201,
        body={"email": email, "password": "secret"},
    )
    duplicate_register = TestCase(
        case_id="buggy_duplicate_registration",
        test_type="happy_path",
        path="/register",
        method="post",
        name="Duplicate registration",
        expected_status=409,
        body={"email": email, "password": "secret"},
    )

    first_result = execute_test_case(first_register, base_url=buggy_api_url)
    assert first_result.status_code == 201

    duplicate_result = execute_test_case(duplicate_register, base_url=buggy_api_url)
    validation = validate_response(
        test_case=duplicate_register,
        execution=duplicate_result,
        endpoint=_endpoint(parsed, "/register", "post"),
        parsed_schema=parsed,
    )

    assert duplicate_result.status_code == 201
    assert validation.passed is False
    assert validation.errors == ["Expected status 409, got 201."]


def _run_uvicorn(app_path: str) -> Iterator[str]:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            app_path,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until_ready(base_url)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(base_url: str) -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/openapi.json", timeout=0.5)
            if response.status_code == 200:
                return
        except httpx.RequestError:
            time.sleep(0.1)
    raise RuntimeError(f"Server did not become ready: {base_url}")


def _load_parsed_schema(base_url: str) -> ParsedOpenAPISchema:
    return parse_openapi_schema(
        load_openapi_schema(openapi_url=f"{base_url}/openapi.json")
    )


def _endpoint(
    parsed: ParsedOpenAPISchema,
    path: str,
    method: str,
) -> EndpointDefinition:
    return next(
        endpoint
        for endpoint in parsed.endpoints
        if endpoint.path == path and endpoint.method == method
    )
