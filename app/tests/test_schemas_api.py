import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from demo_apis.normal_shop_api.main import app as normal_shop_app


def test_load_schema_endpoint_parses_local_openapi_file(tmp_path: Path) -> None:
    schema_path = tmp_path / "normal-openapi.json"
    schema_path.write_text(json.dumps(normal_shop_app.openapi()), encoding="utf-8")
    client = TestClient(app)

    response = client.post("/schemas/load", json={"file_path": str(schema_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoint_count"] == 6
    assert payload["schema"]["title"] == "Normal Shop API"
    assert {
        (endpoint["path"], endpoint["method"])
        for endpoint in payload["schema"]["endpoints"]
    } >= {
        ("/register", "post"),
        ("/login", "post"),
        ("/users/me", "get"),
        ("/items", "post"),
        ("/items/{item_id}", "get"),
        ("/items/{item_id}", "delete"),
    }


def test_load_schema_endpoint_reports_loader_errors() -> None:
    client = TestClient(app)

    response = client.post("/schemas/load", json={})

    assert response.status_code == 400
    assert "exactly one" in response.json()["detail"]
