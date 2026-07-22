from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PromptDocument(BaseModel):
    id: str
    title: str
    description: str = ""
    prompt: str
    category: str
    categories: list[str] = Field(default_factory=list)
    preview_image: str = ""
    source_media: list[str] = Field(default_factory=list)
    need_reference_images: bool = False
    arguments: list[dict[str, Any]] = Field(default_factory=list)
    language: str = "en"
    content_hash: str = ""
    status: str = "active"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    categories: list[str] = Field(default_factory=list)
    need_reference_images: bool | None = None
    use_dense: bool = True


class SearchHit(BaseModel):
    document: PromptDocument
    score: float
    lexical_rank: int | None = None
    dense_rank: int | None = None
    dense_score: float | None = None
    matched_by: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    expanded_query: str
    inferred_categories: list[str]
    dense_enabled: bool
    dense_error: str | None = None
    total: int
    results: list[SearchHit]


class RecommendRequest(SearchRequest):
    explain: bool = True


class RecommendResponse(SearchResponse):
    recommendation: str | None = None


class RemixRequest(BaseModel):
    prompt_id: str
    requirement: str = Field(min_length=1, max_length=10000)


class RemixResponse(BaseModel):
    prompt_id: str
    source_title: str
    remixed_prompt: str
    generated: bool


class RequirementSubject(BaseModel):
    description: str = Field(default="", max_length=1000)
    action: str = Field(default="", max_length=500)


class RequirementCamera(BaseModel):
    shot: str = Field(default="", max_length=200)
    lens: str = Field(default="", max_length=200)


class RequirementText(BaseModel):
    content: str = Field(default="", max_length=2000)
    must_be_exact: bool = True


class RequirementReference(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    role: str = Field(default="style", max_length=100)
    preserve: list[str] = Field(default_factory=list, max_length=20)


class RequirementOutput(BaseModel):
    model: str = Field(default="gpt-image-2", max_length=100)
    ratio: str = Field(default="1:1", max_length=20)
    size: str = Field(default="1024x1024", max_length=30)
    quality: Literal["low", "medium", "high", "auto"] = "low"
    count: int = Field(default=1, ge=1, le=4)
    format: Literal["png", "jpeg", "webp"] = "png"
    prompt_language: Literal["zh", "en"] = "zh"


class RequirementSpec(BaseModel):
    raw_request: str = Field(min_length=1, max_length=10000)
    use_case: str = Field(default="", max_length=200)
    subject: RequirementSubject = Field(default_factory=RequirementSubject)
    environment: str = Field(default="", max_length=1000)
    style: list[str] = Field(default_factory=list, max_length=30)
    composition: str = Field(default="", max_length=500)
    camera: RequirementCamera = Field(default_factory=RequirementCamera)
    lighting: list[str] = Field(default_factory=list, max_length=30)
    palette: list[str] = Field(default_factory=list, max_length=30)
    text: RequirementText = Field(default_factory=RequirementText)
    references: list[RequirementReference] = Field(default_factory=list, max_length=10)
    negative_constraints: list[str] = Field(default_factory=list, max_length=50)
    output: RequirementOutput = Field(default_factory=RequirementOutput)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    missing_fields: list[str] = Field(default_factory=list, max_length=30)
    confidence: float = Field(default=0.0, ge=0, le=1)
    schema_version: int = Field(default=1, ge=1)


class UnderstandRequirementRequest(BaseModel):
    raw_request: str = Field(min_length=1, max_length=10000)
    use_case: str = Field(default="", max_length=200)
    target_model: str = Field(default="gpt-image-2", max_length=100)
    ratio: str = Field(default="1:1", max_length=20)
    text_content: str = Field(default="", max_length=2000)
    reference_mode: Literal["auto", "required", "none"] = "auto"
    output_language: Literal["zh", "en"] = "zh"


class ConfirmRequirementRequest(BaseModel):
    requirement_spec: RequirementSpec


class WorkflowRun(BaseModel):
    id: str
    status: Literal["requirements_ready", "requirements_confirmed", "interrupted"]
    requirement_spec: RequirementSpec
    generated: bool
    cached: bool = False
    model: str = ""
    schema_version: int = 1
    created_at: str
    updated_at: str
    confirmed_at: str | None = None
