import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from apps.api.config import settings

logger = logging.getLogger(__name__)

# ── TTL configuration ────────────────────────────────────
JOB_TTL_HOURS = 48          # Delete completed/failed jobs older than this
STUCK_JOB_MINUTES = 30      # Mark active jobs stuck longer than this as failed


class SupabaseService:
    """
    Drop-in replacement for the in-memory job_store dict.
    All reads/writes go to Supabase pipeline_jobs table via REST API.
    No supabase-py SDK needed — plain httpx calls.
    """

    def __init__(self):
        self.url = settings.supabase_url.rstrip('/')
        self.key = settings.supabase_service_role_key
        self.table = "pipeline_jobs"

    @property
    def _headers(self) -> dict:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    @property
    def _base(self) -> str:
        return f"{self.url}/rest/v1/{self.table}"

    # ── Write operations ──────────────────────────────────

    async def create_job(self, job_id: str, story: Any, create_pr: bool = False, github_repo: Optional[str] = None) -> None:
        payload = {
            "job_id": job_id,
            "issue_key": story.issue_key if hasattr(story, 'issue_key') else story.get('issue_key'),
            "status": "running",
            "story": story.model_dump() if hasattr(story, 'model_dump') else story,
            "create_pr": create_pr,
            "github_repo": github_repo,
            "approve_path": "A",
            "edited_acs": None,
            "validator_result": None,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self._base, headers=self._headers, json=payload)
            if not response.is_success:
                raise RuntimeError(f"Supabase create_job failed: {response.status_code} {response.text}")
            logger.info(f"Supabase: created job {job_id}")

    async def update_job(self, job_id: str, **fields) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self._base}?job_id=eq.{job_id}",
                headers=self._headers,
                json=fields
            )
            if not response.is_success:
                raise RuntimeError(f"Supabase update_job failed: {response.status_code} {response.text}")
            logger.info(f"Supabase: updated job {job_id} fields={list(fields.keys())}")

    # ── Read operations ───────────────────────────────────

    async def get_job(self, job_id: str) -> Optional[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base}?job_id=eq.{job_id}&limit=1",
                headers=self._headers
            )
            if not response.is_success:
                raise RuntimeError(f"Supabase get_job failed: {response.status_code} {response.text}")
            rows = response.json()
            return rows[0] if rows else None

    async def job_exists(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        return job is not None

    # ── Convenience status helpers ────────────────────────

    async def set_status(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        fields = {"status": status}
        if error is not None:
            fields["error"] = error
        await self.update_job(job_id, **fields)

    async def set_audit_result(self, job_id: str, audit_result: dict) -> None:
        await self.update_job(job_id, audit_result=audit_result)

    async def set_architect_result(self, job_id: str, architect_result: dict) -> None:
        await self.update_job(job_id, architect_result=architect_result)

    async def set_coder_result(self, job_id: str, coder_result: dict) -> None:
        await self.update_job(job_id, coder_result=coder_result)

    async def get_active_job_for_issue(self, issue_key: str) -> Optional[dict]:
        """
        Returns the most recent non-failed, non-completed job for an issue_key.
        Used for deduplication — prevents two jobs running for the same story.
        Active statuses: running, awaiting_review, running_coder
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base}?issue_key=eq.{issue_key}"
                f"&status=in.(running,awaiting_review,running_coder)"
                f"&order=created_at.desc&limit=1",
                headers=self._headers
            )
            if not response.is_success:
                logger.warning(f"Supabase get_active_job_for_issue failed: {response.status_code}")
                return None
            rows = response.json()
            return rows[0] if rows else None

    # ── Job TTL / cleanup ─────────────────────────────────

    async def cleanup_stale_jobs(self) -> dict:
        """
        Two-phase cleanup:
          1. Stuck active jobs (running/awaiting_review/running_coder for >30 min)
             → mark as 'failed' with an error message so the UI can show it.
          2. Old terminal jobs (completed/failed older than 48 hours)
             → hard delete from Supabase to reclaim storage.
        Returns a summary dict with counts.
        """
        now = datetime.now(timezone.utc)
        stuck_cutoff = (now - timedelta(minutes=STUCK_JOB_MINUTES)).isoformat()
        ttl_cutoff = (now - timedelta(hours=JOB_TTL_HOURS)).isoformat()

        summary = {"stuck_failed": 0, "expired_deleted": 0, "errors": []}

        async with httpx.AsyncClient() as client:
            # Phase 1: Fail stuck active jobs
            try:
                resp = await client.patch(
                    f"{self._base}"
                    f"?status=in.(running,awaiting_review,running_coder)"
                    f"&created_at=lt.{stuck_cutoff}",
                    headers={**self._headers, "Prefer": "return=representation"},
                    json={
                        "status": "failed",
                        "error": f"Job expired — stuck for over {STUCK_JOB_MINUTES} minutes. Please re-run analysis."
                    }
                )
                if resp.is_success:
                    rows = resp.json()
                    summary["stuck_failed"] = len(rows) if isinstance(rows, list) else 0
                    if summary["stuck_failed"] > 0:
                        logger.info(f"TTL: marked {summary['stuck_failed']} stuck jobs as failed")
                else:
                    summary["errors"].append(f"Phase 1 failed: {resp.status_code}")
                    logger.warning(f"TTL cleanup phase 1 failed: {resp.status_code} {resp.text}")
            except Exception as e:
                summary["errors"].append(f"Phase 1 error: {str(e)}")
                logger.error(f"TTL cleanup phase 1 error: {e}")

            # Phase 2: Delete old terminal jobs
            try:
                resp = await client.delete(
                    f"{self._base}"
                    f"?status=in.(completed,failed)"
                    f"&created_at=lt.{ttl_cutoff}",
                    headers={**self._headers, "Prefer": "return=representation"},
                )
                if resp.is_success:
                    rows = resp.json()
                    summary["expired_deleted"] = len(rows) if isinstance(rows, list) else 0
                    if summary["expired_deleted"] > 0:
                        logger.info(f"TTL: deleted {summary['expired_deleted']} expired jobs (>{JOB_TTL_HOURS}h old)")
                else:
                    summary["errors"].append(f"Phase 2 failed: {resp.status_code}")
                    logger.warning(f"TTL cleanup phase 2 failed: {resp.status_code} {resp.text}")
            except Exception as e:
                summary["errors"].append(f"Phase 2 error: {str(e)}")
                logger.error(f"TTL cleanup phase 2 error: {e}")

        return summary


supabase_service = SupabaseService()