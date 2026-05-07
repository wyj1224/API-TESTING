# APITestAgent

APITestAgent is an internship portfolio project: an LLM-powered backend API testing assistant for black-box API testing.

It reads an OpenAPI schema, generates structured API test plans, executes real HTTP requests against a running API service, validates responses deterministically, diagnoses failures, and generates reproducible JSON / Markdown reports with visible agent traces.

This is not a RAG project. The core workflow is:

```text
Plan tests -> Execute HTTP calls -> Observe responses -> Validate results -> Diagnose failures -> Generate report
```

## What This Project Demonstrates

- FastAPI backend engineering
- OpenAPI schema loading and parsing
- LLM function calling / tool calling
- Structured LLM output validated by Pydantic
- HTTP request execution with `httpx`
- Deterministic pass/fail validation
- Rule-based failure diagnosis
- Plan -> Action -> Observe -> Reflect agent trace
- JSON and Markdown report generation
- Demo APIs for reproducible evaluation
- Docker-based local deployment

## Tech Stack

- Python 3.11+
- FastAPI
- Pydantic v2
- httpx
- pytest
- DeepSeek / OpenAI-compatible Chat Completions API
- Docker / Docker Compose

## Project Structure

```text
app/
  api/                 FastAPI route modules
  agent/               planner, LLM function-calling loop, workflow schemas
  core/                runtime configuration
  openapi/             OpenAPI loader, parser, and parsed schema models
  reports/             JSON and Markdown report generation
  tools/               HTTP executor, response validator, diagnoser
  tests/               pytest test suite
demo_apis/
  normal_shop_api/     correct demo API
  buggy_shop_api/      intentionally buggy demo API
eval/
  expected_failures.json
```

## Local Setup

Create and activate a Python environment, then install the project:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

If your VS Code environment already has a Python interpreter, you can also run commands through that interpreter:

```powershell
& "D:\python\envs\fastapi\python.exe" -m pip install -e ".[dev]"
```

## LLM Configuration

Create a `.env` file in the project root. `.env` is ignored by Git.

```env
APP_NAME=APITestAgent
APP_ENV=development
LOG_LEVEL=INFO

DEEPSEEK_API_KEY=your_deepseek_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=20
```

The config also accepts `LLM_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL`.

The LLM participates in:

- generating a structured test plan through function calling
- producing a reflection summary through function calling
- improving test case names, payloads, and explanations

The LLM does not:

- execute HTTP requests
- parse JSON
- validate response schemas
- decide pass/fail
- write to storage

Those parts are handled by deterministic backend tools.

## Run The Services

Start APITestAgent:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Or with an explicit interpreter:

```powershell
& "D:\python\envs\fastapi\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the correct demo API:

```powershell
python -m uvicorn demo_apis.normal_shop_api.main:app --reload --port 8001
```

Start the intentionally buggy demo API:

```powershell
python -m uvicorn demo_apis.buggy_shop_api.main:app --reload --port 8002
```

Both demo APIs expose OpenAPI schemas:

```powershell
curl.exe http://localhost:8001/openapi.json
curl.exe http://localhost:8002/openapi.json
```

## Health Check

```powershell
curl.exe http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Load An OpenAPI Schema

```powershell
$body = @{
  openapi_url = "http://localhost:8002/openapi.json"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/schemas/load" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

## Run APITestAgent

Run against the buggy demo API:

```powershell
$body = @{
  base_url = "http://localhost:8002"
  openapi_url = "http://localhost:8002/openapi.json"
  allow_mutation = $true
} | ConvertTo-Json

$result = Invoke-RestMethod -Uri "http://localhost:8000/runs" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

Inspect the result:

```powershell
$result.summary | ConvertTo-Json -Depth 10
$result.reflections | ConvertTo-Json -Depth 10
$result.trace.steps | ConvertTo-Json -Depth 10
```

Fetch reports:

```powershell
Invoke-RestMethod "http://localhost:8000/runs/$($result.run_id)/report.json"
curl.exe "http://localhost:8000/runs/$($result.run_id)/report.md"
```

## Run Request Options

`POST /runs` accepts:

```json
{
  "base_url": "http://localhost:8002",
  "openapi_url": "http://localhost:8002/openapi.json",
  "max_endpoints": 10,
  "test_types": ["happy_path", "missing_required_field", "wrong_type", "not_found", "unauthorized_access"],
  "allow_mutation": true,
  "use_llm_planner": true,
  "use_agent_loop": true,
  "max_agent_iterations": 1
}
```

Notes:

- `allow_mutation=true` is required for POST / DELETE style tests against non-local APIs.
- `use_agent_loop=true` runs the full Plan -> Action -> Observe -> Reflect loop.
- `use_llm_planner=false` can be used with the non-agent workflow as a deterministic fallback.

## Reports And Trace

Each run returns:

- `summary.total`, `summary.passed`, `summary.failed`
- failed cases with validation errors and diagnosis
- executed case details, including latency and response body
- visible trace steps such as `load_schema`, `plan_tests`, `execute_case`, `validate_response`, `diagnose_failure`, `agent_reflect`
- optional LLM reflection output

Available report endpoints:

```text
GET /runs/{run_id}/report.json
GET /runs/{run_id}/report.md
```

## Docker

Build and start APITestAgent:

```powershell
docker compose up --build
```

The service will be available at:

```text
http://localhost:8000
```

If you want the containerized app to use your LLM key, add the LLM environment variables to `docker-compose.yml` or pass them through your Docker environment.

## Tests

```powershell
pytest
```

The test suite covers:

- health endpoint
- demo APIs
- OpenAPI loader and parser
- deterministic planner
- LLM planner fallback and validation
- LLM reflector
- HTTP execution and response validation
- failure diagnosis
- workflow traces
- report generation

## Safety Notes

- Prefer local APIs for testing.
- Do not run destructive tests against public APIs unless explicitly intended.
- Do not send real credentials, cookies, or secrets to the LLM.
- Authorization headers and secrets are redacted in traces and reports.
- Pass/fail is always computed by backend validation logic, not by the LLM.
