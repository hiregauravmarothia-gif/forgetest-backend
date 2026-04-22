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
        "create_pr": False
    },
    timeout=600
)

data = res.json()
print("STATUS:", res.status_code)
print("PIPELINE STATUS:", data.get("pipeline_status"))
print("DURATION:", round(data.get("duration_ms", 0)/1000, 1), "seconds")
print("ERROR:", data.get("error"))  # ← error detail


audit = data.get("audit")
architect = data.get("architect")
coder = data.get("coder")

print(f"AUDIT SCORE: {audit.get('overall_score') if audit else 'FAILED'}")
print(f"ACs PROPOSED: {len(architect.get('proposed_acs', [])) if architect else 'FAILED'}")
print(f"FILES GENERATED: {len(coder.get('files', [])) if coder else 'FAILED'}")
if coder:
    for f in coder["files"]:
        print(f"  - {f['path']}")