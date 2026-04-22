from pydantic import BaseModel, Field
from typing import Optional


class JiraStory(BaseModel):
    issue_key: str = Field(..., description="Jira issue key (e.g., PROJ-123)")
    title: str = Field(..., description="Title of the Jira story")
    description: str = Field(..., description="Full description of the story")
    acceptance_criteria: list[str] = Field(..., description="List of acceptance criteria items")
    epic_context: Optional[str] = Field(None, description="Optional epic context or parent story")