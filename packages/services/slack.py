import logging
import httpx
from apps.api.config import settings
from packages.services.jira import jira_service
from packages.services.webhook import webhook_service

logger = logging.getLogger(__name__)

class SlackService:
    def __init__(self):
        self.webhook_url = settings.slack_webhook_url
        if not self.webhook_url:
            logger.warning('SLACK_WEBHOOK_URL not set — Slack alerts disabled')

    async def send_low_score_alert(
        self,
        issue_key: str,
        score: float,
        title: str = None,
        job_id: str = None,
    ):
        if not self.webhook_url:
            return

        title_text = f"*{title}*\n" if title else ""
        issue_url = self._build_issue_url(issue_key)
        issue_link = f"<{issue_url}|{issue_key}>" if issue_url else issue_key

        payload = {
            "text": (
                f":warning: *ForgeTest Low Score Alert*\n"
                f"*Issue:* {issue_link}\n"
                f"*Score:* {round(score * 100)}%\n"
                f"{title_text}"
                f"*Job ID:* {job_id or 'N/A'}\n"
                "Please review the requirement and improve acceptance criteria before generating tests."
            )
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Slack alert sent for {issue_key} (score={score:.2f})")

        # Also add Jira comment
        comment = (
            f"*ForgeTest Low Score Alert*\n"
            f"*Score:* {round(score * 100)}%\n"
            f"*Job ID:* {job_id or 'N/A'}\n"
            "Please review the requirement and improve acceptance criteria before generating tests."
        )
        await jira_service.add_comment(issue_key, comment)

        # Also send generic webhook
        await webhook_service.send_alert(issue_key, score, title, job_id)

    def _build_issue_url(self, issue_key: str) -> str | None:
        if getattr(settings, 'jira_base_url', None):
            return f"{settings.jira_base_url.rstrip('/')}/browse/{issue_key}"
        return None

slack_service = SlackService()
