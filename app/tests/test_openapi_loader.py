import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.openapi.loader import OpenAPILoadError, load_openapi_schema


def test_load_openapi_schema_from_json_file(tmp_path: Path) -> None:
    schema_path = tmp_path / "openapi.json"
    schema_path.write_text(
        json.dumps({"openapi": "3.1.0", "info": {"title": "Test"}, "paths": {}}),
        encoding="utf-8",
    )

    schema = load_openapi_schema(file_path=str(schema_path))

    assert schema["openapi"] == "3.1.0"
    assert schema["info"]["title"] == "Test"


def test_load_openapi_schema_from_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"openapi": "3.1.0", "info": {"title": "Remote"}, "paths": {}}

    def fake_get(
        url: str,
        *,
        timeout: float,
        follow_redirects: bool,
    ) -> FakeResponse:
        assert url == "http://example.test/openapi.json"
        assert timeout == 10.0
        assert follow_redirects is True
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    schema = load_openapi_schema(openapi_url="http://example.test/openapi.json")

    assert schema["info"]["title"] == "Remote"


def test_load_openapi_schema_requires_one_source(tmp_path: Path) -> None:
    schema_path = tmp_path / "openapi.json"

    with pytest.raises(OpenAPILoadError, match="exactly one"):
        load_openapi_schema()

    with pytest.raises(OpenAPILoadError, match="exactly one"):
        load_openapi_schema(
            openapi_url="http://example.test/openapi.json",
            file_path=str(schema_path),
        )
