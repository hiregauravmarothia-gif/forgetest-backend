import logging
import httpx
from typing import Any, Optional
from apps.api.config import settings

logger = logging.getLogger(__name__)


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


supabase_service = SupabaseService()