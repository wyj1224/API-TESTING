from pydantic import BaseModel, Field

from app.agent.schemas import TestCase
from app.tools.http_executor import HttpExecutionResult
from app.tools.response_validator import ResponseValidationResult


class DiagnosisResult(BaseModel):
    message: str
    matched_rule: str
    details: list[str] = Field(default_factory=list)


def diagnose_failure(
    *,
    test_case: TestCase,
    execution: HttpExecutionResult,
    validation: ResponseValidationResult,
) -> DiagnosisResult:
    if execution.error_message:
        return DiagnosisResult(
            message="HTTP request failed before a response was received.",
            matched_rule="request_error",
            details=[execution.error_message],
        )

    actual_status = execution.status_code
    expected_status = test_case.expected_status

    if expected_status == 422 and actual_status == 500:
        return DiagnosisResult(
            message="Likely missing input validation or an unhandled exception.",
            matched_rule="expected_422_got_500",
            details=validation.errors,
        )
    if expected_status == 404 and actual_status == 200:
        return DiagnosisResult(
            message="Likely missing not-found handling.",
            matched_rule="expected_404_got_200",
            details=validation.errors,
        )
    if expected_status == 401 and actual_status == 500:
        return DiagnosisResult(
            message="Likely missing authentication error handling.",
            matched_rule="expected_401_got_500",
            details=validation.errors,
        )
    if expected_status == 409 and actual_status in {200, 201}:
        return DiagnosisResult(
            message="Likely duplicate resource handling is missing.",
            matched_rule=f"expected_409_got_{actual_status}",
            details=validation.errors,
        )
    if expected_status == 422 and actual_status in {200, 201}:
        return DiagnosisResult(
            message="The API accepted input that should have failed validation.",
            matched_rule=f"expected_422_got_{actual_status}",
            details=validation.errors,
        )

    return DiagnosisResult(
        message="Response did not match the expected API contract.",
        matched_rule="contract_mismatch",
        details=validation.errors,
    )
