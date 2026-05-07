from app.agent.schemas import TestCase
from app.tools.diagnoser import diagnose_failure
from app.tools.http_executor import HttpExecutionResult
from app.tools.response_validator import ResponseValidationResult


def test_diagnoser_detects_expected_422_got_500() -> None:
    diagnosis = diagnose_failure(
        test_case=_case(expected_status=422),
        execution=_execution(status_code=500),
        validation=_validation(),
    )

    assert diagnosis.matched_rule == "expected_422_got_500"
    assert "input validation" in diagnosis.message


def test_diagnoser_detects_expected_404_got_200() -> None:
    diagnosis = diagnose_failure(
        test_case=_case(expected_status=404, test_type="not_found"),
        execution=_execution(status_code=200),
        validation=_validation(),
    )

    assert diagnosis.matched_rule == "expected_404_got_200"
    assert diagnosis.message == "Likely missing not-found handling."


def test_diagnoser_detects_expected_401_got_500() -> None:
    diagnosis = diagnose_failure(
        test_case=_case(expected_status=401, test_type="unauthorized_access"),
        execution=_execution(status_code=500),
        validation=_validation(),
    )

    assert diagnosis.matched_rule == "expected_401_got_500"
    assert "authentication" in diagnosis.message


def test_diagnoser_detects_expected_409_got_success() -> None:
    diagnosis = diagnose_failure(
        test_case=_case(expected_status=409),
        execution=_execution(status_code=200),
        validation=_validation(),
    )

    assert diagnosis.matched_rule == "expected_409_got_200"
    assert "duplicate resource" in diagnosis.message


def _case(
    *,
    expected_status: int,
    test_type="happy_path",
) -> TestCase:
    return TestCase(
        case_id="case",
        test_type=test_type,
        path="/example",
        method="get",
        name="Example",
        expected_status=expected_status,
    )


def _execution(*, status_code: int) -> HttpExecutionResult:
    return HttpExecutionResult(
        method="GET",
        url="http://example.test/example",
        status_code=status_code,
        latency_ms=1.0,
    )


def _validation() -> ResponseValidationResult:
    return ResponseValidationResult(
        passed=False,
        errors=["Expected status did not match."],
    )
