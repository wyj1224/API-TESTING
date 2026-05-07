from fastapi import APIRouter, HTTPException, status

from app.openapi.loader import OpenAPILoadError, load_openapi_schema
from app.openapi.models import SchemaLoadRequest, SchemaLoadResponse
from app.openapi.parser import parse_openapi_schema


router = APIRouter(prefix="/schemas", tags=["schemas"])


@router.post("/load", response_model=SchemaLoadResponse)
def load_schema(payload: SchemaLoadRequest) -> SchemaLoadResponse:
    try:
        raw_schema = load_openapi_schema(
            openapi_url=payload.openapi_url,
            file_path=payload.file_path,
        )
    except OpenAPILoadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    parsed_schema = parse_openapi_schema(raw_schema)
    source = payload.openapi_url or str(payload.file_path)
    return SchemaLoadResponse(
        source=str(source),
        endpoint_count=len(parsed_schema.endpoints),
        schema=parsed_schema,
    )
