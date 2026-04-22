from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from packages.schemas.coder_schema import CoderResponse
from packages.schemas.architect_schema import ArchitectResponse
from packages.schemas.github_schema import PRResult
from packages.services.github import github_service

router = APIRouter(prefix="/github", tags=["github"])

class PRRequest(BaseModel):
    issue_key: str
    repo: str = "owner/repo"
    coder_response: CoderResponse
    architect_response: ArchitectResponse


@router.post("/pr", response_model=PRResult, status_code=201)
async def create_pr(request: PRRequest) -> PRResult:
    """
    Create a GitHub PR with generated Playwright tests.
    
    Takes CoderResponse files and ArchitectResponse details to create a branch and PR.
    """
    try:
        result = await github_service.create_pr(
            issue_key=request.issue_key,
            coder_response=request.coder_response,
            architect_response=request.architect_response,
            repo=request.repo,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create PR: {str(e)}")