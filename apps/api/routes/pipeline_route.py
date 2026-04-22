import time
import logging
import uuid
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from packages.schemas.pipeline_schema import PipelineRequest, PipelineResponse
from packages.schemas import JiraStory
from packages.schemas.prescan_schema import PrescanResponse
from packages.schemas.architect_schema import ArchitectResponse, HiddenPaths
from packages.schemas.coder_schema import CoderResponse
from packages.agents import auditor_agent, architect_agent, coder_agent
from packages.services.github import github_service
from packages.services.supabase_service import supabase_service

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)


class JobStartResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    status: str
    audit: dict | None = None
    architect: dict | None = None
    coder: dict | None = None
    error: str | None = None


class ApproveResponse(BaseModel):
    job_id: str
    status: str
    files: list[dict]
    issue_key: str


async def run_pipeline_async(story: JiraStory, job_id: str):
    audit_response = None
    architect_response = None

    try:
        audit_response = await auditor_agent.audit(story)
    except Exception as e:
        error_msg = f"Audit failed: {str(e)}"
        await supabase_service.set_status(job_id, "failed", error=error_msg)
        return

    await supabase_service.set_audit_result(job_id, audit_response.model_dump())

    # Hard fail — stop pipeline
    if audit_response.hard_fail:
        await supabase_service.set_status(job_id, "failed", error=audit_response.hard_fail_reason)
        return

    score = audit_response.overall_score

    if score >= 0.7:
        await supabase_service.set_status(job_id, "completed")
    else:
        try:
            architect_response = await architect_agent.enrich(story, audit_response)
            await supabase_service.set_architect_result(job_id, architect_response.model_dump())
            await supabase_service.set_status(job_id, "awaiting_review")
        except Exception as e:
            error_msg = f"Architect failed: {str(e)}"
            await supabase_service.set_status(job_id, "failed", error=error_msg)


@router.post("/prescan", response_model=PrescanResponse, status_code=200)
async def prescan_story(request: PipelineRequest) -> PrescanResponse:
    from packages.agents.prescan_agent import prescan_agent
    return prescan_agent.prescan(request.story)


@router.post("/start", response_model=JobStartResponse)
async def start_pipeline(request: PipelineRequest) -> JobStartResponse:
    issue_key = request.story.issue_key

    # ── Deduplication check ───────────────────────────────
    # If an active job already exists for this issue_key, return it instead
    # of creating a new one. Prevents duplicate jobs from multiple tabs or
    # double-clicks.
    existing = await supabase_service.get_active_job_for_issue(issue_key)
    if existing:
        logger.info(f"Dedup: returning existing job {existing['job_id']} for issue {issue_key}")
        return JobStartResponse(job_id=existing["job_id"], status=existing["status"])

    job_id = str(uuid.uuid4())

    await supabase_service.create_job(
        job_id=job_id,
        story=request.story,
        create_pr=request.create_pr or False,
        github_repo=request.github_repo
    )

    asyncio.create_task(run_pipeline_async(request.story, job_id))

    return JobStartResponse(job_id=job_id, status="started")


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_pipeline_status(job_id: str) -> JobStatusResponse:
    job = await supabase_service.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        status=job["status"],
        audit=job.get("audit_result"),
        architect=job.get("architect_result"),
        coder=job.get("coder_result"),
        error=job.get("error")
    )


async def run_coder_async(job_id: str, story: JiraStory, architect_response: ArchitectResponse):
    try:
        coder_response = await coder_agent.generate(story, architect_response)
        await supabase_service.set_coder_result(job_id, coder_response.model_dump())
        await supabase_service.set_status(job_id, "completed")
        logger.info(f"Coder completed for job {job_id}")
    except Exception as e:
        error_msg = f"Coder failed: {str(e)}"
        await supabase_service.set_status(job_id, "failed", error=error_msg)
        logger.error(f"Coder failed for job {job_id}: {error_msg}")


@router.post("/{job_id}/approve", response_model=ApproveResponse)
async def approve_pipeline(job_id: str) -> ApproveResponse:
    job = await supabase_service.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "awaiting_review":
        raise HTTPException(status_code=400, detail="Job not in awaiting_review state")

    # Set status immediately before returning - acts as idempotency guard
    await supabase_service.set_status(job_id, "running_coder")

    story = JiraStory(**job["story"])
    architect_response = ArchitectResponse(**job["architect_result"])

    # Fire coder in background - Forge has a 25s resolver limit so we cannot await it
    asyncio.create_task(run_coder_async(job_id, story, architect_response))

    # Return immediately - frontend polls status for running_coder -> completed
    return ApproveResponse(
        job_id=job_id,
        status="running_coder",
        files=[],
        issue_key=story.issue_key
    )


@router.post("", response_model=PipelineResponse, status_code=200)
async def run_pipeline(request: PipelineRequest) -> PipelineResponse:
    """Synchronous full pipeline — legacy endpoint, kept for compatibility."""
    start_time = time.perf_counter()
    story = request.story
    error_msg = None
    pr_result = None

    audit_response = None
    architect_response = None
    coder_response = None
    pipeline_status = "COMPLETE"

    try:
        audit_response = await auditor_agent.audit(story)
    except Exception as e:
        error_msg = f"Audit failed: {str(e)}"
        return PipelineResponse(
            issue_key=story.issue_key,
            audit=None, architect=None, coder=None,
            pipeline_status="REJECTED",
            duration_ms=(time.perf_counter() - start_time) * 1000,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=error_msg, pr_result=None
        )

    score = audit_response.overall_score
    ts = datetime.now(timezone.utc).isoformat()

    if score >= 0.7:
        minimal_architect = ArchitectResponse(
            issue_key=story.issue_key,
            hidden_paths=HiddenPaths(),
            proposed_acs=[],
            gherkin="Feature: Auto-generated\n  Scenario: Pass-through",
            assumptions=[],
            timestamp=ts
        )
        try:
            coder_response = await coder_agent.generate(story, minimal_architect)
        except Exception as e:
            error_msg = f"Coder failed: {str(e)}"
    else:
        try:
            architect_response = await architect_agent.enrich(story, audit_response)
            coder_response = await coder_agent.generate(story, architect_response)
            if score < 0.4:
                pipeline_status = "ENRICHMENT_REQUIRED"
        except Exception as e:
            error_msg = f"Pipeline step failed: {str(e)}"
            if score < 0.7:
                pipeline_status = "ENRICHMENT_REQUIRED"

    if not coder_response and score >= 0.7:
        pipeline_status = "REJECTED"

    if request.create_pr and request.github_repo and coder_response and architect_response:
        try:
            pr_result = await github_service.create_pr(
                issue_key=story.issue_key,
                coder_response=coder_response,
                architect_response=architect_response,
                repo=request.github_repo,
            )
        except Exception as e:
            logger.warning(f"GitHub PR creation failed: {str(e)}")

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PipelineResponse(
        issue_key=story.issue_key,
        audit=audit_response,
        architect=architect_response,
        coder=coder_response,
        pipeline_status=pipeline_status,
        duration_ms=duration_ms,
        timestamp=ts,
        error=error_msg,
        pr_result=pr_result
    )