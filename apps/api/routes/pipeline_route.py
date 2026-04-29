import time
import logging
import uuid
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from packages.schemas.pipeline_schema import PipelineRequest, PipelineResponse
from packages.schemas import JiraStory
from packages.schemas.prescan_schema import PrescanResponse
from packages.schemas.architect_schema import ArchitectResponse, HiddenPaths
from packages.schemas.coder_schema import CoderResponse
from packages.schemas.validator_schema import ValidatorStatus
from packages.agents import auditor_agent, architect_agent, coder_agent
from packages.agents.validator_agent import validator_agent
from packages.services.github import github_service
from packages.services.slack import slack_service
from packages.services.supabase_service import supabase_service
from apps.api.config import settings

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)

VALIDATOR_THRESHOLD = 0.75
MAX_RETRIES = 2


class JobStartResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    status: str
    audit: dict | None = None
    architect: dict | None = None
    coder: dict | None = None
    validator: dict | None = None
    pr_result: dict | None = None
    error: str | None = None


class ApproveRequest(BaseModel):
    path: str = "A"                          # "A" = original ACs, "B" = user-edited ACs
    edited_acs: Optional[list[dict]] = None  # Only used for Path B


class ApproveResponse(BaseModel):
    job_id: str
    status: str
    files: list[dict]
    issue_key: str


async def run_skip_audit_async(story: JiraStory, job_id: str):
    ts = datetime.now(timezone.utc).isoformat()
    skipped_audit = {
        "skipped": True, "overall_score": None,
        "last_analyzed": ts,
        "recommended_next_step": "Tests generated directly from Jira ACs."
    }
    await supabase_service.set_audit_result(job_id, skipped_audit)
    from packages.schemas.architect_schema import ProposedAC, ACType
    proposed_acs = []
    for i, ac_text in enumerate(story.acceptance_criteria or []):
        proposed_acs.append(ProposedAC(
            id=f"AC-{i+1}", given="the user has access to the feature",
            when=f"the action described in AC-{i+1} is performed",
            then=ac_text, tag=ACType.HAPPY
        ))
    minimal_architect = ArchitectResponse(
        issue_key=story.issue_key, hidden_paths=HiddenPaths(),
        proposed_acs=proposed_acs,
        gherkin=f"Feature: {story.title}\n  # Generated from {len(proposed_acs)} ACs",
        assumptions=["Tests generated directly from Jira ACs without AI enrichment."],
        timestamp=ts
    )
    await supabase_service.set_architect_result(job_id, minimal_architect.model_dump())
    await supabase_service.set_status(job_id, "running_coder")
    await run_coder_async(job_id=job_id, story=story,
        architect_response=minimal_architect, path="A", edited_acs=None)


async def run_pipeline_async(story: JiraStory, job_id: str):
    try:
        audit_response = await auditor_agent.audit(story)
    except Exception as e:
        await supabase_service.set_status(job_id, "failed", error=f"Audit failed: {str(e)}")
        return

    await supabase_service.set_audit_result(job_id, audit_response.model_dump())

    score = audit_response.overall_score or 0.0
    if score < 0.40:
        async def _notify_slack():
            try:
                await slack_service.send_low_score_alert(
                    issue_key=story.issue_key,
                    score=score,
                    title=story.title,
                    job_id=job_id,
                )
            except Exception as err:
                logger.warning(f"Slack alert failed for job {job_id}: {err}")

        asyncio.create_task(_notify_slack())

    if audit_response.hard_fail:
        await supabase_service.set_status(job_id, "failed", error=audit_response.hard_fail_reason)
        return

    score = audit_response.overall_score
    ts = datetime.now(timezone.utc).isoformat()

    # Always run architect to enrich ACs based on audit findings,
    # regardless of score. Score only determines UI verdict (PASS/ENRICH/REJECT).
    try:
        architect_response = await architect_agent.enrich(story, audit_response)
        await supabase_service.set_architect_result(job_id, architect_response.model_dump())
        await supabase_service.set_status(job_id, "awaiting_review")
    except Exception as e:
        await supabase_service.set_status(job_id, "failed", error=f"Architect failed: {str(e)}")


