import json
from typing import Any

import httpx
from demo_apis.normal_shop_api.main import app as normal_shop_app

from app.agent.llm_planner import generate_test_plan_with_optional_llm
from app.agent.workflow import RunRequest, run_api_tests
from app.core.config import get_settings
from app.openapi.parser import parse_openapi_schema


def test_llm_planner_disabled_uses_deterministic_plan() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    result = generate_test_plan_with_optional_llm(parsed, enabled=False)

    assert result.used_llm is False
    assert result.fallback_reason is None
    assert result.plan.total_cases > 0


def test_llm_planner_enabled_accepts_valid_structured_json() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    def fake_completion(payload):
        assert payload["tool_choice"]["function"]["name"] == "submit_test_plan"
        assert payload["tools"][0]["function"]["name"] == "submit_test_plan"
        return _tool_call_message(
            _login_plan_arguments(
                name="Login with realistic sample credentials",
                body={
                    "email": "user@example.com",
                    "password": "correct-horse-battery-staple",
                },
            )
        )

    result = generate_test_plan_with_optional_llm(
        parsed,
        test_types=["happy_path"],
        enabled=True,
        completion_client=fake_completion,
    )

    assert result.used_llm is True
    assert result.plan.cases[0].name == "Login with realistic sample credentials"
    assert result.plan.cases[0].body == {
        "email": "user@example.com",
        "password": "correct-horse-battery-staple",
    }


def test_invalid_llm_output_falls_back_to_deterministic_plan() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    result = generate_test_plan_with_optional_llm(
        parsed,
        test_types=["happy_path"],
        enabled=True,
        completion_client=lambda _payload: _tool_call_message("not json"),
    )

    assert result.used_llm is False
    assert "invalid JSON" in str(result.fallback_reason)
    assert result.plan.total_cases > 0


def test_semantically_invalid_llm_output_falls_back() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    def fake_completion(_payload):
        return _tool_call_message(
            json.dumps(
                {
                    "schema_title": "Normal Shop API",
                    "test_types": ["happy_path"],
                    "cases": [
                        {
                            "case_id": "unknown_endpoint",
                            "test_type": "happy_path",
                            "path": "/does-not-exist",
                            "method": "get",
                            "operation_id": None,
                            "name": "Unknown endpoint",
                            "expected_status": 200,
                            "path_params": {},
                            "query_params": {},
                            "headers": {},
                            "body": None,
                        }
                    ],
                }
            )
        )

    result = generate_test_plan_with_optional_llm(
        parsed,
        test_types=["happy_path"],
        enabled=True,
        completion_client=fake_completion,
    )

    assert result.used_llm is False
    assert "unknown endpoint" in str(result.fallback_reason)


def test_llm_output_without_tool_call_falls_back() -> None:
    parsed = parse_openapi_schema(normal_shop_app.openapi())

    result = generate_test_plan_with_optional_llm(
        parsed,
        test_types=["happy_path"],
        enabled=True,
        completion_client=lambda _payload: {"role": "assistant", "content": "{}"},
    )

    assert result.used_llm is False
    assert "did not call submit_test_plan" in str(result.fallback_reason)


def test_workflow_with_llm_planner_enabled_without_key_falls_back(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return normal_shop_app.openapi()

    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: FakeResponse())

    result = run_api_tests(
        RunRequest(
            base_url="http://127.0.0.1:9",
            openapi_url="http://example.test/openapi.json",
            test_types=["happy_path"],
            use_llm_planner=True,
            use_agent_loop=False,
        )
    )

    assert result.status == "completed"
    plan_step = next(step for step in result.trace.steps if step.type == "plan_tests")
    assert plan_step.tool_calls[0].output["used_llm"] is False
    assert "LLM_API_KEY" in plan_step.tool_calls[0].output["fallback_reason"]
    get_settings.cache_clear()


def _tool_call_message(arguments: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "submit_test_plan",
                    "arguments": arguments,
                },
            }
        ],
    }


def _login_plan_arguments(
    *,
    name: str,
    body: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "schema_title": "Normal Shop API",
            "test_types": ["happy_path"],
            "cases": [
                {
                    "case_id": "llm_login_happy_path",
                    "test_type": "happy_path",
                    "path": "/login",
                    "method": "post",
                    "operation_id": "login_login_post",
                    "name": name,
                    "expected_status": 200,
                    "path_params": {},
                    "query_params": {},
                    "headers": {},
                    "body": body,
                }
            ],
        }
    )
