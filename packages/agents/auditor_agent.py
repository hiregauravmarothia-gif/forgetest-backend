import json
import statistics
from datetime import datetime, timezone
from typing import Optional
from packages.services.llm import llm_service
from packages.schemas import JiraStory
from packages.schemas.audit_schema import (
    AuditResponse, DimensionScores, ScenarioResult,
    Flag, FlagType, Severity, Verdict
)

SYSTEM_PROMPT = """You are the Auditor Agent for ForgeTest — a requirement quality engine.
Your job is to audit a Jira story across 5 dimensions and return a
structured JSON response.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSIONS (score each 0.0–1.0)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

clarity (weight: 25%)
Does the story clearly describe WHAT needs to be done?
Is the language unambiguous and specific?
Rubric:
0.0–0.1 → Completely vague, no meaningful information
0.1–0.3 → Very weak, major ambiguity
0.3–0.5 → Partial clarity, significant gaps
0.5–0.7 → Mostly clear, minor ambiguity
0.7–0.9 → Clear and specific
0.9–1.0 → Excellent, zero ambiguity

completeness (weight: 20%)
Are all necessary details present?
User role, action, expected outcome, preconditions?
Rubric:
0.0–0.1 → Missing almost everything
0.1–0.3 → Only 1 element present
0.3–0.5 → 2 elements present
0.5–0.7 → 3 elements present
0.7–0.9 → All elements present with minor gaps
0.9–1.0 → Complete and thorough

testability (weight: 20%)
Can QA engineers write automated tests from this story?
Are acceptance criteria measurable and deterministic?
Rubric:
0.0–0.1 → Cannot be tested at all
0.1–0.3 → Extremely difficult to test
0.3–0.5 → Partially testable
0.5–0.7 → Mostly testable with effort
0.7–0.9 → Clearly testable
0.9–1.0 → Perfectly testable with clear assertions

edge_cases (weight: 20%)
Are boundary conditions, error states, and negative paths covered?
STRICT RULES:

If NO edge cases mentioned anywhere: score MUST be 0.0–0.1
If only 1 edge case implied: 0.1–0.2
If 2-3 edge cases: 0.3–0.5
If comprehensive coverage: 0.6–1.0

"User should be able to login" with no ACs = edge_cases: 0.05
DO NOT give credit for implied or assumed edge cases.

consistency (weight: 15%)
Do the description, title, and ACs align with each other?
Are there contradictions or mismatches?
Rubric:
0.0–0.1 → Direct contradictions present
0.1–0.3 → Major inconsistencies
0.3–0.5 → Some mismatches
0.5–0.7 → Mostly consistent
0.7–0.9 → Consistent
0.9–1.0 → Perfectly aligned

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCENARIOS (evaluate these 5)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evaluate each dimension as a scenario:

clarity
completeness
testability
edge_cases
consistency

For each scenario, assign:

score: dimension score (0-1)
verdict: PASS (>=0.75), ENRICH (0.5-0.75), REJECT (<0.5)
flags: specific issues found

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLAG TYPES (use exact values only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IMPERATIVE_TRAP: Imperative language creating false positives
MISSING_BOUNDARY: Missing boundary/edge conditions
AMBIGUOUS_OUTCOME: Vague success/failure criteria
MISSING_GIVEN: Missing preconditions or setup
FLAKE_RISK: Potential for flaky tests

Severity: critical, major, minor

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ISSUES LIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return top 3 critical issues as short strings (max 8 words each).
These will be shown directly in the Jira panel.
Example: "Missing validation in login", "No error handling defined"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION REASONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For each dimension, return a short reason string (max 8 words).
This is shown as a tooltip/label next to the score bar in the UI.
Be specific — reference what is actually missing or good.
Examples:
  "Requirement is vague and ambiguous"
  "Missing preconditions and expected outcome"
  "No acceptance criteria defined"
  "No edge cases or error paths mentioned"
  "Title and description are well aligned"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY valid JSON, no additional text, no markdown:
{
  "scenarios": [
    {
      "scenario": "clarity",
      "score": 0.3,
      "verdict": "REJECT",
      "flags": [
        {
          "line": 1,
          "type": "AMBIGUOUS_OUTCOME",
          "severity": "critical",
          "message": "No clear success criteria defined for login"
        }
      ]
    },
    {
      "scenario": "completeness",
      "score": 0.2,
      "verdict": "REJECT",
      "flags": []
    },
    {
      "scenario": "testability",
      "score": 0.25,
      "verdict": "REJECT",
      "flags": []
    },
    {
      "scenario": "edge_cases",
      "score": 0.05,
      "verdict": "REJECT",
      "flags": []
    },
    {
      "scenario": "consistency",
      "score": 0.6,
      "verdict": "ENRICH",
      "flags": []
    }
  ],
  "dimensions": {
    "clarity": 0.3,
    "clarity_reason": "Requirement is vague and ambiguous",
    "completeness": 0.2,
    "completeness_reason": "Missing preconditions and expected outcome",
    "testability": 0.25,
    "testability_reason": "No acceptance criteria defined",
    "edge_cases": 0.05,
    "edge_cases_reason": "No edge cases or error paths mentioned",
    "consistency": 0.6,
    "consistency_reason": "Title and description are mostly aligned"
  },
  "issues": [
    "Missing validation in login",
    "No error handling defined",
    "Weak acceptance criteria"
  ]
}"""


