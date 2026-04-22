import requests
import json

res = requests.post(
    "http://localhost:8001/pipeline",
    json={
        "story": {
            "issue_key": "PROJ-1",
            "title": "User Login",
            "description": "As a user I want to login",
            "acceptance_criteria": [
                "Given I am on login page When I click login Then I am logged in"
            ]
        }
    },
    timeout=300
)

print("STATUS:", res.status_code)
data = res.json()
print("PIPELINE STATUS:", data.get("pipeline_status"))
print("DURATION:", data.get("duration_ms"), "ms")

audit = data.get("audit")
architect = data.get("architect")
coder = data.get("coder")

if audit:
    print("AUDIT SCORE:", audit.get("overall_score"))
else:
    print("AUDIT: Failed/None")

if architect:
    print("ACs PROPOSED:", len(architect.get("proposed_acs", [])))
else:
    print("ARCHITECT: Failed/None")

if coder:
    print("FILES GENERATED:", len(coder.get("files", [])))
    for f in coder["files"]:
        print(f"  - {f['path']}")
else:
    print("CODER: Failed/None")