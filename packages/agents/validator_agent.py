import json
import re
import logging
import statistics
from datetime import datetime, timezone
from packages.schemas import JiraStory
from packages.schemas.architect_schema import ArchitectResponse, ProposedAC
from packages.schemas.coder_schema import CoderResponse
from packages.schemas.validator_schema import (
    ValidatorResponse, ValidatorDimensions, ValidatorIssue, ValidatorStatus
)
from packages.services.llm import llm_service

logger = logging.getLogger(__name__)

THRESHOLD = 0.75
MAX_RETRIES = 2

WEIGHTS = {
    "coverage":   0.30,
    "balance":    0.20,
    "redundancy": 0.15,
    "fidelity":   0.35,
}

FIDELITY_PROMPT = """You are a test quality reviewer. For each AC-Test pair below, decide if the test assertions verify the AC.

Respond ONLY with valid JSON — no markdown, no preamble:
{
  "results": [
    {"ac_id": "AC-1", "verdict": "VERIFIED", "confidence": 0.9},
    {"ac_id": "AC-2", "verdict": "PARTIAL", "confidence": 0.6},
    {"ac_id": "AC-3", "verdict": "NOT_VERIFIED", "confidence": 0.8}
  ]
}

Verdict options: VERIFIED (test fully checks the AC), PARTIAL (test partially checks it), NOT_VERIFIED (test does not check it).
Confidence: 0.0-1.0 — how certain you are.
"""


