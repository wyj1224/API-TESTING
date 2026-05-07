from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.agent.llm_reflector import generate_reflection_with_optional_llm
from app.agent.llm_planner import generate_test_plan_with_optional_llm
from app.agent.reflection import AgentReflection
from app.agent.workflow import (
    AgentTrace,
    FailedCase,
    Observation,
    RunRequest,
    RunResult,
    RunSummary,
    ToolCall,
    _add_step,
    _execute_and_validate_cases,
    _failed_case_from_result,
    _failed_run_result,
    _is_local_url,
    _load_schema,
    _parse_schema,
)
from app.openapi.loader import OpenAPILoadError
from app.core.config import get_settings


def run_api_agent_loop(request: RunRequest) -> RunResult:
    run_id = f"run_{uuid4().hex[:12]}"
    trace = AgentTrace(run_id=run_id)
    created_at = datetime.now(UTC)
    reflections: list[AgentReflection] = []

    if request.use_llm_planner and not get_settings().llm_api_key:
        _add_step(
            trace,
            "agent_init",
            "failed",
            observations=[
                Observation(
                    message="LLM API key is required for the agent loop."
                )
            ],
        )
        return RunResult(
            run_id=run_id,
            status="failed",
            created_at=created_at,
            base_url=request.base_url,
            openapi_url=request.openapi_url,
            summary=RunSummary(
                total=0,
                passed=0,
                failed=1,
                failed_cases=[
                    FailedCase(
                        case_id="missing_llm_api_key",
                        name="Configure LLM API key",
                        method="POST",
                        path="/runs",
                        test_type="happy_path",
                        expected_status=200,
                        actual_status=None,
                        errors=[
                            "Set DEEPSEEK_API_KEY or LLM_API_KEY in .env before using the LLM agent loop."
                        ],
                        diagnosis="The LLM agent loop requires a configured API key.",
                        diagnosis_rule="missing_llm_api_key",
                    )
                ],
            ),
            trace=trace,
            reflections=reflections,
        )

    try:
        raw_schema = _load_schema(request, trace)
        parsed_schema = _parse_schema(raw_schema, request, trace)

        _add_step(
            trace,
            "agent_plan",
            "success",
            observations=[
                Observation(
                    message="Agent entered Plan phase.",
                    data={"iteration": 1},
                )
            ],
        )
        planner_result = generate_test_plan_with_optional_llm(
            parsed_schema,
            test_types=request.test_types,
            enabled=True,
        )
        if not planner_result.used_llm:
            return _failed_agent_llm_result(
                run_id=run_id,
                created_at=created_at,
                request=request,
                trace=trace,
                case_id="llm_planner_failed",
                message=planner_result.fallback_reason
                or "LLM planner did not produce a usable tool call.",
            )
        test_plan = planner_result.plan
        if not _is_local_url(request.base_url) and not request.allow_mutation:
            test_plan = test_plan.model_copy(
                update={
                    "cases": [
                        test_case
                        for test_case in test_plan.cases
                        if test_case.method in {"get", "head", "options"}
                    ]
                }
            )
        _add_step(
            trace,
            "plan_tests",
            "success",
            tool_calls=[
                ToolCall(
                    name="submit_test_plan",
                    input={
                        "test_types": request.test_types,
                        "max_endpoints": request.max_endpoints,
                        "allow_mutation": request.allow_mutation,
                    },
                    output={
                        "case_count": len(test_plan.cases),
                        "used_llm": True,
                    },
                )
            ],
            observations=[
                Observation(
                    message="LLM submitted a validated test plan through function calling.",
                    data={"case_ids": [case.case_id for case in test_plan.cases]},
                )
            ],
        )

        _add_step(
            trace,
            "agent_action",
            "success",
            tool_calls=[
                ToolCall(
                    name="execute_test_cases",
                    input={"case_count": len(test_plan.cases)},
                )
            ],
            observations=[
                Observation(
                    message="Agent entered Action phase and delegated execution to backend tools."
                )
            ],
        )
        case_results = _execute_and_validate_cases(
            test_plan.cases,
            parsed_schema,
            request,
            trace,
        )
        failed_cases = [
            _failed_case_from_result(result)
            for result in case_results
            if result.validation is not None and not result.validation.passed
        ]
        summary = RunSummary(
            total=len(case_results),
            passed=len(case_results) - len(failed_cases),
            failed=len(failed_cases),
            failed_cases=failed_cases,
        )

        _add_step(
            trace,
            "agent_observe",
            "success",
            observations=[
                Observation(
                    message="Agent observed deterministic execution and validation results.",
                    data=_summary_observation(summary),
                )
            ],
        )

        reflection_result = generate_reflection_with_optional_llm(
            summary=summary,
            enabled=True,
        )
        if not reflection_result.used_llm:
            return _failed_agent_llm_result(
                run_id=run_id,
                created_at=created_at,
                request=request,
                trace=trace,
                case_id="llm_reflection_failed",
                message=reflection_result.fallback_reason
                or "LLM reflector did not produce a usable tool call.",
            )
        reflections.append(reflection_result.reflection)
        _add_step(
            trace,
            "agent_reflect",
            "success",
            tool_calls=[
                ToolCall(
                    name="submit_reflection",
                    input={"use_llm_planner": request.use_llm_planner},
                    output={
                        "used_llm": reflection_result.used_llm,
                        "fallback_reason": reflection_result.fallback_reason,
                        "recommended_next_action": (
                            reflection_result.reflection.recommended_next_action
                        ),
                    },
                )
            ],
            observations=[
                Observation(
                    message=reflection_result.reflection.reason,
                    data=reflection_result.reflection.model_dump(mode="json"),
                )
            ],
        )

        _add_step(
            trace,
            "agent_finish",
            "success",
            tool_calls=[
                ToolCall(
                    name="finish_run",
                    output={
                        "total": summary.total,
                        "passed": summary.passed,
                        "failed": summary.failed,
                    },
                )
            ],
            observations=[
                Observation(
                    message="Agent finished after Plan -> Action -> Observe -> Reflect."
                )
            ],
        )

        return RunResult(
            run_id=run_id,
            status="completed",
            created_at=created_at,
            base_url=request.base_url,
            openapi_url=request.openapi_url,
            summary=summary,
            cases=case_results,
            trace=trace,
            reflections=reflections,
        )
    except OpenAPILoadError as exc:
        _add_step(
            trace,
            "load_schema",
            "failed",
            observations=[Observation(message=str(exc))],
        )
        return _failed_run_result(run_id, created_at, request, trace, str(exc))


