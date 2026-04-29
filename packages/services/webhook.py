import logging
import httpx
from apps.api.config import settings

logger = logging.getLogger(__name__)

class WebhookService:
    def __init__(self):
        self.webhook_url = settings.webhook_url
        if not self.webhook_url:
            logger.warning('WEBHOOK_URL not set — Generic webhook alerts disabled')

    async def send_alert(
        self,
        issue_key: str,
        score: float,
        title: str = None,
        job_id: str = None,
    ):
        if not self.webhook_url:
            return

        payload = {
            "event": "forgetest_low_score_alert",
            "issue_key": issue_key,
            "score": round(score * 100, 1),
            "title": title,
            "job_id": job_id,
            "message": f"ForgeTest detected low audit score ({round(score * 100)}%) for issue {issue_key}. Please review acceptance criteria.",
            "timestamp": httpx._utils.get_datetime_now().isoformat()
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Generic webhook alert sent for {issue_key} (score={score:.2f})")

webhook_service = WebhookService()