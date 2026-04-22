import asyncio
import logging
from datetime import datetime, timezone
from packages.schemas import PRResult
from packages.schemas.coder_schema import CoderResponse
from packages.schemas.architect_schema import ArchitectResponse
from apps.api.config import settings

logger = logging.getLogger(__name__)


class GitHubService:
    def __init__(self):
        self.token = settings.github_token
        self.default_repo = settings.github_default_repo
        self._client = None
        
        if not self.token:
            logger.warning("GITHUB_TOKEN not set — PR creation disabled")

    @property
    def client(self):
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN not configured")
        if self._client is None:
            from github import Github
            self._client = Github(self.token)
        return self._client

    async def create_pr(
        self,
        issue_key: str,
        coder_response: CoderResponse,
        architect_response: ArchitectResponse,
        repo: str = "",
    ) -> PRResult:
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN not configured — PR creation disabled")
        
        repo_str = repo or self.default_repo
        parts = repo_str.split("/")
        owner, repo_name = parts[0], parts[1]
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._create_pr_sync, issue_key, coder_response, architect_response, owner, repo_name
        )

    def _create_pr_sync(
        self,
        issue_key: str,
        coder_response: CoderResponse,
        architect_response: ArchitectResponse,
        owner: str,
        repo_name: str,
    ) -> PRResult:
        from github.GithubException import GithubException

        g = self.client
        repo = g.get_repo(f"{owner}/{repo_name}")

        # Base branch detect karo
        base_branch = repo.default_branch or "main"
        logger.info(f"Using base branch: {base_branch}")

        # SHA lo — format: heads/branch_name (refs/ prefix nahi)
        try:
            base_ref = repo.get_git_ref(f"heads/{base_branch}")
        except GithubException as e:
            logger.warning(f"Branch {base_branch} not found: {e}, trying main...")
            try:
                base_ref = repo.get_git_ref("heads/main")
                base_branch = "main"
            except GithubException:
                base_ref = repo.get_git_ref("heads/master")
                base_branch = "master"

        base_sha = base_ref.object.sha
        logger.info(f"Base SHA: {base_sha}")

        # New branch banao
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        branch_name = f"forgetest/{issue_key}-{ts}"
        repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)
        logger.info(f"Created branch: {branch_name}")

        # Files commit karo
        files_count = 0
        for file in coder_response.files:
            try:
                try:
                    existing = repo.get_contents(file.path, ref=branch_name)
                    repo.update_file(
                        file.path,
                        f"ForgeTest: {issue_key}",
                        file.content,
                        existing.sha,
                        branch=branch_name
                    )
                except GithubException:
                    repo.create_file(
                        file.path,
                        f"ForgeTest: {issue_key}",
                        file.content,
                        branch=branch_name
                    )
                files_count += 1
                logger.info(f"Committed: {file.path}")
            except Exception as e:
                logger.warning(f"Failed to commit {file.path}: {e}")
                continue

        # Draft PR banao
        body = self._build_pr_body(coder_response, architect_response)
        pr = repo.create_pull(
            title=f"ForgeTest: [{issue_key}] Automated Test Generation",
            body=body,
            head=branch_name,
            base=base_branch,
            draft=True,
        )
        logger.info(f"PR created: {pr.html_url}")

        return PRResult(
            pr_url=pr.html_url,
            branch_name=branch_name,
            files_committed=files_count,
            pr_number=pr.number,
            status="DRAFT",
        )

    def _build_pr_body(self, coder_response: CoderResponse, architect_response: ArchitectResponse) -> str:
        coverage = "\n".join([
            f"| {c.scenario_tag} | {c.status} | {c.output_file} |"
            for c in coder_response.manifest.coverage
        ]) or "| - | - | - |"

        assumptions = "\n".join([f"- {a}" for a in architect_response.assumptions]) or "None"
        locators = "\n".join([
            f"- **{k}**: {v}"
            for k, v in coder_response.manifest.locator_inventory.items()
        ]) or "No locators"

        return f"""## ForgeTest — Automated Test Generation
> Generated from **{coder_response.issue_key}**

### Coverage
| Scenario Tag | Status | Output File |
|---|---|---|
{coverage}

### Assumptions
{assumptions}

### Locator Inventory
<details><summary>View all locators</summary>

{locators}
</details>

---
*Generated by ForgeTest Pipeline*
"""


github_service = GitHubService()