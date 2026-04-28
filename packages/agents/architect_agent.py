import json
import logging
from datetime import datetime, timezone
from packages.schemas import JiraStory, AuditResponse
from packages.schemas.architect_schema import ArchitectResponse, HiddenPaths, ProposedAC, ACType
from packages.services.llm import llm_service

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert QA Architect. Your job is to ENRICH a Jira user story's acceptance criteria based on audit findings.

RULES:
1. KEEP all original ACs but rewrite them into proper Given/When/Then format if needed.
2. ADD NEW ACs to address gaps identified by the audit (issues, low-scoring dimensions, missing edge cases).
3. Tag each AC: HAPPY (normal flow), SAD (error/failure), EDGE (boundary/corner case), SECURITY (auth/permissions).
4. Original ACs should stay as HAPPY. New ACs addressing gaps should be SAD, EDGE, or SECURITY.
5. Each AC must have specific, testable Given/When/Then — no vague placeholders.

Return ONLY this exact JSON structure, no other text:
{
  "hidden_paths": {
    "auth_permissions": ["list of auth-related test gaps"],
    "input_boundaries": ["list of input validation gaps"],
    "network_async": ["list of network/timing gaps"],
    "data_state": ["list of data state gaps"],
    "ux_edge": ["list of UX edge case gaps"]
  },
  "proposed_acs": [
    {"id": "AC-1", "given": "specific precondition", "when": "specific action", "then": "specific expected outcome", "tag": "HAPPY"}
  ],
  "gherkin": "Feature: ...\\n  Scenario: ...",
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
        # Include ALL ACs, not just first 3
        criteria_text = "\n".join([f"- {c}" for c in (story.acceptance_criteria or [])])
        if not criteria_text:
            criteria_text = "(none provided)"

        # Build audit issues summary
        flags_summary = []
        for scenario in audit.scenarios:
            for flag in scenario.flags:
                flags_summary.append(f"- [{flag.type.value}] {flag.message}")
        flags_text = "\n".join(flags_summary) if flags_summary else "None"

        # Build audit issues list
        issues_text = "\n".join([f"- {i}" for i in (audit.issues or [])]) if audit.issues else "None"
        
        # Build dimension scores (DimensionScores is a Pydantic model, not a dict)
        dims = audit.dimensions
        dim_lines = []
        if dims:
            dim_lines.append(f"- Clarity: {round(dims.clarity * 100)}% — {dims.clarity_reason}")
            dim_lines.append(f"- Completeness: {round(dims.completeness * 100)}% — {dims.completeness_reason}")
            dim_lines.append(f"- Testability: {round(dims.testability * 100)}% — {dims.testability_reason}")
            dim_lines.append(f"- Edge Cases: {round(dims.edge_cases * 100)}% — {dims.edge_cases_reason}")
            dim_lines.append(f"- Consistency: {round(dims.consistency * 100)}% — {dims.consistency_reason}")
        dims_text = "\n".join(dim_lines) if dim_lines else "None"

        epic = f"\nEpic: {story.epic_context}" if story.epic_context else ""

        return f"""Story: {story.issue_key} - {story.title}
{story.description}

Current Acceptance Criteria:
{criteria_text}{epic}

AUDIT RESULTS:
Overall Score: {round(audit.overall_score * 100)}%

Dimension Scores:
{dims_text}

Critical Issues Found:
{issues_text}

Audit Flags:
{flags_text}

INSTRUCTIONS:
1. Keep ALL {len(story.acceptance_criteria or [])} original ACs (rewrite into proper Given/When/Then if needed)
2. Add NEW ACs specifically addressing each Critical Issue listed above
3. Add EDGE/SAD ACs for any dimension scoring below 70%
4. Ensure every new AC is specific, testable, and tagged appropriately
5. Do NOT duplicate existing ACs — only add what's missing"""

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