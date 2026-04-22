from pydantic import BaseModel, Field


class PRResult(BaseModel):
    pr_url: str = Field(..., description="URL of the created PR")
    branch_name: str = Field(..., description="Branch name created")
    files_committed: int = Field(..., description="Number of files committed")
    pr_number: int = Field(..., description="PR number")
    status: str = Field(..., description="PR status: OPEN, DRAFT")