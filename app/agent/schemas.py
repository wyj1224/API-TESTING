from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from app.openapi.models import HttpMethod


TestType = Literal[
    "happy_path",
    "missing_required_field",
    "wrong_type",
    "not_found",
    "unauthorized_access",
]


class TestCase(BaseModel):
    __test__: ClassVar[bool] = False

    case_id: str
    test_type: TestType
    path: str
    method: HttpMethod
    operation_id: str | None = None
    name: str
    expected_status: int
    path_params: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None


class TestPlan(BaseModel):
    __test__: ClassVar[bool] = False

    schema_title: str | None = None
    test_types: list[TestType]
    cases: list[TestCase]

    @property
    def total_cases(self) -> int:
        return len(self.cases)
