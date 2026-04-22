from fastapi import APIRouter, HTTPException
from packages.schemas import JiraStory, AuditResponse
from packages.schemas.architect_schema import ArchitectResponse
from packages.agents.architect_agent import architect_agent

router = APIRouter(prefix="/enrich", tags=["enrich"])


@router.post("", response_model=ArchitectResponse, status_code=200)
async def enrich_story(story: JiraStory, audit: AuditResponse) -> ArchitectResponse:
    """
    Enrich a Jira story with hidden paths, proposed ACs, and Gherkin draft.
    
    Takes a JiraStory and its AuditResponse to generate comprehensive specifications.
    """
    try:
        result = await architect_agent.enrich(story, audit)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse enrich response: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal enrich error: {str(e)}")