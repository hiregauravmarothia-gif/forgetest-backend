import json
import logging
from datetime import datetime, timezone
from packages.schemas import JiraStory, AuditResponse
from packages.schemas.architect_schema import ArchitectResponse, HiddenPaths, ProposedAC, ACType
from packages.services.llm import llm_service

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Transform Jira stories into Gherkin specs. Return ONLY this exact JSON structure, no other text:
{
  "hidden_paths": {
    "auth_permissions": ["example"],
    "input_boundaries": ["example"],
    "network_async": ["example"],
    "data_state": ["example"],
    "ux_edge": ["example"]
  },
  "proposed_acs": [
    {"id": "AC-1", "given": "...", "when": "...", "then": "...", "tag": "HAPPY"}
  ],
  "gherkin": "Feature: ...",
  "assumptions": ["ASSUMPTION: ..."]
}

tag must be one of: HAPPY, SAD, EDGE, SECURITY"""


class ArchitectAgent:
    def __init__(self):
        self.llm = llm_service

    async def enrich(self, story: JiraStory, audit: AuditResponse) -> ArchitectResponse:
        user_prompt = self._build_prompt(story, audit)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        response = await self.llm.chat(messages)
        parsed = self._parse_response(response)
        
        return ArchitectResponse(
            issue_key=story.issue_key,
            hidden_paths=parsed["hidden_paths"],
            proposed_acs=parsed["proposed_acs"],
            gherkin=parsed["gherkin"],
            assumptions=parsed["assumptions"],
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def _build_prompt(self, story: JiraStory, audit: AuditResponse) -> str:
        flags_summary = []
        for scenario in audit.scenarios:
            for flag in scenario.flags:
                flags_summary.append(f"[{flag.type.value}] {flag.message}")
        flags_text = "\n".join(flags_summary[:5]) if flags_summary else "None"
        
        criteria_text = "\n".join([f"- {c}" for c in story.acceptance_criteria[:3]])
        epic = f"\nEpic: {story.epic_context}" if story.epic_context else ""

        return f"""Story: {story.issue_key} - {story.title}
{story.description}

ACs:
{criteria_text}{epic}

Audit Score: {audit.overall_score}
Flags:
{flags_text}

Enrich with hidden paths, proposed ACs, and Gherkin."""

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
            return self._empty_response()
        
        # hidden_paths — defensive
        hp = data.get("hidden_paths", {})
        if isinstance(hp, list):
            hp = {"auth_permissions": hp}
        if not isinstance(hp, dict):
            hp = {}

        hidden_paths = HiddenPaths(
            auth_permissions=hp.get("auth_permissions", []),
            input_boundaries=hp.get("input_boundaries", []),
            network_async=hp.get("network_async", []),
            data_state=hp.get("data_state", []),
            ux_edge=hp.get("ux_edge", [])
        )
        
        # proposed_acs — defensive with ACType fallback
        valid_tags = {e.value for e in ACType}
        proposed_acs = []
        for ac in data.get("proposed_acs", []):
            if not isinstance(ac, dict):
                continue
            raw_tag = str(ac.get("tag", "HAPPY")).upper()
            if raw_tag not in valid_tags:
                raw_tag = "HAPPY"
            try:
                proposed_acs.append(ProposedAC(
                    id=ac.get("id", f"AC-{len(proposed_acs)+1}"),
                    given=ac.get("given", ""),
                    when=ac.get("when", ""),
                    then=ac.get("then", ""),
                    tag=ACType(raw_tag)
                ))
            except Exception as e:
                logger.warning(f"Skipping AC due to error: {e}")
                continue
        
        return {
            "hidden_paths": hidden_paths,
            "proposed_acs": proposed_acs,
            "gherkin": data.get("gherkin", ""),
            "assumptions": data.get("assumptions", [])
        }

    def _empty_response(self) -> dict:
        return {
            "hidden_paths": HiddenPaths(),
            "proposed_acs": [],
            "gherkin": "",
            "assumptions": []
        }


architect_agent = ArchitectAgent()