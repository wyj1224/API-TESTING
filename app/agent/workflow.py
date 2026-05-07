from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent.reflection import AgentReflection
from app.agent.llm_planner import generate_test_plan_with_optional_llm
from app.agent.schemas import TestCase, TestType
from app.openapi.loader import OpenAPILoadError, load_openapi_schema
from app.openapi.models import EndpointDefinition, ParsedOpenAPISchema
from app.openapi.parser import parse_openapi_schema
from app.tools.diagnoser import DiagnosisResult, diagnose_failure
from app.tools.http_executor import HttpExecutionResult, execute_test_case
from app.tools.response_validator import ResponseValidationResult, validate_response


RunStatus = Literal["completed", "failed"]
StepStatus = Literal["success", "failed", "passed", "skipped"]


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentStep(BaseModel):
    type: str
    status: StepStatus
    case_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)


class AgentTrace(BaseModel):
    run_id: str
    steps: list[AgentStep] = Field(default_factory=list)


class RunRequest(BaseModel):
    base_url: str
    openapi_url: str
    max_endpoints: int | None = Field(default=None, ge=1)
    test_types: list[TestType] | None = None
    allow_mutation: bool = False
    use_llm_planner: bool = True
    use_agent_loop: bool = True
    max_agent_iterations: int = Field(default=1, ge=1, le=5)


class FailedCase(BaseModel):
    case_id: str
    name: str
    method: str
    path: str
    test_type: TestType
    expected_status: int
    actual_status: int | None = None
    errors: list[str]
    diagnosis: str
    diagnosis_rule: str | None = None


class ExecutedCaseResult(BaseModel):
    test_case: TestCase
    execution: HttpExecutionResult | None = None
    validation: ResponseValidationResult | None = None
    diagnosis: DiagnosisResult | None = None


class RunSummary(BaseModel):
    total: int
    passed: int
    failed: int
    failed_cases: list[FailedCase] = Field(default_factory=list)


class RunResult(BaseModel):
    run_id: str
    status: RunStatus
    created_at: datetime
    base_url: str
    openapi_url: str
    summary: RunSummary
    cases: list[ExecutedCaseResult] = Field(default_factory=list)
    trace: AgentTrace
    reflections: list[AgentReflection] = Field(default_factory=list)


def run_api_tests(request: RunRequest) -> RunResult:
    if request.use_agent_loop:
        from app.agent.loop import run_api_agent_loop

        return run_api_agent_loop(request)

    run_id = f"run_{uuid4().hex[:12]}"
    trace = AgentTrace(run_id=run_id)
    created_at = datetime.now(UTC)

    try:
        raw_schema = _load_schema(request, trace)
        parsed_schema = _parse_schema(raw_schema, request, trace)
        test_plan = _plan_tests(parsed_schema, request, trace)
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
            "generate_result",
            "success",
            observations=[
                Observation(
                    message="Generated final structured run result.",
                    data=summary.model_dump(),
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
        )
    except OpenAPILoadError as exc:
        _add_step(
            trace,
            "load_schema",
            "failed",
            observations=[Observation(message=str(exc))],
        )
        return _failed_run_result(run_id, created_at, request, trace, str(exc))


def _load_schema(request: RunRequest, trace: AgentTrace) -> dict[str, Any]:
    try:
        raw_schema = load_openapi_schema(openapi_url=request.openapi_url)
    except OpenAPILoadError:
        raise

    _add_step(
        trace,
        "load_schema",
        "success",
        tool_calls=[
            ToolCall(
                name="load_openapi_schema",
                input={"openapi_url": request.openapi_url},
                output={
                    "openapi_version": raw_schema.get("openapi") or raw_schema.get("swagger"),
                    "path_count": len(raw_schema.get("paths", {})),
                },
            )
        ],
        observations=[
            Observation(
                message="Loaded OpenAPI schema.",
                data={"source": request.openapi_url},
            )
        ],
    )
    return raw_schema


def _parse_schema(
    raw_schema: dict[str, Any],
    request: RunRequest,
    trace: AgentTrace,
) -> ParsedOpenAPISchema:
    parsed_schema = parse_openapi_schema(raw_schema)
    if request.max_endpoints is not None:
        parsed_schema = parsed_schema.model_copy(
            update={"endpoints": parsed_schema.endpoints[: request.max_endpoints]}
        )

    _add_step(
        trace,
        "parse_endpoints",
        "success",
        tool_calls=[
            ToolCall(
                name="parse_openapi_schema",
                output={
                    "title": parsed_schema.title,
                    "endpoint_count": len(parsed_schema.endpoints),
                },
            )
        ],
        observations=[
            Observation(
                message="Parsed endpoint definitions.",
                data={
                    "endpoints": [
                        {"method": endpoint.method, "path": endpoint.path}
                        for endpoint in parsed_schema.endpoints
                    ]
                },
            )
        ],
    )
    return parsed_schema


def _plan_tests(
    parsed_schema: ParsedOpenAPISchema,
    request: RunRequest,
    trace: AgentTrace,
):
    planner_result = generate_test_plan_with_optional_llm(
        parsed_schema,
        test_types=request.test_types,
        enabled=request.use_llm_planner,
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
                name="generate_test_plan",
                input={
                    "test_types": request.test_types,
                    "max_endpoints": request.max_endpoints,
                    "allow_mutation": request.allow_mutation,
                    "use_llm_planner": request.use_llm_planner,
                },
                output={
                    "case_count": len(test_plan.cases),
                    "used_llm": planner_result.used_llm,
                    "fallback_reason": planner_result.fallback_reason,
                },
            )
        ],
        observations=[
            Observation(
                message=(
                    "Generated LLM-assisted test plan."
                    if planner_result.used_llm
                    else "Generated deterministic test plan."
                ),
                data={
                    "case_ids": [test_case.case_id for test_case in test_plan.cases]
                },
            )
        ],
    )
    return test_plan


