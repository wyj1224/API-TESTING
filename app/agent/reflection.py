from typing import Literal

from pydantic import BaseModel, Field


NextAction = Literal["finish_run", "add_more_tests"]


class AgentReflection(BaseModel):
    key_findings: list[str] = Field(default_factory=list)
    suspected_root_causes: list[str] = Field(default_factory=list)
    needs_more_tests: bool = False
    next_test_focus: list[str] = Field(default_factory=list)
    recommended_next_action: NextAction = "finish_run"
    reason: str