class ValidatorAgent:

    def __init__(self):
        self.llm = llm_service

    async def validate(
        self,
        story: JiraStory,
        architect_response: ArchitectResponse,
        coder_response: CoderResponse,
        edited_acs: list[dict] | None = None,
        retry_count: int = 0,
        path_used: str = "A"
    ) -> ValidatorResponse:

        # Determine which AC set to validate against
        if path_used == "B" and edited_acs:
            acs = [ProposedAC(**ac) for ac in edited_acs]
        else:
            acs = architect_response.proposed_acs

        # If no proposed ACs, fall back to original story ACs
        original_acs = story.acceptance_criteria or []

        # Combine all spec file content for analysis
        spec_content = "\n\n".join([
            f"// FILE: {f.path}\n{f.content}"
            for f in coder_response.files
            if f.type.value == "spec"
        ])

        if not spec_content:
            logger.warning(f"No spec files found for job validation")
            return self._empty_response(story.issue_key, retry_count, path_used)

        # ── Score each dimension ──────────────────────────
        coverage_score, missing_acs = self._score_coverage(acs, original_acs, coder_response)
        balance_score, balance_issues = self._score_balance(coder_response)
        redundancy_score, redundancy_issues = self._score_redundancy(coder_response)
        fidelity_score, fidelity_issues = await self._score_fidelity(acs, original_acs, spec_content)

        # ── Weighted overall ──────────────────────────────
        overall = round(
            coverage_score   * WEIGHTS["coverage"] +
            balance_score    * WEIGHTS["balance"] +
            redundancy_score * WEIGHTS["redundancy"] +
            fidelity_score   * WEIGHTS["fidelity"],
            4
        )

        # ── Determine status ──────────────────────────────
        attempts_remaining = MAX_RETRIES - retry_count
        if overall >= THRESHOLD:
            status = ValidatorStatus.PASSED
        elif attempts_remaining <= 0:
            status = ValidatorStatus.NEEDS_REVIEW
        else:
            status = ValidatorStatus.FAILED

        # ── Compile issues list ───────────────────────────
        all_issues = missing_acs + balance_issues + redundancy_issues + fidelity_issues
        # Sort by severity: missing_ac first, then low_fidelity, then others
        priority = {"missing_ac": 0, "low_fidelity": 1, "imbalanced": 2, "duplicate": 3}
        all_issues.sort(key=lambda x: priority.get(x.type, 99))

        dimensions = ValidatorDimensions(
            coverage=round(coverage_score, 4),
            balance=round(balance_score, 4),
            redundancy=round(redundancy_score, 4),
            fidelity=round(fidelity_score, 4),
        )

        logger.info(
            f"Validator: issue={story.issue_key} overall={overall} "
            f"coverage={coverage_score:.2f} balance={balance_score:.2f} "
            f"redundancy={redundancy_score:.2f} fidelity={fidelity_score:.2f} "
            f"status={status} retry={retry_count}"
        )

        return ValidatorResponse(
            issue_key=story.issue_key,
            overall_score=overall,
            dimensions=dimensions,
            status=status,
            issues=all_issues[:5],  # Top 5 issues for feedback to coder
            retry_count=retry_count,
            attempts_remaining=max(0, attempts_remaining),
            path_used=path_used,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    # ── Coverage scoring ──────────────────────────────────
    def _score_coverage(
        self,
        proposed_acs: list,
        original_acs: list[str],
        coder_response: CoderResponse
    ) -> tuple[float, list[ValidatorIssue]]:

        # Build set of covered AC IDs from manifest
        covered_tags = {c.scenario_tag.lower() for c in coder_response.manifest.coverage}

        # Also scan spec content for AC references
        spec_text = " ".join([
            f.content for f in coder_response.files if f.type.value == "spec"
        ]).lower()

        issues = []
        covered_count = 0
        total = 0

        # Check proposed ACs
        for ac in proposed_acs:
            total += 1
            ac_id = ac.id.lower()
            ac_tag = f"@{ac_id}".lower()

            # Check manifest coverage OR spec content mentions this AC
            if (ac_id in covered_tags or ac_tag in covered_tags or
                    ac_id in spec_text or ac_tag in spec_text):
                covered_count += 1
            else:
                issues.append(ValidatorIssue(
                    type="missing_ac",
                    ac_id=ac.id,
                    suggestion=f"Add a test for {ac.id} [{ac.tag}]: {ac.then[:60]}..."
                ))

        # Also check original ACs if no proposed ACs
        if not proposed_acs and original_acs:
            for i, ac_text in enumerate(original_acs):
                total += 1
                ac_id = f"ac-{i+1}"
                if ac_id in spec_text or f"ac{i+1}" in spec_text:
                    covered_count += 1
                else:
                    issues.append(ValidatorIssue(
                        type="missing_ac",
                        ac_id=f"AC-{i+1}",
                        suggestion=f"Add a test for: {ac_text[:80]}..."
                    ))

        if total == 0:
            return 1.0, []

        score = covered_count / total
        return score, issues

    # ── Balance scoring ───────────────────────────────────
    def _score_balance(
        self,
        coder_response: CoderResponse
    ) -> tuple[float, list[ValidatorIssue]]:

        # Count by tag from manifest coverage
        tag_counts = {"happy": 0, "sad": 0, "edge": 0, "security": 0}

        spec_text = " ".join([
            f.content for f in coder_response.files if f.type.value == "spec"
        ]).lower()

        # Count from manifest tags
        for entry in coder_response.manifest.coverage:
            tag = entry.scenario_tag.lower()
            for t in tag_counts:
                if t in tag:
                    tag_counts[t] += 1

        # Also scan spec for keywords if manifest is sparse
        if sum(tag_counts.values()) < 2:
            happy_patterns = ['valid', 'success', 'correct', 'should be able', 'happy']
            sad_patterns = ['invalid', 'error', 'fail', 'incorrect', 'wrong', 'sad']
            edge_patterns = ['boundary', 'edge', 'limit', 'empty', 'null', 'timeout', 'maximum', 'minimum']

            for pattern in happy_patterns:
                if pattern in spec_text:
                    tag_counts["happy"] += 1
                    break
            for pattern in sad_patterns:
                if pattern in spec_text:
                    tag_counts["sad"] += 1
                    break
            for pattern in edge_patterns:
                if pattern in spec_text:
                    tag_counts["edge"] += 1
                    break

        issues = []
        has_happy = tag_counts["happy"] > 0
        has_sad = tag_counts["sad"] > 0
        has_edge = tag_counts["edge"] > 0

        if not has_happy:
            issues.append(ValidatorIssue(
                type="imbalanced",
                suggestion="Add at least one happy path test (successful user journey)"
            ))
        if not has_sad:
            issues.append(ValidatorIssue(
                type="imbalanced",
                suggestion="Add at least one sad path test (error/failure scenario)"
            ))
        if not has_edge:
            issues.append(ValidatorIssue(
                type="imbalanced",
                suggestion="Add at least one edge case test (boundary/limit conditions)"
            ))

        # Score: full marks if all 3 present, partial otherwise
        present = sum([has_happy, has_sad, has_edge])
        score = present / 3.0

        return score, issues

    # ── Redundancy scoring ────────────────────────────────
    def _score_redundancy(
        self,
        coder_response: CoderResponse
    ) -> tuple[float, list[ValidatorIssue]]:

        # Extract individual test blocks from spec files
        test_blocks = []
        for f in coder_response.files:
            if f.type.value != "spec":
                continue
            # Match test() and it() blocks
            matches = re.findall(
                r"(?:test|it)\s*\(['\"`]([^'\"` ]+)['\"`]",
                f.content
            )
            test_blocks.extend(matches)

        if len(test_blocks) <= 1:
            return 1.0, []

        # Normalize test names for similarity check
        def normalize(s: str) -> set:
            return set(re.sub(r'[^a-z0-9 ]', '', s.lower()).split())

        issues = []
        duplicate_pairs = []

        for i in range(len(test_blocks)):
            for j in range(i + 1, len(test_blocks)):
                a = normalize(test_blocks[i])
                b = normalize(test_blocks[j])
                if not a or not b:
                    continue
                # Jaccard similarity
                intersection = len(a & b)
                union = len(a | b)
                similarity = intersection / union if union > 0 else 0

                if similarity > 0.85:
                    duplicate_pairs.append((test_blocks[i], test_blocks[j]))

        if duplicate_pairs:
            for pair in duplicate_pairs[:2]:
                issues.append(ValidatorIssue(
                    type="duplicate",
                    suggestion=f"Merge similar tests: '{pair[0][:40]}' and '{pair[1][:40]}'"
                ))

        # Score: penalise for duplicates
        duplicate_ratio = len(duplicate_pairs) / len(test_blocks)
        score = max(0.0, 1.0 - duplicate_ratio)

        return round(score, 4), issues

    # ── Fidelity scoring (LLM) ────────────────────────────
    async def _score_fidelity(
        self,
        proposed_acs: list,
        original_acs: list[str],
        spec_content: str
    ) -> tuple[float, list[ValidatorIssue]]:

        # Build AC list for fidelity check
        ac_pairs = []
        if proposed_acs:
            for ac in proposed_acs[:6]:  # Cap at 6 to control LLM cost
                ac_text = f"Given {ac.given} When {ac.when} Then {ac.then}"
                ac_pairs.append({"id": ac.id, "text": ac_text})
        elif original_acs:
            for i, ac_text in enumerate(original_acs[:6]):
                ac_pairs.append({"id": f"AC-{i+1}", "text": ac_text})

        if not ac_pairs:
            return 1.0, []

        # Build prompt with AC + relevant spec excerpt
        spec_excerpt = spec_content[:3000]  # Keep prompt manageable
        pairs_text = "\n".join([
            f"{p['id']}: {p['text']}" for p in ac_pairs
        ])

        user_prompt = f"""Check if these ACs are verified by the test file below.

ACCEPTANCE CRITERIA:
{pairs_text}

TEST FILE (excerpt):
{spec_excerpt}

Return JSON with verdict for each AC."""

        try:
            response = await self.llm.chat([
                {"role": "system", "content": FIDELITY_PROMPT},
                {"role": "user", "content": user_prompt}
            ], use_cache=False)  # Don't cache fidelity checks — content changes each retry

            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

            data = json.loads(cleaned.strip())
            results = data.get("results", [])

            scores = []
            issues = []
            for r in results:
                verdict = r.get("verdict", "NOT_VERIFIED")
                confidence = float(r.get("confidence", 0.5))
                ac_id = r.get("ac_id", "")

                if verdict == "VERIFIED":
                    scores.append(confidence)
                elif verdict == "PARTIAL":
                    scores.append(confidence * 0.5)
                    issues.append(ValidatorIssue(
                        type="low_fidelity",
                        ac_id=ac_id,
                        suggestion=f"{ac_id}: Test partially verifies the AC — strengthen the assertion to fully cover the expected outcome"
                    ))
                else:
                    scores.append(0.0)
                    issues.append(ValidatorIssue(
                        type="low_fidelity",
                        ac_id=ac_id,
                        suggestion=f"{ac_id}: No test found that verifies this AC — add a test block for this scenario"
                    ))

            avg_score = sum(scores) / len(scores) if scores else 0.5
            return round(avg_score, 4), issues

        except Exception as e:
            logger.warning(f"Fidelity scoring LLM failed: {e} — defaulting to 0.6")
            return 0.6, []

    def _empty_response(self, issue_key: str, retry_count: int, path_used: str) -> ValidatorResponse:
        return ValidatorResponse(
            issue_key=issue_key,
            overall_score=0.0,
            dimensions=ValidatorDimensions(coverage=0.0, balance=0.0, redundancy=0.0, fidelity=0.0),
            status=ValidatorStatus.NEEDS_REVIEW,
            issues=[ValidatorIssue(type="missing_ac", suggestion="No spec files were generated")],
            retry_count=retry_count,
            attempts_remaining=0,
            path_used=path_used,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def build_feedback_prompt(self, validator_response: ValidatorResponse) -> str:
        """Builds a feedback string to inject into the Coder's retry prompt."""
        issues_text = "\n".join([
            f"- [{i.type.upper()}] {f'AC: {i.ac_id} — ' if i.ac_id else ''}{i.suggestion}"
            for i in validator_response.issues
        ])
        return f"""VALIDATOR FEEDBACK (retry {validator_response.retry_count}/{MAX_RETRIES}):
Overall score: {validator_response.overall_score:.2f} (threshold: {THRESHOLD})
Coverage: {validator_response.dimensions.coverage:.2f} | Balance: {validator_response.dimensions.balance:.2f} | Redundancy: {validator_response.dimensions.redundancy:.2f} | Fidelity: {validator_response.dimensions.fidelity:.2f}

Issues to fix:
{issues_text}

Fix these issues in the regenerated test files. Do not remove existing passing tests."""


validator_agent = ValidatorAgent()
