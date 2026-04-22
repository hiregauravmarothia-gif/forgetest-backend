import requests
import json

architect_data = {
    "issue_key": "PROJ-1",
    "hidden_paths": {
        "auth_permissions": ["Account locked after N failed attempts"],
        "input_boundaries": ["Empty string inputs", "SQL injection strings"],
        "network_async": ["Timeout during authentication"],
        "data_state": ["Login with unverified email"],
        "ux_edge": ["Back-button behavior after login"]
    },
    "proposed_acs": [
        {"id": "AC-1", "given": "a registered user with valid credentials exists", "when": "they enter correct username and password and submit", "then": "they are redirected to the dashboard", "tag": "HAPPY"},
        {"id": "AC-2", "given": "a user enters an incorrect password", "when": "they attempt to login", "then": "access is denied and error message shown", "tag": "SAD"},
        {"id": "AC-3", "given": "a user submits SQL injection in username", "when": "they attempt to login", "then": "input is sanitized and no database error exposed", "tag": "SECURITY"}
    ],
    "gherkin": "Feature: User Authentication\n  Scenario: Successful login\n    Given a registered user exists\n    When they submit valid credentials\n    Then they are redirected to dashboard",
    "assumptions": ["ASSUMPTION: Login redirects to /dashboard"],
    "timestamp": "2026-04-11T06:32:29.542701+00:00"
}

res = requests.post(
    "http://localhost:8001/generate",
    json={
        "story": {
            "issue_key": "PROJ-1",
            "title": "User Login",
            "description": "As a user I want to login",
            "acceptance_criteria": [
                "Given I am on login page When I click login Then I am logged in"
            ]
        },
        "architect_response": architect_data
    }
)

print("STATUS:", res.status_code)
data = res.json()
if res.status_code == 200:
    print("\nFILES GENERATED:")
    for f in data.get("files", []):
        print(f"\n--- {f['path']} ({f['type']}) ---")
        print(f['content'][:300])
    print("\nMANIFEST:", json.dumps(data.get("manifest", {}), indent=2))
else:
    print("ERROR:", json.dumps(data, indent=2))