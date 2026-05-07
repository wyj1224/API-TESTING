from fastapi import APIRouter, HTTPException, Response, status

from app.agent.workflow import RunRequest, RunResult, run_api_tests
from app.reports.generator import JsonReport, generate_json_report, generate_markdown_report


router = APIRouter(prefix="/runs", tags=["runs"])

_RUNS: dict[str, RunResult] = {}


@router.post("", response_model=RunResult)
def create_run(payload: RunRequest) -> RunResult:
    result = run_api_tests(payload)
    _RUNS[result.run_id] = result
    return result


@router.get("/{run_id}", response_model=RunResult)
def get_run(run_id: str) -> RunResult:
    return _get_run_or_404(run_id)


@router.get("/{run_id}/report.json", response_model=JsonReport)
def get_json_report(run_id: str) -> JsonReport:
    return generate_json_report(_get_run_or_404(run_id))


@router.get("/{run_id}/report.md")
def get_markdown_report(run_id: str) -> Response:
    return Response(
        content=generate_markdown_report(_get_run_or_404(run_id)),
        media_type="text/markdown; charset=utf-8",
    )


def _get_run_or_404(run_id: str) -> RunResult:
    result = _RUNS.get(run_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    return result
