import requests
import json

res = requests.post(
    "http://localhost:8001/api/v1/pipeline",
    json={
        "story": {
            "issue_key": "PROJ-1",
            "title": "User Login",
            "description": "As a user I want to login",
            "acceptance_criteria": [
                "Given I am on login page When I click login Then I am logged in"
            ]
        },
        "create_pr": True,
        "github_repo": "hiregauravmarothia-gif/forgetest-test"
    },
    timeout=300
)

print("STATUS:", res.status_code)
data = res.json()
print("PIPELINE STATUS:", data.get("pipeline_status"))
print("DURATION:", round(data.get("duration_ms", 0)/1000, 1), "seconds")
print("ERROR:", data.get("error"))

audit = data.get("audit")
architect = data.get("architect")
coder = data.get("coder")
pr = data.get("pr_result")

print(f"AUDIT SCORE: {audit.get('overall_score') if audit else 'FAILED'}")
print(f"ACs PROPOSED: {len(architect.get('proposed_acs', [])) if architect else 'FAILED'}")
print(f"FILES GENERATED: {len(coder.get('files', [])) if coder else 'FAILED'}")

if pr:
    print(f"\n🎉 PR CREATED!")
    print(f"PR URL: {pr.get('pr_url')}")
    print(f"Branch: {pr.get('branch_name')}")
    print(f"Files committed: {pr.get('files_committed')}")
else:
    print("\nPR: Not created")