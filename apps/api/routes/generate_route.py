from fastapi import APIRouter, HTTPException
from packages.schemas import JiraStory
from packages.schemas.architect_schema import ArchitectResponse
from packages.schemas.coder_schema import CoderResponse
from packages.agents.coder_agent import coder_agent

router = APIRouter(prefix="/generate", tags=["generate"])


@router.post("", response_model=CoderResponse, status_code=200)
async def generate_tests(story: JiraStory, architect_response: ArchitectResponse) -> CoderResponse:
    """
    Generate Playwright TypeScript tests from Gherkin specification.
    
    Takes a JiraStory and its ArchitectResponse to generate test files.
    """
    try:
        result = await coder_agent.generate(story, architect_response)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse generate response: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal generate error: {str(e)}")