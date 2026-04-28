import json
import re
import logging
from datetime import datetime, timezone
from packages.schemas import JiraStory, AuditResponse
from packages.schemas.architect_schema import ArchitectResponse, HiddenPaths, ProposedAC, ACType
from packages.services.llm import llm_service

logger = logging.getLogger(__name__)


# ── System prompt: output ONLY new ACs, never rewrite originals ──────────
SYSTEM_PROMPT = """You are a QA Architect. Your ONLY job is to add the MISSING acceptance criteria
that the auditor identified as gaps. You must NOT rewrite, rephrase, or include the original ACs.

RULES:
1. Output ONLY the NEW ACs that address the Critical Issues from the audit.
2. Typically 2-5 new ACs. One per Critical Issue. Do NOT over-generate.
3. Tag each: SAD (error/failure path), EDGE (boundary/corner case), or SECURITY (auth/permission).
4. Never use the HAPPY tag — the originals already cover happy paths.
5. Number new ACs continuing from the last original (e.g. if 8 originals exist, start at AC-9).
6. Each AC must have specific, testable Given/When/Then — no vague placeholders.

Return ONLY this JSON, no other text:
{
  "hidden_paths": {
    "auth_permissions": [],
    "input_boundaries": [],
    "network_async": [],
    "data_state": [],
    "ux_edge": []
  },
  "proposed_acs": [
    {"id": "AC-9", "given": "specific precondition", "when": "specific action", "then": "specific outcome", "tag": "SAD"}
  ],
  "gherkin": "Feature: ...\\n  Scenario: ...",
  "assumptions": ["ASSUMPTION: ..."]
}

CRITICAL: proposed_acs must contain ONLY the new ACs. Do NOT include the originals."""


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

        # ── Merge: original ACs (untouched) + new ACs from LLM ──
        original_acs = self._originals_as_proposed(story)
        all_acs = original_acs + parsed["proposed_acs"]

        return ArchitectResponse(
            issue_key=story.issue_key,
            hidden_paths=parsed["hidden_paths"],
            proposed_acs=all_acs,
            gherkin=parsed["gherkin"],
            assumptions=parsed["assumptions"],
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    # ── Convert original Jira ACs to ProposedAC (HAPPY, text unchanged) ──
    def _originals_as_proposed(self, story: JiraStory) -> list[ProposedAC]:
        acs = []
        for i, text in enumerate(story.acceptance_criteria or []):
            given, when, then = self._split_gwt(text)
            acs.append(ProposedAC(
                id=f"AC-{i + 1}",
                given=given,
                when=when,
                then=then,
                tag=ACType.HAPPY
            ))
        return acs

    @staticmethod
    def _split_gwt(text: str) -> tuple[str, str, str]:
        """Best-effort split of AC text into Given/When/Then."""
        lower = text.lower()
        if "given" in lower and "when" in lower and "then" in lower:
            parts = re.split(r"(?i)\b(given|when|then)\b", text)
            bucket = {"given": "", "when": "", "then": ""}
            key = None
            for seg in parts:
                sl = seg.strip().lower()
                if sl in bucket:
                    key = sl
                elif key:
                    bucket[key] += seg.strip() + " "
            g = bucket["given"].strip()
            w = bucket["when"].strip()
            t = bucket["then"].strip()
            if g and w and t:
                return g, w, t
        # Not structured — keep full text in 'then', generic given/when
        return (
            "the preconditions for this scenario are met",
            "the described action is performed",
            text.strip()
        )

    # ── Build user prompt ─────────────────────────────────────────────────
    def _build_prompt(self, story: JiraStory, audit: AuditResponse) -> str:
        num_acs = len(story.acceptance_criteria or [])
        criteria_text = "\n".join(
            [f"  AC-{i+1}: {c}" for i, c in enumerate(story.acceptance_criteria or [])]
        ) or "  (none provided)"

        # Audit flags
        flags_summary = []
        for scenario in audit.scenarios:
            for flag in scenario.flags:
                flags_summary.append(f"- [{flag.type.value}] {flag.message}")
        flags_text = "\n".join(flags_summary) if flags_summary else "None"

        # Critical issues (this is what drives new ACs)
        issues = audit.issues or []
        issues_text = "\n".join([f"- {iss}" for iss in issues]) if issues else "None"
        num_issues = len(issues)

        # Dimension scores
        dims = audit.dimensions
        dim_lines = []
        if dims:
            dim_lines.append(f"- Clarity: {round(dims.clarity * 100)}%  ({dims.clarity_reason})")
            dim_lines.append(f"- Completeness: {round(dims.completeness * 100)}%  ({dims.completeness_reason})")
            dim_lines.append(f"- Testability: {round(dims.testability * 100)}%  ({dims.testability_reason})")
            dim_lines.append(f"- Edge Cases: {round(dims.edge_cases * 100)}%  ({dims.edge_cases_reason})")
            dim_lines.append(f"- Consistency: {round(dims.consistency * 100)}%  ({dims.consistency_reason})")
        dims_text = "\n".join(dim_lines) if dim_lines else "None"

        epic = f"\nEpic: {story.epic_context}" if story.epic_context else ""

        return f"""Story: {story.issue_key} - {story.title}
{story.description}

EXISTING ACs (DO NOT rewrite — they are final):
{criteria_text}{epic}

AUDIT RESULTS — Overall: {round(audit.overall_score * 100)}%

Dimension scores:
{dims_text}

Critical Issues (each needs exactly one new AC):
{issues_text}

Flags:
{flags_text}

YOUR TASK:
- Add {num_issues} new ACs (starting at AC-{num_acs + 1}).
- One new AC per Critical Issue above.
- Tag each SAD, EDGE, or SECURITY. Never HAPPY.
- Do NOT include or rewrite the original {num_acs} ACs."""

    # ── Parse LLM JSON response ──────────────────────────────────────────
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
            raw_tag = str(ac.get("tag", "SAD")).upper()
            if raw_tag not in valid_tags:
                raw_tag = "SAD"
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