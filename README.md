# APITestAgent

APITestAgent is an internship portfolio project for building an LLM-powered backend API testing assistant. The current version includes FastAPI app setup, configuration management, a health endpoint, OpenAPI schema loading/parsing, deterministic test planning, HTTP execution, response validation, workflow trace logging, in-memory run history, pytest setup, and Docker support.

The agent workflow, HTTP execution tools, validation, diagnosis, and reports will be added in later steps.

## Requirements

- Python 3.11+
- Docker and Docker Compose, optional for containerized runs

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Run The API

```bash
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Load and parse an OpenAPI schema:

```bash
curl -X POST http://localhost:8000/schemas/load ^
  -H "Content-Type: application/json" ^
  -d "{\"openapi_url\":\"http://localhost:8001/openapi.json\"}"
```

Run the LLM agent workflow:

```bash
curl -X POST http://localhost:8000/runs ^
  -H "Content-Type: application/json" ^
  -d "{\"base_url\":\"http://localhost:8002\",\"openapi_url\":\"http://localhost:8002/openapi.json\",\"allow_mutation\":true}"
```

By default, `POST /runs` uses the LLM agent loop: Plan -> Action -> Observe -> Reflect. The model is only allowed to call local function tools such as `submit_test_plan` and `submit_reflection`. APITestAgent validates tool arguments with Pydantic, then backend code executes HTTP requests and computes pass/fail.

You can also create a local `.env` file from `.env.example` and fill in your own key. `.env` is ignored by Git.

```bash
set DEEPSEEK_API_KEY=your_key
set LLM_BASE_URL=https://api.deepseek.com
set LLM_MODEL=deepseek-chat
```

Fetch reports for a completed run:

```bash
curl http://localhost:8000/runs/{run_id}/report.json
curl http://localhost:8000/runs/{run_id}/report.md
```

## Run Tests

```bash
pytest
```

## Run With Docker

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.

## Run Demo APIs

Start the correct demo shop API:

```bash
uvicorn demo_apis.normal_shop_api.main:app --reload --port 8001
```

Start the intentionally buggy demo shop API:

```bash
uvicorn demo_apis.buggy_shop_api.main:app --reload --port 8002
```

Both demo services expose OpenAPI schemas:

```bash
curl http://localhost:8001/openapi.json
curl http://localhost:8002/openapi.json
```
