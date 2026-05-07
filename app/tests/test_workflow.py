import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.workflow import RunRequest, run_api_tests
from app.api.runs import _RUNS
from app.main import app


@pytest.fixture
def buggy_api_url() -> Iterator[str]:
    yield from _run_uvicorn("demo_apis.buggy_shop_api.main:app")


def test_workflow_returns_trace_and_buggy_failures(buggy_api_url: str) -> None:
    result = run_api_tests(
        RunRequest(
            base_url=buggy_api_url,
            openapi_url=f"{buggy_api_url}/openapi.json",
            test_types=[
                "missing_required_field",
                "not_found",
                "unauthorized_access",
            ],
            allow_mutation=True,
            use_agent_loop=False,
            use_llm_planner=False,
        )
    )

    assert result.status == "completed"
    assert result.summary.total > 0
    assert result.summary.failed >= 3
    assert result.trace.run_id == result.run_id
    assert {"load_schema", "parse_endpoints", "plan_tests"} <= {
        step.type for step in result.trace.steps
    }
    assert any(step.type == "diagnose_failure" for step in result.trace.steps)

    failed_by_case = {
        failed_case.case_id: failed_case for failed_case in result.summary.failed_cases
    }
    assert (
        "login_login_post_missing_required_field_password"
        in failed_by_case
    )
    assert (
        "read_item_items__item_id__get_not_found"
        in failed_by_case
    )
    assert (
        "read_current_user_users_me_get_unauthorized_access"
        in failed_by_case
    )
    assert (
        failed_by_case[
            "login_login_post_missing_required_field_password"
        ].actual_status
        == 500
    )
    assert (
        failed_by_case[
            "read_item_items__item_id__get_not_found"
        ].diagnosis
        == "Likely missing not-found handling."
    )


def test_runs_endpoints_create_and_fetch_run(buggy_api_url: str) -> None:
    _RUNS.clear()
    client = TestClient(app)

    response = client.post(
        "/runs",
        json={
            "base_url": buggy_api_url,
            "openapi_url": f"{buggy_api_url}/openapi.json",
            "test_types": ["missing_required_field", "not_found"],
            "allow_mutation": True,
            "use_agent_loop": False,
            "use_llm_planner": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] in _RUNS
    assert payload["summary"]["failed"] >= 2
    assert len(payload["trace"]["steps"]) > 0

    get_response = client.get(f"/runs/{payload['run_id']}")

    assert get_response.status_code == 200
    assert get_response.json()["run_id"] == payload["run_id"]


def test_agent_loop_run_includes_plan_action_reflect_trace(
    buggy_api_url: str,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    from app.agent import llm_planner, llm_reflector
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        llm_planner,
        "_call_openai_compatible_chat",
        lambda _payload, _settings: _planner_tool_call_message(),
    )
    monkeypatch.setattr(
        llm_reflector,
        "_call_openai_compatible_chat",
        lambda _payload, _settings: _reflection_tool_call_message(),
    )

    result = run_api_tests(
        RunRequest(
            base_url=buggy_api_url,
            openapi_url=f"{buggy_api_url}/openapi.json",
            test_types=["missing_required_field", "not_found"],
            allow_mutation=True,
            use_agent_loop=True,
            use_llm_planner=True,
        )
    )

    step_types = [step.type for step in result.trace.steps]
    assert "agent_plan" in step_types
    assert "agent_action" in step_types
    assert "agent_observe" in step_types
    assert "agent_reflect" in step_types
    assert "agent_finish" in step_types
    assert result.reflections
    reflect_step = next(step for step in result.trace.steps if step.type == "agent_reflect")
    assert reflect_step.tool_calls[0].name == "submit_reflection"
    assert reflect_step.tool_calls[0].output["used_llm"] is True
    get_settings.cache_clear()


def test_get_missing_run_returns_404() -> None:
    _RUNS.clear()
    client = TestClient(app)

    response = client.get("/runs/run_missing")

    assert response.status_code == 404


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


def _planner_tool_call_message() -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_plan",
                "type": "function",
                "function": {
                    "name": "submit_test_plan",
                    "arguments": (
                        "{"
                        '"schema_title":"Buggy Shop API",'
                        '"test_types":["missing_required_field","not_found"],'
                        '"cases":['
                        '{"case_id":"llm_login_missing_password",'
                        '"test_type":"missing_required_field",'
                        '"path":"/login","method":"post",'
                        '"operation_id":"login_login_post",'
                        '"name":"LLM login missing password",'
                        '"expected_status":422,'
                        '"path_params":{},'
                        '"query_params":{},'
                        '"headers":{},'
                        '"body":{"email":"test@example.com"}},'
                        '{"case_id":"llm_missing_item",'
                        '"test_type":"not_found",'
                        '"path":"/items/{item_id}","method":"get",'
                        '"operation_id":"read_item_items__item_id__get",'
                        '"name":"LLM missing item",'
                        '"expected_status":404,'
                        '"path_params":{"item_id":999999},'
                        '"query_params":{},'
                        '"headers":{},'
                        '"body":null}'
                        "]}"
                    ),
                },
            }
        ],
    }


def _reflection_tool_call_message() -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_reflect",
                "type": "function",
                "function": {
                    "name": "submit_reflection",
                    "arguments": (
                        "{"
                        '"key_findings":["Buggy API violates validation and not-found contracts."],'
                        '"suspected_root_causes":["Missing validation and not-found handling."],'
                        '"needs_more_tests":false,'
                        '"next_test_focus":["validation","not_found"],'
                        '"recommended_next_action":"finish_run",'
                        '"reason":"The observed failures are clear enough to finish the run."'
                        "}"
                    ),
                },
            }
        ],
    }
