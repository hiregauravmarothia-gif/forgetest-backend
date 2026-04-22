from datetime import datetime, timezone
from packages.schemas.prescan_schema import PrescanResponse, PrescanIssue, PrescanSeverity
from packages.schemas.requirement_schema import JiraStory


class PrescanAgent:
    def prescan(self, story: JiraStory) -> PrescanResponse:
        issues = []
        desc = story.description or ""
        desc_lower = desc.lower()
        acs = story.acceptance_criteria or []

        if len(acs) == 0:
            issues.append(PrescanIssue(
                code="NO_AC",
                message="No acceptance criteria defined"
            ))

        if len(desc.split()) < 10:
            issues.append(PrescanIssue(
                code="VAGUE_DESC",
                message="Description too short or vague"
            ))

        outcome_words = ['then', 'should', 'must', 'will', 'expect', 'result', 'output', 'return']
        if not any(word in desc_lower for word in outcome_words):
            issues.append(PrescanIssue(
                code="MISSING_OUTCOME",
                message="No expected outcome defined"
            ))

        actor_words = ['user', 'admin', 'customer', 'system', 'api', 'service', 'client', 'agent']
        if not any(word in desc_lower for word in actor_words):
            issues.append(PrescanIssue(
                code="MISSING_ACTOR",
                message="No user role or actor defined"
            ))

        action_words = ['click', 'submit', 'enter', 'select', 'login', 'logout', 'create', 'update',
                        'delete', 'view', 'open', 'close', 'search', 'filter', 'upload', 'download',
                        'send', 'receive', 'navigate', 'access', 'able to', 'can ', 'should be able']
        if not any(word in desc_lower for word in action_words):
            issues.append(PrescanIssue(
                code="MISSING_ACTION",
                message="No clear action defined"
            ))

        if len(acs) > 0:
            edge_words = ['invalid', 'error', 'fail', 'wrong', 'empty', 'null', 'missing',
                          'exceed', 'limit', 'boundary', 'negative', 'unauthorized', 'forbidden',
                          'timeout', 'expired', 'locked', 'duplicate']
            has_edge = any(any(word in ac.lower() for word in edge_words) for ac in acs)
            if not has_edge:
                issues.append(PrescanIssue(
                    code="NO_EDGE_CASES",
                    message="No edge cases in acceptance criteria"
                ))

        meaningless = {'test', 'fix', 'asdf', 'todo', 'tbd', 'na', 'n/a', 'wip', '...', 'placeholder'}
        if desc.strip().lower() in meaningless:
            issues.append(PrescanIssue(
                code="MEANINGLESS_DESC",
                message="Description is meaningless placeholder"
            ))

        issue_count = len(issues)

        if issue_count <= 1:
            severity = PrescanSeverity.LOW
        elif issue_count <= 3:
            severity = PrescanSeverity.MEDIUM
        else:
            severity = PrescanSeverity.HIGH

        return PrescanResponse(
            issue_key=story.issue_key,
            issue_count=issue_count,
            severity=severity,
            issues=issues,
            passed=issue_count == 0,
            timestamp=datetime.now(timezone.utc).isoformat()
        )


prescan_agent = PrescanAgent()