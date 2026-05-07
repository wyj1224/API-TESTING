import json
from typing import Any

from app.agent.llm_reflector import generate_reflection_with_optional_llm
from app.agent.workflow import FailedCase, RunSummary


def test_llm_reflector_accepts_valid_tool_call() -> None:
    summary = _failed_summary()

    def fake_reflection_client(payload: dict[str, Any]) -> dict[str, Any]:
        assert payload["tool_choice"]["function"]["name"] == "submit_reflection"
        assert payload["tools"][0]["function"]["name"] == "submit_reflection"
        return _tool_call_message(
            json.dumps(
                {
                    "key_findings": ["Login validation is returning server errors."],
                    "suspected_root_causes": ["Missing validation exception handling."],
                    "needs_more_tests": True,
                    "next_test_focus": ["validation"],
                    "recommended_next_action": "add_more_tests",
                    "reason": "The failed case suggests a broader validation issue.",
                }
            )
        )

    result = generate_reflection_with_optional_llm(
        summary=summary,
        enabled=True,
        reflection_client=fake_reflection_client,
    )

    assert result.used_llm is True
    assert result.reflection.needs_more_tests is True
    assert result.reflection.recommended_next_action == "add_more_tests"


def test_invalid_llm_reflection_falls_back() -> None:
    result = generate_reflection_with_optional_llm(
        summary=_failed_summary(),
        enabled=True,
        reflection_client=lambda _payload: {"role": "assistant", "content": "{}"},
    )

    assert result.used_llm is False
    assert "did not call submit_reflection" in str(result.fallback_reason)
    assert result.reflection.recommended_next_action == "finish_run"


def _failed_summary() -> RunSummary:
    return RunSummary(
        total=1,
        passed=0,
        failed=1,
        failed_cases=[
            FailedCase(
                case_id="login_missing_password",
                name="Login missing password",
                method="POST",
                path="/login",
                test_type="missing_required_field",
                expected_status=422,
                actual_status=500,
                errors=["Expected status 422, got 500."],
                diagnosis="Likely missing input validation or an unhandled exception.",
                diagnosis_rule="expected_422_got_500",
            )
        ],
    )


def _tool_call_message(arguments: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_reflect",
                "type": "function",
                "function": {
                    "name": "submit_reflection",
                    "arguments": arguments,
                },
            }
        ],
    }
