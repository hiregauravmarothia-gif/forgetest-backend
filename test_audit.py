import requests
import json

audit_res = requests.post(
    "http://localhost:8001/audit",
    json={
        "issue_key": "PROJ-1",
        "title": "User Login",
        "description": "As a user I want to login",
        "acceptance_criteria": [
            "Given I am on login page When I click login Then I am logged in"
        ]
    }
)

print("STATUS:", audit_res.status_code)
print("RESPONSE:", json.dumps(audit_res.json(), indent=2))