class AuditorAgent:
    def __init__(self):
        self.llm = llm_service

    async def audit(self, story: JiraStory) -> AuditResponse:
        hard_fail, hard_fail_reason = self._check_hard_fail(story)

        if hard_fail:
            empty_dimensions = DimensionScores(
                clarity=0.0,
                clarity_reason="Requirement failed pre-check",
                completeness=0.0,
                completeness_reason="Requirement failed pre-check",
                testability=0.0,
                testability_reason="Requirement failed pre-check",
                edge_cases=0.0,
                edge_cases_reason="Requirement failed pre-check",
                consistency=0.0,
                consistency_reason="Requirement failed pre-check",
            )
            return AuditResponse(
                issue_key=story.issue_key,
                scenarios=[],
                overall_score=0.0,
                dimensions=empty_dimensions,
                confidence=1.0,
                hard_fail=True,
                hard_fail_reason=hard_fail_reason,
                issues=[hard_fail_reason],
                recommended_next_step="Rewrite the requirement with a clear description and acceptance criteria.",
                last_analyzed="just now",
                timestamp=datetime.now(timezone.utc).isoformat()
            )

        user_prompt = self._build_prompt(story)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = await self.llm.chat(messages)
            parsed = self._parse_response(response)

            dimensions = DimensionScores(**parsed["dimensions"])
            overall_score = self._calculate_overall_score(dimensions, parsed["scenarios"])
            confidence = self._calculate_confidence(dimensions)
            recommended_next_step = self._get_recommended_next_step(overall_score)

            return AuditResponse(
                issue_key=story.issue_key,
                scenarios=parsed["scenarios"],
                overall_score=overall_score,
                dimensions=dimensions,
                confidence=confidence,
                hard_fail=False,
                hard_fail_reason=None,
                issues=parsed.get("issues", []),
                recommended_next_step=recommended_next_step,
                last_analyzed="just now",
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            raise RuntimeError(f"LLM service failed: {e}")

    def _check_hard_fail(self, story: JiraStory) -> tuple[bool, Optional[str]]:
        desc = story.description or ""
        desc_lower = desc.lower()
        desc_words = len(desc.split())
        has_acs = len(story.acceptance_criteria) > 0

        # Meaningless description — always hard fail
        meaningless = {'test', 'fix', 'asdf', 'todo', 'tbd', 'na', 'n/a', 'wip', '...', 'placeholder'}
        if desc.strip().lower() in meaningless:
            return True, f"Meaningless description: '{desc.strip()}'"

        # Combined rule — all three conditions must be true
        has_action = any(word in desc_lower for word in [
            'click', 'submit', 'enter', 'select', 'login', 'logout', 'create', 'update',
            'delete', 'view', 'open', 'close', 'search', 'filter', 'upload', 'download',
            'send', 'receive', 'navigate', 'access', 'able to', 'can ', 'should be able'
        ])
        has_outcome = any(word in desc_lower for word in [
            'then', 'should', 'must', 'will', 'expect', 'result', 'output', 'return'
        ])

        if not has_acs and desc_words < 8 and not has_action and not has_outcome:
            return True, "Description too vague — missing action and outcome (< 8 words)"

        return False, None

    def _get_recommended_next_step(self, overall_score: float) -> str:
        if overall_score >= 0.75:
            return "Requirement looks good. Approve to generate Playwright tests."
        elif overall_score >= 0.5:
            return "Review the proposed improvements below, then approve to generate tests."
        else:
            return "Rewrite the requirement - add acceptance criteria, preconditions, and edge cases."

    def _calculate_overall_score(self, dimensions: DimensionScores, scenarios: list) -> float:
        score = (
            dimensions.clarity      * 0.25 +
            dimensions.completeness * 0.20 +
            dimensions.testability  * 0.20 +
            dimensions.edge_cases   * 0.20 +
            dimensions.consistency  * 0.15
        )

        has_edge_cases = dimensions.edge_cases > 0.1
        has_negative_scenarios = any(
            any(flag.type.value in ['MISSING_BOUNDARY', 'AMBIGUOUS_OUTCOME']
                for flag in s.flags)
            for s in scenarios
        )

        if not has_edge_cases and not has_negative_scenarios:
            score = min(score, 0.55)

        return round(max(0.0, min(1.0, score)), 4)

    def _calculate_confidence(self, dimensions: DimensionScores) -> float:
        scores = [
            dimensions.clarity,
            dimensions.completeness,
            dimensions.testability,
            dimensions.edge_cases,
            dimensions.consistency
        ]
        std_dev = statistics.pstdev(scores)
        mean_score = sum(scores) / len(scores)
        confidence = (1 - (std_dev / 0.5)) * (0.5 + 0.5 * mean_score)
        return round(max(0.0, min(1.0, confidence)), 4)

    def _build_prompt(self, story: JiraStory) -> str:
        epic_context = f"\n\nEpic Context: {story.epic_context}" if story.epic_context else ""
        criteria_list = "\n".join([f"- {c}" for c in story.acceptance_criteria]) or "None provided"

        return f"""Audit this Jira story:

Issue Key: {story.issue_key}
Title: {story.title}
Description: {story.description or 'Not provided'}

Acceptance Criteria:
{criteria_list}
{epic_context}

Evaluate all 5 dimensions (clarity, completeness, testability, edge_cases, consistency).
For each dimension, include a short reason string (max 8 words) explaining the score.
Return your audit results in the exact JSON format specified."""

    def _parse_response(self, response: str) -> dict:
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        data = json.loads(cleaned.strip())

        scenarios = []
        for s in data.get("scenarios", []):
            flags = []
            for f in s.get("flags", []):
                try:
                    flag_type = FlagType(f.get("type", "MISSING_BOUNDARY").replace(" ", "_").upper())
                except ValueError:
                    flag_type = FlagType.MISSING_BOUNDARY
                try:
                    severity = Severity(f.get("severity", "minor").lower())
                except ValueError:
                    severity = Severity.minor

                flags.append(Flag(
                    line=f.get("line", 1),
                    type=flag_type,
                    severity=severity,
                    message=f.get("message", "")
                ))

            try:
                verdict = Verdict(s.get("verdict", "ENRICH").upper())
            except ValueError:
                verdict = Verdict.ENRICH

            scenarios.append(ScenarioResult(
                scenario=s.get("scenario", "unknown"),
                score=float(s.get("score", 0.0)),
                verdict=verdict,
                flags=flags
            ))

        raw_dimensions = data.get("dimensions", {})
        dimensions = {
            "clarity":               float(raw_dimensions.get("clarity", 0.0)),
            "clarity_reason":        str(raw_dimensions.get("clarity_reason", "")),
            "completeness":          float(raw_dimensions.get("completeness", 0.0)),
            "completeness_reason":   str(raw_dimensions.get("completeness_reason", "")),
            "testability":           float(raw_dimensions.get("testability", 0.0)),
            "testability_reason":    str(raw_dimensions.get("testability_reason", "")),
            "edge_cases":            float(raw_dimensions.get("edge_cases", 0.0)),
            "edge_cases_reason":     str(raw_dimensions.get("edge_cases_reason", "")),
            "consistency":           float(raw_dimensions.get("consistency", 0.0)),
            "consistency_reason":    str(raw_dimensions.get("consistency_reason", "")),
        }

        issues = data.get("issues", [])
        if isinstance(issues, list):
            issues = [str(i) for i in issues[:3]]

        return {
            "scenarios": scenarios,
            "dimensions": dimensions,
            "issues": issues,
        }


auditor_agent = AuditorAgent()