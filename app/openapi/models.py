from typing import Any, Literal

from pydantic import BaseModel, Field


HttpMethod = Literal["get", "post", "put", "patch", "delete", "options", "head", "trace"]
ParameterLocation = Literal["query", "path", "header", "cookie"]


class ParameterDefinition(BaseModel):
    name: str
    location: ParameterLocation = Field(alias="in")
    required: bool = False
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    description: str | None = None

    model_config = {"populate_by_name": True}


class RequestBodyDefinition(BaseModel):
    required: bool = False
    content: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ResponseDefinition(BaseModel):
    status_code: str
    description: str | None = None
    content: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SecurityRequirement(BaseModel):
    schemes: dict[str, list[str]]


class EndpointDefinition(BaseModel):
    path: str
    method: HttpMethod
    operation_id: str | None = None
    parameters: list[ParameterDefinition] = Field(default_factory=list)
    request_body: RequestBodyDefinition | None = None
    responses: list[ResponseDefinition] = Field(default_factory=list)
    security: list[SecurityRequirement] = Field(default_factory=list)
    requires_auth: bool = False


class ParsedOpenAPISchema(BaseModel):
    title: str | None = None
    version: str | None = None
    openapi_version: str | None = None
    components: dict[str, Any] = Field(default_factory=dict)
    endpoints: list[EndpointDefinition]


class SchemaLoadRequest(BaseModel):
    openapi_url: str | None = None
    file_path: str | None = None


class SchemaLoadResponse(BaseModel):
    source: str
    endpoint_count: int
    schema_: ParsedOpenAPISchema = Field(alias="schema")

    model_config = {"populate_by_name": True}
