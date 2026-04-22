# ForgeTest

A Jira-native AI platform with 3 agents that transform user stories into production-ready Playwright tests.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ForgeTest API                              │
├─────────────────────────────────────────────────────────────────┤
│  POST /api/v1/audit    →  Auditor Agent (scores quality)        │
│  POST /api/v1/enrich    →  Architect Agent (generates Gherkin)  │
│  POST /api/v1/generate   →  Coder Agent (Playwright tests)          │
│  POST /api/v1/pipeline   →  Full pipeline (audit → enrich → gen)  │
│  POST /api/v1/github/pr →  Create GitHub PR                    │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   LLM Service       │
                    │ (OpenRouter/NVIDIA) │
                    └─────────────────────┘
```

## Tech Stack

- **Backend**: FastAPI (Python 3.11+)
- **LLM**: OpenRouter API or NVIDIA API
- **Primary Model**: gemini/gemini-2.5-flash (configurable)
- **Testing**: PyGithub (for PR creation)

## Setup

1. Clone the repository
2. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables in `.env`:
   ```
   OPENROUTER_API_KEY=your_key_here
   PRIMARY_MODEL=gemini/gemini-2.5-flash
   ```
5. Run the server:
   ```bash
   uvicorn apps.api.main:app --reload --port 8001
   ```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|--------|-------------|
| `OPENROUTER_API_KEY` | Yes* | - | OpenRouter API key |
| `GEMINI_API_KEY` | Yes* | - | Google Gemini API key |
| `NVIDIA_API_KEY` | Yes* | - | NVIDIA API key |
| `PRIMARY_MODEL` | No | gemini/gemini-2.5-flash | LLM model to use |
| `LOG_LEVEL` | No | INFO | Logging level |
| `APP_ENV` | No | development | Environment |
| `CORS_ORIGINS` | No | * | CORS origins |
| `GITHUB_TOKEN` | For PR creation | - | GitHub PAT |
| `GITHUB_DEFAULT_REPO` | No | owner/repo | Default repo |

*At least one API key required

## API Endpoints

### Health Check
```bash
curl http://localhost:8001/health
```

### Audit (Score Quality)
```bash
curl -X POST http://localhost:8001/api/v1/audit \
  -H "Content-Type: application/json" \
  -d '{
    "issue_key": "PROJ-123",
    "title": "User login",
    "description": "Users can log in with email and password",
    "acceptance_criteria": ["Login with valid credentials"]
  }'
```

### Enrich (Generate Gherkin)
```bash
curl -X POST http://localhost:8001/api/v1/enrich \
  -H "Content-Type: application/json" \
  -d '{
    "story": {...},
    "audit": {...}
  }'
```

### Generate (Create Tests)
```bash
curl -X POST http://localhost:8001/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{
    "story": {...},
    "architect_response": {...}
  }'
```

### Pipeline (Full Flow)
```bash
curl -X POST http://localhost:8001/api/v1/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "story": {
      "issue_key": "PROJ-123",
      "title": "User login",
      "description": "Users can log in",
      "acceptance_criteria": ["Login succeeds"]
    }
  }'
```

### Pipeline with GitHub PR
```bash
curl -X POST http://localhost:8001/api/v1/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "story": {...},
    "github_repo": "owner/my-repo",
    "create_pr": true
  }'
```

### Create GitHub PR
```bash
curl -X POST http://localhost:8001/api/v1/github/pr \
  -H "Content-Type: application/json" \
  -d '{
    "issue_key": "PROJ-123",
    "repo": "owner/repo",
    "coder_response": {...},
    "architect_response": {...}
  }'
```

## Response Schemas

### AuditResponse
```json
{
  "issue_key": "PROJ-123",
  "scenarios": [{
    "scenario": "clarity",
    "score": 0.85,
    "verdict": "PASS",
    "flags": []
  }],
  "overall_score": 0.85,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### ArchitectResponse
```json
{
  "issue_key": "PROJ-123",
  "hidden_paths": {...},
  "proposed_acs": [...],
  "gherkin": "Feature: ...",
  "assumptions": [],
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### CoderResponse
```json
{
  "issue_key": "PROJ-123",
  "files": [{"type": "spec", "path": "...", "content": "..."}],
  "manifest": {...},
  "locator_gaps": [],
  "skipped_scenarios": [],
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### PipelineResponse
```json
{
  "issue_key": "PROJ-123",
  "audit": {...},
  "architect": {...},
  "coder": {...},
  "pipeline_status": "COMPLETE",
  "duration_ms": 1500.0,
  "timestamp": "2024-01-01T00:00:00Z",
  "pr_result": {...}
}
```

## Project Structure

```
forgetest/
├── apps/
│   └── api/
│       ├── main.py          # FastAPI app
│       ├── config.py         # Settings
│       └── routes/
│           ├── audit.py     # /audit endpoint
│           ├── enrich.py    # /enrich endpoint
│           ├── generate.py  # /generate endpoint
│           ├── pipeline.py  # /pipeline endpoint
│           └── github.py   # /github/pr endpoint
├── packages/
│   ├── agents/
│   │   ├── auditor.py       # Auditor Agent
│   │   ├── architect.py    # Architect Agent
│   │   └── coder.py       # Coder Agent
│   ├── schemas/
│   │   ├── requirement.py # JiraStory
│   │   ├── audit.py       # AuditResponse
│   │   ├── architect.py   # ArchitectResponse
│   │   ├── coder.py      # CoderResponse
│   │   ├── pipeline.py   # PipelineRequest/Response
│   │   └── github.py    # PRResult
│   └── services/
│       ├── llm.py         # LLM service
│       └── github.py       # GitHub service
├── .env.example
├── requirements.txt
└── README.md
```

## License

MIT