import json
from pathlib import Path
from typing import Any

import httpx


class OpenAPILoadError(ValueError):
    """Raised when an OpenAPI schema cannot be loaded or decoded."""


def load_openapi_schema(
    *,
    openapi_url: str | None = None,
    file_path: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    if bool(openapi_url) == bool(file_path):
        raise OpenAPILoadError("Provide exactly one of openapi_url or file_path.")

    if openapi_url:
        schema = _load_from_url(openapi_url, timeout_seconds)
    else:
        schema = _load_from_file(Path(str(file_path)))

    _validate_openapi_document(schema)
    return schema


def _load_from_url(openapi_url: str, timeout_seconds: float) -> dict[str, Any]:
    try:
        response = httpx.get(openapi_url, timeout=timeout_seconds, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise OpenAPILoadError(
            f"OpenAPI URL returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.RequestError as exc:
        raise OpenAPILoadError(f"Could not connect to OpenAPI URL: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAPILoadError("OpenAPI URL did not return valid JSON.") from exc

    if not isinstance(payload, dict):
        raise OpenAPILoadError("OpenAPI URL returned JSON, but not a JSON object.")
    return payload


def _load_from_file(file_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OpenAPILoadError(f"OpenAPI file was not found: {file_path}") from exc
    except OSError as exc:
        raise OpenAPILoadError(f"Could not read OpenAPI file: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAPILoadError("OpenAPI file did not contain valid JSON.") from exc

    if not isinstance(payload, dict):
        raise OpenAPILoadError("OpenAPI file contained JSON, but not a JSON object.")
    return payload


def _validate_openapi_document(schema: dict[str, Any]) -> None:
    if "openapi" not in schema and "swagger" not in schema:
        raise OpenAPILoadError("Schema is missing an OpenAPI version field.")
    if not isinstance(schema.get("paths"), dict):
        raise OpenAPILoadError("Schema is missing a valid paths object.")