async def run_coder_async(
    job_id: str,
    story: JiraStory,
    architect_response: ArchitectResponse,
    path: str = "A",
    edited_acs: list[dict] | None = None
):
    retry_count = 0
    coder_response = None
    validator_feedback = None

    while retry_count <= MAX_RETRIES:
        try:
            # Generate tests — pass edited_acs and feedback on retries
            coder_response = await coder_agent.generate(
                story=story,
                architect_response=architect_response,
                edited_acs=edited_acs if path == "B" else None,
                validator_feedback=validator_feedback
            )
        except Exception as e:
            await supabase_service.set_status(job_id, "failed", error=f"Coder failed: {str(e)}")
            logger.error(f"Coder failed for job {job_id}: {str(e)}")
            return

        # Run Validator
        try:
            validator_response = await validator_agent.validate(
                story=story,
                architect_response=architect_response,
                coder_response=coder_response,
                edited_acs=edited_acs if path == "B" else None,
                retry_count=retry_count,
                path_used=path
            )
        except Exception as e:
            logger.warning(f"Validator failed for job {job_id}: {str(e)} — proceeding without validation")
            validator_response = None

        # Store latest coder + validator results
        await supabase_service.set_coder_result(job_id, coder_response.model_dump())
        if validator_response:
            await supabase_service.update_job(
                job_id,
                validator_result=validator_response.model_dump()
            )

        # Check if validator passed or we should retry
        if validator_response is None or validator_response.status == ValidatorStatus.PASSED:
            logger.info(f"Validator passed for job {job_id} on attempt {retry_count + 1}")
            break

        if retry_count >= MAX_RETRIES or validator_response.status == ValidatorStatus.NEEDS_REVIEW:
            logger.warning(
                f"Validator exhausted retries for job {job_id} "
                f"score={validator_response.overall_score:.2f} — committing best effort"
            )
            break

        # Build feedback for next Coder attempt
        validator_feedback = validator_agent.build_feedback_prompt(validator_response)
        retry_count += 1
        logger.info(f"Validator retry {retry_count}/{MAX_RETRIES} for job {job_id}")

    # GitHub PR creation — non-blocking
    pr_result = None
    try:
        pr_response = await github_service.create_pr(
            issue_key=story.issue_key,
            coder_response=coder_response,
            architect_response=architect_response,
            repo=settings.github_default_repo
        )
        pr_result = pr_response.model_dump()
        logger.info(f"PR created for job {job_id}: {pr_response.pr_url}")
    except Exception as pr_err:
        logger.warning(f"PR creation failed for job {job_id}: {str(pr_err)}")

    await supabase_service.update_job(job_id, pr_result=pr_result, status="completed")
    logger.info(f"Pipeline completed for job {job_id}")


@router.post("/prescan", response_model=PrescanResponse, status_code=200)
async def prescan_story(request: PipelineRequest) -> PrescanResponse:
    from packages.agents.prescan_agent import prescan_agent
    return prescan_agent.prescan(request.story)


@router.post("/start", response_model=JobStartResponse)
async def start_pipeline(request: PipelineRequest) -> JobStartResponse:
    issue_key = request.story.issue_key

    skip_audit = request.skip_audit

    # Dedup: only apply for full pipeline runs (not Path A direct generate)
    # Path A always creates a new job and cancels any existing one
    if not skip_audit:
        existing = await supabase_service.get_active_job_for_issue(issue_key)
        if existing:
            logger.info(f"Dedup: returning existing job {existing['job_id']} for issue {issue_key}")
            return JobStartResponse(job_id=existing["job_id"], status=existing["status"])
    else:
        # Path A — cancel any existing active job (awaiting_review etc.)
        existing = await supabase_service.get_active_job_for_issue(issue_key)
        if existing:
            logger.info(f"Path A: cancelling existing job {existing['job_id']} for issue {issue_key}")
            await supabase_service.set_status(
                existing['job_id'], "failed",
                error="Superseded by direct test generation (Path A)"
            )

    job_id = str(uuid.uuid4())
    await supabase_service.create_job(
        job_id=job_id,
        story=request.story,
        create_pr=request.create_pr or False,
        github_repo=request.github_repo
    )

    if skip_audit:
        asyncio.create_task(run_skip_audit_async(request.story, job_id))
    else:
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
        validator=job.get("validator_result"),
        pr_result=job.get("pr_result"),
        error=job.get("error")
    )


@router.post("/{job_id}/approve", response_model=ApproveResponse)
async def approve_pipeline(job_id: str, request: ApproveRequest = None) -> ApproveResponse:
    if request is None:
        request = ApproveRequest()

    job = await supabase_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "awaiting_review":
        raise HTTPException(status_code=400, detail="Job not in awaiting_review state")

    await supabase_service.set_status(job_id, "running_coder")

    story = JiraStory(**job["story"])

    # Handle case where architect_result is null (PASS stories)
    architect_data = job.get("architect_result")
    if architect_data:
        architect_response = ArchitectResponse(**architect_data)
    else:
        ts = datetime.now(timezone.utc).isoformat()
        architect_response = ArchitectResponse(
            issue_key=story.issue_key,
            hidden_paths=HiddenPaths(),
            proposed_acs=[],
            gherkin="Feature: Auto-generated\n  Scenario: Pass-through",
            assumptions=[],
            timestamp=ts
        )

    # Store path choice and edited ACs in job for reference
    await supabase_service.update_job(
        job_id,
        approve_path=request.path,
        edited_acs=request.edited_acs
    )

    # Fire coder + validator in background
    asyncio.create_task(run_coder_async(
        job_id=job_id,
        story=story,
        architect_response=architect_response,
        path=request.path,
        edited_acs=request.edited_acs
    ))

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
    architect_response = None
    coder_response = None
    pipeline_status = "COMPLETE"

    try:
        audit_response = await auditor_agent.audit(story)
    except Exception as e:
        return PipelineResponse(
            issue_key=story.issue_key,
            audit=None, architect=None, coder=None,
            pipeline_status="REJECTED",
            duration_ms=(time.perf_counter() - start_time) * 1000,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=f"Audit failed: {str(e)}", pr_result=None
        )

    score = audit_response.overall_score
    ts = datetime.now(timezone.utc).isoformat()

    # Always run architect to enrich ACs based on audit findings
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

    return PipelineResponse(
        issue_key=story.issue_key,
        audit=audit_response,
        architect=architect_response,
        coder=coder_response,
        pipeline_status=pipeline_status,
        duration_ms=(time.perf_counter() - start_time) * 1000,
        timestamp=ts,
        error=error_msg,
        pr_result=pr_result
    )