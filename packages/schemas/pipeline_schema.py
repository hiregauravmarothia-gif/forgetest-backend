from pydantic import BaseModel, Field
from packages.schemas import JiraStory, AuditResponse, ArchitectResponse
from packages.schemas.coder_schema import CoderResponse
from packages.schemas.github_schema import PRResult
from typing import Optional


class PipelineRequest(BaseModel):
    story: JiraStory = Field(..., description="The Jira story to process through the pipeline")
    github_repo: Optional[str] = Field(None, description="GitHub repo in 'owner/repo' format")
    create_pr: bool = Field(False, description="Whether to create a GitHub PR after generating tests")


class PipelineResponse(BaseModel):
    issue_key: str = Field(..., description="The Jira issue key")
    audit: Optional[AuditResponse] = Field(None, description="Audit response from Auditor Agent")
    architect: Optional[ArchitectResponse] = Field(None, description="Architect response from Architect Agent")
    coder: Optional[CoderResponse] = Field(None, description="Coder response from Coder Agent")
    pipeline_status: str = Field(..., description="Status: COMPLETE, ENRICHMENT_REQUIRED, or REJECTED")
    duration_ms: float = Field(..., description="Total pipeline duration in milliseconds")
    timestamp: str = Field(..., description="ISO timestamp")
    error: Optional[str] = Field(None, description="Error message if any step failed")
    pr_result: Optional[PRResult] = Field(None, description="GitHub PR result if create_pr=True")