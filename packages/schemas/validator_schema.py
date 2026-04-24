from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class ValidatorStatus(str, Enum):
    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ValidatorDimensions(BaseModel):
    coverage: float = Field(..., ge=0, le=1, description="% of ACs with corresponding tests (0-1)")
    balance: float = Field(..., ge=0, le=1, description="Happy/sad/edge ratio score (0-1)")
    redundancy: float = Field(..., ge=0, le=1, description="Absence of duplicate assertions (0-1)")
    fidelity: float = Field(..., ge=0, le=1, description="Test-to-AC semantic match (0-1)")


class ValidatorIssue(BaseModel):
    type: str = Field(..., description="Issue type: missing_ac, low_fidelity, duplicate, imbalanced")
    ac_id: Optional[str] = Field(None, description="AC identifier if applicable")
    suggestion: str = Field(..., description="Actionable fix suggestion")


class ValidatorResponse(BaseModel):
    issue_key: str = Field(..., description="Jira issue key")
    overall_score: float = Field(..., ge=0, le=1, description="Weighted overall score (0-1)")
    dimensions: ValidatorDimensions = Field(..., description="4-dimension breakdown")
    status: ValidatorStatus = Field(..., description="passed / needs_review / failed")
    issues: list[ValidatorIssue] = Field(default_factory=list, description="Actionable issues found")
    retry_count: int = Field(0, description="Number of retries so far")
    attempts_remaining: int = Field(2, description="Retries left before needs_review")
    path_used: str = Field("A", description="A = original ACs, B = user-edited ACs")
    timestamp: str = Field(..., description="ISO timestamp")
