import json
import logging
from datetime import datetime, timezone
from packages.schemas import JiraStory
from packages.schemas.architect_schema import ArchitectResponse
from packages.schemas.coder_schema import CoderResponse, GeneratedFile, CoderManifest, ManifestCoverage, FileType
from packages.services.llm import llm_service

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a senior QA automation engineer. Generate comprehensive Playwright TypeScript tests.

LAWS — never break these:
1. Use data-testid or ARIA role locators ONLY. If no stable locator exists, use // ⚠ LOCATOR_GAP comment.
2. Page Objects are MANDATORY — no raw locators in spec files.
3. Await ALL async interactions.
4. Assert on roles, text, data-attributes only — never on CSS classes or implementation details.
5. Cover EVERY acceptance criterion — one describe block per AC, tagged with AC-N.
6. Page Object must have one method per distinct user action from the ACs.
7. Generate declarative tests — describe WHAT not HOW.

FILE STRUCTURE:
- One page object file per page/component under test
- One spec file per feature area
- Page object path: e2e/pages/[FeatureName]Page.ts
- Spec path: e2e/specs/[feature-name].spec.ts

Return ONLY this exact JSON structure, no markdown, no preamble:
{
  "files": [
    {
      "type": "page_object",
      "path": "e2e/pages/FeaturePage.ts",
      "content": "full TypeScript content here"
    },
    {
      "type": "spec",
      "path": "e2e/specs/feature.spec.ts",
      "content": "full TypeScript content here"
    }
  ],
  "manifest": {
    "jira_context": {"issue_key": ""},
    "coverage": [
      {"scenario_tag": "AC-1", "status": "GENERATED", "output_file": "e2e/specs/feature.spec.ts"}
    ],
    "locator_inventory": {"buttonName": "data-testid='button-id'"},
    "assumptions_used": []
  },
  "locator_gaps": [],
  "skipped_scenarios": []
}

files MUST be an array of objects, NOT an object/dict.
coverage MUST have one entry per AC from the story."""


class CoderAgent:
    def __init__(self):
        self.llm = llm_service

    async def generate(
        self,
        story: JiraStory,
        architect_response: ArchitectResponse,
        edited_acs: list[dict] | None = None,
        validator_feedback: str | None = None
    ) -> CoderResponse:
        user_prompt = self._build_prompt(story, architect_response, edited_acs, validator_feedback)

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

    def _build_prompt(
        self,
        story: JiraStory,
        architect_response: ArchitectResponse,
        edited_acs: list[dict] | None = None,
        validator_feedback: str | None = None
    ) -> str:
        # Use ALL original ACs from the story first (richer source)
        original_acs = ""
        if story.acceptance_criteria:
            original_acs = "\n".join([
                f"AC-{i+1}: {ac}" for i, ac in enumerate(story.acceptance_criteria)
            ])

        # Use ALL proposed ACs from architect (enriched with Given/When/Then)
        proposed_acs = ""
        if architect_response.proposed_acs:
            proposed_acs = "\n".join([
                f"{ac.id} [{ac.tag}]\n  Given {ac.given}\n  When {ac.when}\n  Then {ac.then}"
                for ac in architect_response.proposed_acs
            ])

        # Full gherkin — no truncation
        gherkin_text = architect_response.gherkin or "Feature: auto-generated"

        # Hidden paths for additional coverage context
        paths = architect_response.hidden_paths
        hidden_paths_text = ""
        all_paths = (
            paths.auth_permissions +
            paths.input_boundaries +
            paths.network_async +
            paths.data_state +
            paths.ux_edge
        )
        if all_paths:
            hidden_paths_text = f"\nHidden paths to consider:\n" + "\n".join([f"- {p}" for p in all_paths[:10]])

        # Assumptions for test setup context
        assumptions_text = ""
        if architect_response.assumptions:
            assumptions_text = "\nAssumptions (use for test setup/fixtures):\n" + "\n".join(
                [f"- {a}" for a in architect_response.assumptions]
            )

        # Path B: use user-edited ACs instead of architect proposed ACs
        # The user has already reviewed everything — their list is the ONLY source of truth.
        # Rejected ACs are filtered out by the ModalApp before reaching here.
        if edited_acs:
            edited_text = "\n".join([
                f"{ac.get('id', f'AC-{i+1}')} [{ac.get('tag', 'HAPPY')}]\n"
                f"  Given {ac.get('given', '')}\n"
                f"  When {ac.get('when', '')}\n"
                f"  Then {ac.get('then', '')}"
                for i, ac in enumerate(edited_acs)
            ])
            proposed_acs = f"USER-REVIEWED ACs (primary source):\n{edited_text}"
            # Clear original ACs — the user's reviewed list supersedes them.
            # Without this, the LLM generates tests for rejected ACs too.
            original_acs = ""

        feedback_section = ""
        if validator_feedback:
            feedback_section = f"\n\nVALIDATOR FEEDBACK - FIX THESE ISSUES:\n{validator_feedback}"

        # Build the prompt — adapt wording based on whether we have user-reviewed ACs
        if edited_acs:
            ac_section = f"""USER-REVIEWED ACCEPTANCE CRITERIA (cover ONLY these — {len(edited_acs)} ACs):
{proposed_acs}

⚠️ IMPORTANT: Generate tests ONLY for the {len(edited_acs)} ACs listed above.
Do NOT add tests for any ACs that are not in this list. The user has reviewed
and removed ACs they don't want tested."""
        else:
            ac_section = f"""ORIGINAL ACCEPTANCE CRITERIA (cover ALL of these):
{original_acs or 'See proposed ACs below'}

PROPOSED ACs (Given/When/Then):
{proposed_acs or 'See original ACs above'}"""

        return f"""Issue: {story.issue_key} — {story.title}
Description: {story.description or 'Not provided'}

{ac_section}

GHERKIN SPECIFICATION:
{gherkin_text}
{hidden_paths_text}
{assumptions_text}

Generate complete Playwright TypeScript tests covering ALL acceptance criteria above.
Every AC must have a corresponding describe/test block tagged with AC-N.
Page Object must have methods for every distinct user action.{feedback_section}"""

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

        # files — convert dict to array if LLM returns wrong format
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
