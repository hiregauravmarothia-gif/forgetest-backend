from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class ACType(str, Enum):
    HAPPY = "HAPPY"
    SAD = "SAD"
    EDGE = "EDGE"
    SECURITY = "SECURITY"


class HiddenPaths(BaseModel):
    auth_permissions: list[str] = Field(default_factory=list, description="Auth & permissions hidden paths")
    input_boundaries: list[str] = Field(default_factory=list, description="Input boundary hidden paths")
    network_async: list[str] = Field(default_factory=list, description="Network & async hidden paths")
    data_state: list[str] = Field(default_factory=list, description="Data state hidden paths")
    ux_edge: list[str] = Field(default_factory=list, description="UX edge hidden paths")


class ProposedAC(BaseModel):
    id: str = Field(..., description="AC identifier (e.g., AC-1)")
    given: str = Field(..., description="Given precondition")
    when: str = Field(..., description="When action")
    then: str = Field(..., description="Then outcome")
    tag: ACType = Field(..., description="Tag: HAPPY, SAD, EDGE, or SECURITY")


class ArchitectResponse(BaseModel):
    issue_key: str = Field(..., description="The Jira issue key")
    hidden_paths: HiddenPaths = Field(..., description="Hidden paths discovered across 5 lenses")
    proposed_acs: list[ProposedAC] = Field(default_factory=list, description="Proposed acceptance criteria")
    gherkin: str = Field(..., description="Gherkin specification draft")
    assumptions: list[str] = Field(default_factory=list, description="List of assumptions made")
    timestamp: str = Field(..., description="ISO timestamp")