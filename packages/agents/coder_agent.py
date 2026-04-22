import json
import logging
from datetime import datetime, timezone
from packages.schemas import JiraStory
from packages.schemas.architect_schema import ArchitectResponse
from packages.schemas.coder_schema import CoderResponse, GeneratedFile, CoderManifest, ManifestCoverage, FileType
from packages.services.llm import llm_service

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Write Playwright TS tests. Return ONLY this exact JSON structure:
{
  "files": [
    {"type": "page_object", "path": "e2e/pages/LoginPage.ts", "content": "..."},
    {"type": "spec", "path": "e2e/specs/login.spec.ts", "content": "..."}
  ],
  "manifest": {
    "jira_context": {"issue_key": ""},
    "coverage": [{"scenario_tag": "@ac-1", "status": "GENERATED", "output_file": "e2e/specs/login.spec.ts"}],
    "locator_inventory": {"loginButton": "data-testid='login-btn'"},
    "assumptions_used": []
  },
  "locator_gaps": [],
  "skipped_scenarios": []
}

Laws: 1) data-testid/role locators only, else // ⚠ LOCATOR_GAP. 2) Page Objects mandatory. 3) Await all interactions. 4) Assert roles/text/data-attributes only.
files MUST be an array of objects, NOT an object/dict."""


class CoderAgent:
    def __init__(self):
        self.llm = llm_service

    async def generate(self, story: JiraStory, architect_response: ArchitectResponse) -> CoderResponse:
        user_prompt = self._build_prompt(story, architect_response)
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        response = await self.llm.chat(messages)
        parsed = self._parse_response(response)
        
        files = []
        for f in parsed.get("files", []):
            if not isinstance(f, dict):
                continue
            try:
                files.append(GeneratedFile(
                    type=FileType(f.get("type", "spec")),
                    path=f.get("path", ""),
                    content=f.get("content", "")
                ))
            except Exception as e:
                logger.warning(f"Skipping file due to error: {e}")
                continue

        m = parsed.get("manifest", {})
        
        # coverage — defensive
        coverage = []
        for c in m.get("coverage", []):
            if isinstance(c, dict):
                try:
                    coverage.append(ManifestCoverage(
                        scenario_tag=c.get("scenario_tag", ""),
                        status=c.get("status", "GENERATED"),
                        output_file=c.get("output_file", "")
                    ))
                except Exception:
                    continue

        manifest = CoderManifest(
            jira_context=m.get("jira_context", {}),
            coverage=coverage,
            locator_inventory=m.get("locator_inventory", {}),
            assumptions_used=m.get("assumptions_used", [])
        )
        
        return CoderResponse(
            issue_key=story.issue_key,
            files=files,
            manifest=manifest,
            locator_gaps=parsed.get("locator_gaps", []),
            skipped_scenarios=parsed.get("skipped_scenarios", []),
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def _build_prompt(self, story: JiraStory, architect_response: ArchitectResponse) -> str:
        acs_list = architect_response.proposed_acs[:3]
        acs_text = "\n".join([f"- Given {ac.given} When {ac.when} Then {ac.then}" for ac in acs_list])
        gherkin_text = architect_response.gherkin[:500] if architect_response.gherkin else "Feature: auto"

        return f"""Issue: {story.issue_key} — {story.title}

Gherkin:
{gherkin_text}

ACs:
{acs_text}

Generate Playwright TypeScript tests with Page Objects."""

    def _parse_response(self, response: str) -> dict:
        logger.warning(f"Raw LLM response (first 500 chars): {response[:500]}")
        
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nCleaned: {cleaned[:1000]}")
            return {"files": [], "manifest": {}, "locator_gaps": [], "skipped_scenarios": []}
        
        # files — agar object/dict aa gaya to array mein convert karo
        files = data.get("files", [])
        if isinstance(files, dict):
            logger.warning("files is dict, converting to array")
            converted = []
            for path, content in files.items():
                file_type = "page_object" if "page" in path.lower() or "Page" in path else "spec"
                converted.append({
                    "type": file_type,
                    "path": path,
                    "content": content if isinstance(content, str) else json.dumps(content)
                })
            data["files"] = converted
        
        return data


coder_agent = CoderAgent()