def _summary_observation(summary: RunSummary) -> dict[str, Any]:
    return {
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "failed_cases": [
            {
                "case_id": failed_case.case_id,
                "expected_status": failed_case.expected_status,
                "actual_status": failed_case.actual_status,
                "diagnosis": failed_case.diagnosis,
            }
            for failed_case in summary.failed_cases
        ],
    }


def _failed_agent_llm_result(
    *,
    run_id: str,
    created_at: datetime,
    request: RunRequest,
    trace: AgentTrace,
    case_id: str,
    message: str,
) -> RunResult:
    _add_step(
        trace,
        case_id,
        "failed",
        observations=[Observation(message=message)],
    )
    return RunResult(
        run_id=run_id,
        status="failed",
        created_at=created_at,
        base_url=request.base_url,
        openapi_url=request.openapi_url,
        summary=RunSummary(
            total=0,
            passed=0,
            failed=1,
            failed_cases=[
                FailedCase(
                    case_id=case_id,
                    name="LLM agent function calling",
                    method="POST",
                    path="/runs",
                    test_type="happy_path",
                    expected_status=200,
                    actual_status=None,
                    errors=[message],
                    diagnosis="The LLM agent loop requires successful function calling.",
                    diagnosis_rule=case_id,
                )
            ],
        ),
        trace=trace,
    )
