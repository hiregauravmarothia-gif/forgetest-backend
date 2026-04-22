from fastapi import APIRouter, HTTPException
from packages.schemas import JiraStory, AuditResponse
from packages.agents.auditor_agent import auditor_agent

router = APIRouter(prefix="/audit", tags=["audit"])


@router.post("", response_model=AuditResponse, status_code=200)
async def audit_story(story: JiraStory) -> AuditResponse:
    """
    Audit a Jira story against quality scenarios.
    
    Returns an AuditResponse with scenario results, scores, and flags.
    """
    try:
        result = await auditor_agent.audit(story)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse audit response: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal audit error: {str(e)}")