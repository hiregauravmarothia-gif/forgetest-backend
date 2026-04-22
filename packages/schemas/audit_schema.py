from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
# import statistics


class FlagType(str, Enum):
    IMPERATIVE_TRAP = "IMPERATIVE_TRAP"
    MISSING_BOUNDARY = "MISSING_BOUNDARY"
    AMBIGUOUS_OUTCOME = "AMBIGUOUS_OUTCOME"
    MISSING_GIVEN = "MISSING_GIVEN"
    FLAKE_RISK = "FLAKE_RISK"


class Severity(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"


class Flag(BaseModel):
    line: int = Field(..., description="Line number where flag was raised")
    type: FlagType = Field(..., description="Type of flag")
    severity: Severity = Field(..., description="Severity level")
    message: str = Field(..., description="Human-readable message")


class Verdict(str, Enum):
    PASS = "PASS"
    ENRICH = "ENRICH"
    REJECT = "REJECT"


class DimensionScores(BaseModel):
    clarity: float = Field(..., ge=0, le=1, description="Clarity score (0-1)")
    clarity_reason: str = Field(default="", description="Short reason for clarity score")

    completeness: float = Field(..., ge=0, le=1, description="Completeness score (0-1)")
    completeness_reason: str = Field(default="", description="Short reason for completeness score")

    testability: float = Field(..., ge=0, le=1, description="Testability score (0-1)")
    testability_reason: str = Field(default="", description="Short reason for testability score")

    edge_cases: float = Field(..., ge=0, le=1, description="Edge cases score (0-1)")
    edge_cases_reason: str = Field(default="", description="Short reason for edge_cases score")

    consistency: float = Field(..., ge=0, le=1, description="Consistency score (0-1)")
    consistency_reason: str = Field(default="", description="Short reason for consistency score")


class ScenarioResult(BaseModel):
    scenario: str = Field(..., description="Scenario identifier or name")
    score: float = Field(..., description="Score for this scenario (0-1)")
    verdict: Verdict = Field(..., description="Verdict: PASS, ENRICH, or REJECT")
    flags: list[Flag] = Field(default_factory=list, description="List of flags for this scenario")


class AuditResponse(BaseModel):
    issue_key: str = Field(..., description="The Jira issue key being audited")
    scenarios: list[ScenarioResult] = Field(..., description="Results for each scenario")
    overall_score: float = Field(..., ge=0, le=1, description="Weighted overall score (0-1)")
    dimensions: DimensionScores = Field(..., description="5-dimension breakdown scores")
    confidence: float = Field(..., ge=0, le=1, description="Confidence in scoring (0-1)")
    hard_fail: bool = Field(False, description="True if hard fail rules triggered")
    hard_fail_reason: Optional[str] = Field(None, description="Reason for hard fail if triggered")
    issues: list[str] = Field(default_factory=list, description="Top critical issues found")
    recommended_next_step: str = Field(default="", description="Actionable next step for the team")
    last_analyzed: str = Field(default="", description="Human-readable relative time, e.g. 'just now'")
    timestamp: str = Field(..., description="ISO timestamp of when audit was performed")