def _execute_and_validate_cases(
    test_cases: list[TestCase],
    parsed_schema: ParsedOpenAPISchema,
    request: RunRequest,
    trace: AgentTrace,
) -> list[ExecutedCaseResult]:
    results: list[ExecutedCaseResult] = []
    for test_case in test_cases:
        endpoint = _find_endpoint(parsed_schema, test_case)
        execution = execute_test_case(test_case, base_url=request.base_url)
        _add_step(
            trace,
            "execute_case",
            "failed" if execution.error_message else "success",
            case_id=test_case.case_id,
            tool_calls=[
                ToolCall(
                    name="execute_test_case",
                    input={
                        "method": test_case.method,
                        "path": test_case.path,
                        "expected_status": test_case.expected_status,
                    },
                    output={
                        "url": execution.url,
                        "status_code": execution.status_code,
                        "latency_ms": execution.latency_ms,
                        "error_message": execution.error_message,
                    },
                )
            ],
            observations=[
                Observation(
                    message="Observed HTTP response.",
                    data={
                        "status_code": execution.status_code,
                        "response_body": execution.response_body,
                    },
                )
            ],
        )

        validation = validate_response(
            test_case=test_case,
            execution=execution,
            endpoint=endpoint,
            parsed_schema=parsed_schema,
        )
        _add_step(
            trace,
            "validate_response",
            "passed" if validation.passed else "failed",
            case_id=test_case.case_id,
            tool_calls=[
                ToolCall(
                    name="validate_response",
                    output={
                        "passed": validation.passed,
                        "errors": validation.errors,
                    },
                )
            ],
        )

        diagnosis: DiagnosisResult | None = None
        if not validation.passed:
            diagnosis = diagnose_failure(
                test_case=test_case,
                execution=execution,
                validation=validation,
            )
            _add_step(
                trace,
                "diagnose_failure",
                "success",
                case_id=test_case.case_id,
                observations=[
                    Observation(
                        message="Diagnosed failed case using deterministic rules.",
                        data=diagnosis.model_dump(),
                    )
                ],
            )

        results.append(
            ExecutedCaseResult(
                test_case=test_case,
                execution=execution,
                validation=validation,
                diagnosis=diagnosis,
            )
        )
    return results


def _failed_case_from_result(result: ExecutedCaseResult) -> FailedCase:
    assert result.validation is not None
    assert result.execution is not None
    return FailedCase(
        case_id=result.test_case.case_id,
        name=result.test_case.name,
        method=result.test_case.method.upper(),
        path=result.test_case.path,
        test_type=result.test_case.test_type,
        expected_status=result.test_case.expected_status,
        actual_status=result.execution.status_code,
        errors=result.validation.errors,
        diagnosis=(
            result.diagnosis.message
            if result.diagnosis is not None
            else "No diagnosis was generated."
        ),
        diagnosis_rule=(
            result.diagnosis.matched_rule if result.diagnosis is not None else None
        ),
    )


def _find_endpoint(
    parsed_schema: ParsedOpenAPISchema,
    test_case: TestCase,
) -> EndpointDefinition:
    return next(
        endpoint
        for endpoint in parsed_schema.endpoints
        if endpoint.path == test_case.path and endpoint.method == test_case.method
    )


def _is_local_url(base_url: str) -> bool:
    return (
        base_url.startswith("http://localhost")
        or base_url.startswith("http://127.0.0.1")
        or base_url.startswith("http://0.0.0.0")
    )


def _failed_run_result(
    run_id: str,
    created_at: datetime,
    request: RunRequest,
    trace: AgentTrace,
    error_message: str,
) -> RunResult:
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
                    case_id="workflow_load_schema",
                    name="Load OpenAPI schema",
                    method="GET",
                    path=request.openapi_url,
                    test_type="happy_path",
                    expected_status=200,
                    actual_status=None,
                    errors=[error_message],
                    diagnosis="The OpenAPI schema could not be loaded.",
                    diagnosis_rule="schema_load_error",
                )
            ],
        ),
        trace=trace,
    )


def _add_step(
    trace: AgentTrace,
    step_type: str,
    status: StepStatus,
    *,
    case_id: str | None = None,
    tool_calls: list[ToolCall] | None = None,
    observations: list[Observation] | None = None,
) -> None:
    trace.steps.append(
        AgentStep(
            type=step_type,
            status=status,
            case_id=case_id,
            tool_calls=tool_calls or [],
            observations=observations or [],
        )
    )
