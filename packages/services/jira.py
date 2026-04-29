import logging
import base64
import httpx
from apps.api.config import settings

logger = logging.getLogger(__name__)

class JiraService:
    def __init__(self):
        self.base_url = settings.jira_base_url.rstrip('/') if settings.jira_base_url else None
        self.email = settings.jira_email
        self.token = settings.jira_token
        self.auth_header = None
        if self.email and self.token:
            auth_string = f"{self.email}:{self.token}"
            self.auth_header = f"Basic {base64.b64encode(auth_string.encode()).decode()}"
        if not self.auth_header:
            logger.warning('JIRA_EMAIL and/or JIRA_TOKEN not set — Jira alerts disabled')

    async def add_comment(self, issue_key: str, comment: str):
        if not self.auth_header or not self.base_url:
            return

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        payload = {"body": comment}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": self.auth_header, "Content-Type": "application/json"}
            )
            response.raise_for_status()
            logger.info(f"Jira comment added to {issue_key}")

jira_service = JiraService()