from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent.workflow import RunResult


class ReportFailedCase(BaseModel):
    case_id: str
    name: str
    method: str
    path: str
    test_type: str
    expected_status: int
    actual_status: int | None
    errors: list[str]
    diagnosis: str
    diagnosis_rule: str | None = None


class ReportCase(BaseModel):
    case_id: str
    name: str
    method: str
    path: str
    test_type: str
    expected_status: int
    actual_status: int | None
    passed: bool | None
    latency_ms: float | None
    diagnosis: str | None = None


class ReportSummary(BaseModel):
    total: int
    passed: int
    failed: int
    failed_cases: list[ReportFailedCase] = Field(default_factory=list)


class JsonReport(BaseModel):
    run_id: str
    status: str
    created_at: datetime
    base_url: str
    openapi_url: str
    summary: ReportSummary
    cases: list[ReportCase]
    trace: dict[str, Any]


def generate_json_report(run_result: RunResult) -> JsonReport:
    return JsonReport(
        run_id=run_result.run_id,
        status=run_result.status,
        created_at=run_result.created_at,
        base_url=run_result.base_url,
        openapi_url=run_result.openapi_url,
        summary=ReportSummary(
            total=run_result.summary.total,
            passed=run_result.summary.passed,
            failed=run_result.summary.failed,
            failed_cases=[
                ReportFailedCase.model_validate(failed_case.model_dump())
                for failed_case in run_result.summary.failed_cases
            ],
        ),
        cases=[
            ReportCase(
                case_id=case_result.test_case.case_id,
                name=case_result.test_case.name,
                method=case_result.test_case.method.upper(),
                path=case_result.test_case.path,
                test_type=case_result.test_case.test_type,
                expected_status=case_result.test_case.expected_status,
                actual_status=(
                    case_result.execution.status_code
                    if case_result.execution is not None
                    else None
                ),
                passed=(
                    case_result.validation.passed
                    if case_result.validation is not None
                    else None
                ),
                latency_ms=(
                    case_result.execution.latency_ms
                    if case_result.execution is not None
                    else None
                ),
                diagnosis=(
                    case_result.diagnosis.message
                    if case_result.diagnosis is not None
                    else None
                ),
            )
            for case_result in run_result.cases
        ],
        trace=run_result.trace.model_dump(mode="json"),
    )


def generate_markdown_report(run_result: RunResult) -> str:
    report = generate_json_report(run_result)
    lines = [
        f"# APITestAgent Report: {report.run_id}",
        "",
        "## Summary",
        "",
        f"- Status: `{report.status}`",
        f"- Base URL: `{report.base_url}`",
        f"- OpenAPI URL: `{report.openapi_url}`",
        f"- Total tests: {report.summary.total}",
        f"- Passed: {report.summary.passed}",
        f"- Failed: {report.summary.failed}",
        "",
        "## Failed Cases",
        "",
    ]

    if report.summary.failed_cases:
        lines.extend(
            [
                "| Case | Endpoint | Expected | Actual | Diagnosis |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for failed_case in report.summary.failed_cases:
            endpoint = f"{failed_case.method} {failed_case.path}"
            actual = (
                str(failed_case.actual_status)
                if failed_case.actual_status is not None
                else "n/a"
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        _cell(failed_case.case_id),
                        _cell(endpoint),
                        str(failed_case.expected_status),
                        actual,
                        _cell(failed_case.diagnosis),
                    ]
                )
                + " |"
            )
    else:
        lines.append("No failed cases.")

    lines.extend(
        [
            "",
            "## Test Cases",
            "",
            "| Case | Endpoint | Type | Expected | Actual | Result | Latency |",
            "| --- | --- | --- | ---: | ---: | --- | ---: |",
        ]
    )
    for case in report.cases:
        actual = str(case.actual_status) if case.actual_status is not None else "n/a"
        latency = f"{case.latency_ms:.2f} ms" if case.latency_ms is not None else "n/a"
        result = "passed" if case.passed else "failed"
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(case.case_id),
                    _cell(f"{case.method} {case.path}"),
                    _cell(case.test_type),
                    str(case.expected_status),
                    actual,
                    result,
                    latency,
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Trace",
            "",
            "| Step | Status | Case | Observation |",
            "| --- | --- | --- | --- |",
        ]
    )
    for step in run_result.trace.steps:
        observation = step.observations[0].message if step.observations else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(step.type),
                    _cell(step.status),
                    _cell(step.case_id or ""),
                    _cell(observation),
                ]
            )
            + " |"
        )

    return "\n".join(lines) + "\n"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
