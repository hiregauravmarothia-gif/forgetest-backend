from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class PrescanSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PrescanIssue(BaseModel):
    code: str = Field(..., description="Issue code e.g. NO_AC, VAGUE_DESC")
    message: str = Field(..., description="Short human-readable message (max 8 words)")


class PrescanResponse(BaseModel):
    issue_key: str = Field(..., description="Jira issue key")
    issue_count: int = Field(..., description="Total number of issues found")
    severity: PrescanSeverity = Field(..., description="Severity: LOW, MEDIUM, HIGH")
    issues: list[PrescanIssue] = Field(default_factory=list, description="List of issues found")
    passed: bool = Field(..., description="True if no issues found")
    timestamp: str = Field(..., description="ISO timestamp")