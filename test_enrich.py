import requests
import json

audit_data = {
    "issue_key": "PROJ-1",
    "scenarios": [
        {"scenario": "clarity", "score": 0.4, "verdict": "REJECT", "flags": [
            {"line": 4, "type": "AMBIGUOUS_OUTCOME", "severity": "critical", "message": "The phrase 'I am logged in' is vague."},
            {"line": 4, "type": "MISSING_GIVEN", "severity": "major", "message": "Preconditions missing."}
        ]},
        {"scenario": "edge_cases", "score": 0.1, "verdict": "REJECT", "flags": [
            {"line": 4, "type": "MISSING_BOUNDARY", "severity": "critical", "message": "No edge cases covered."}
        ]}
    ],
    "overall_score": 0.25,
    "timestamp": "2026-04-11T06:04:09.176463+00:00"
}

enrich_res = requests.post(
    "http://localhost:8001/enrich",
    json={
        "story": {
            "issue_key": "PROJ-1",
            "title": "User Login",
            "description": "As a user I want to login",
            "acceptance_criteria": [
                "Given I am on login page When I click login Then I am logged in"
            ]
        },
        "audit": audit_data
    }
)

print("STATUS:", enrich_res.status_code)
print(json.dumps(enrich_res.json(), indent=2))