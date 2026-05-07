from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.agent.schemas import TestCase
from app.agent.workflow import (
    AgentTrace,
    ExecutedCaseResult,
    FailedCase,
    RunResult,
    RunSummary,
)
from app.api.runs import _RUNS
from app.main import app
from app.reports.generator import generate_json_report, generate_markdown_report
from app.tools.diagnoser import DiagnosisResult
from app.tools.http_executor import HttpExecutionResult
from app.tools.response_validator import ResponseValidationResult


def test_generate_json_report_is_structured() -> None:
    run_result = _sample_run_result()

    report = generate_json_report(run_result)

    assert report.run_id == "run_report"
    assert report.summary.failed == 1
    assert report.summary.failed_cases[0].diagnosis_rule == "expected_422_got_500"
    assert report.cases[0].passed is False
    assert report.trace["run_id"] == "run_report"


def test_generate_markdown_report_is_readable() -> None:
    markdown = generate_markdown_report(_sample_run_result())

    assert "# APITestAgent Report: run_report" in markdown
    assert "## Summary" in markdown
    assert "## Failed Cases" in markdown
    assert "Likely missing input validation" in markdown
    assert "| Case | Endpoint | Expected | Actual | Diagnosis |" in markdown


def test_report_endpoints_return_json_and_markdown() -> None:
    _RUNS.clear()
    _RUNS["run_report"] = _sample_run_result()
    client = TestClient(app)

    json_response = client.get("/runs/run_report/report.json")
    markdown_response = client.get("/runs/run_report/report.md")

    assert json_response.status_code == 200
    assert json_response.json()["summary"]["failed"] == 1
    assert markdown_response.status_code == 200
    assert "text/markdown" in markdown_response.headers["content-type"]
    assert "# APITestAgent Report: run_report" in markdown_response.text


def _sample_run_result() -> RunResult:
    test_case = TestCase(
        case_id="login_missing_password",
        test_type="missing_required_field",
        path="/login",
        method="post",
        name="Login missing password",
        expected_status=422,
        body={"email": "test@example.com"},
    )
    execution = HttpExecutionResult(
        method="POST",
        url="http://example.test/login",
        request_body=test_case.body,
        status_code=500,
        response_body={"detail": "crashed"},
        response_body_is_json=True,
        latency_ms=2.5,
    )
    validation = ResponseValidationResult(
        passed=False,
        errors=["Expected status 422, got 500."],
    )
    diagnosis = DiagnosisResult(
        message="Likely missing input validation or an unhandled exception.",
        matched_rule="expected_422_got_500",
        details=validation.errors,
    )
    return RunResult(
        run_id="run_report",
        status="completed",
        created_at=datetime.now(UTC),
        base_url="http://example.test",
        openapi_url="http://example.test/openapi.json",
        summary=RunSummary(
            total=1,
            passed=0,
            failed=1,
            failed_cases=[
                FailedCase(
                    case_id=test_case.case_id,
                    name=test_case.name,
                    method="POST",
                    path=test_case.path,
                    test_type=test_case.test_type,
                    expected_status=422,
                    actual_status=500,
                    errors=validation.errors,
                    diagnosis=diagnosis.message,
                    diagnosis_rule=diagnosis.matched_rule,
                )
            ],
        ),
        cases=[
            ExecutedCaseResult(
                test_case=test_case,
                execution=execution,
                validation=validation,
                diagnosis=diagnosis,
            )
        ],
        trace=AgentTrace(run_id="run_report"),
        reflections=[],
    )
