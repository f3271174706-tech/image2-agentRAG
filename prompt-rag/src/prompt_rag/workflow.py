from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from .database import PromptStore
from .generation import ChatGenerator
from .models import (
    RequirementCamera,
    RequirementOutput,
    RequirementSpec,
    RequirementSubject,
    RequirementText,
    UnderstandRequirementRequest,
    WorkflowRun,
)


SIZE_BY_RATIO = {
    "1:1": "1024x1024",
    "16:9": "1536x864",
    "9:16": "864x1536",
    "4:3": "1536x1152",
    "3:4": "1152x1536",
}

STYLE_TERMS = (
    "现代电影感",
    "电影感",
    "赛博朋克",
    "像素艺术",
    "像素",
    "复古",
    "极简",
    "写实",
    "动漫",
    "水彩",
    "油画",
    "3D",
)

USE_CASE_TERMS = (
    ("游戏", "game-asset"),
    ("海报", "poster-flyer"),
    ("产品", "product-marketing"),
    ("电商", "ecommerce-main-image"),
    ("头像", "profile-avatar"),
    ("分镜", "comic-storyboard"),
    ("信息图", "infographic-edu-visual"),
    ("网页", "app-web-design"),
)

CONFIRMATION_MISSING_FIELDS = {
    "use_case",
    "subject.description",
    "subject.action",
    "environment",
    "composition",
    "references",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("requirement response does not contain JSON")
    payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("requirement response must be an object")
    return payload


def _strings(value: Any, limit: int = 30) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = " ".join(item.split()).strip()
            if cleaned and cleaned not in result:
                result.append(cleaned[:300])
        if len(result) >= limit:
            break
    return result


class RequirementUnderstander:
    def __init__(self, store: PromptStore, generator: ChatGenerator | None):
        self.store = store
        self.generator = generator

    @property
    def enabled(self) -> bool:
        return bool(self.generator and self.generator.enabled)

    @property
    def model(self) -> str:
        if self.enabled and self.generator is not None:
            return self.generator.model
        return "rules-v1"

    @staticmethod
    def _output(request: UnderstandRequirementRequest) -> RequirementOutput:
        model = request.target_model.strip() or "gpt-image-2"
        if model.casefold().replace(" ", "-") == "gpt-image-2":
            model = "gpt-image-2"
        return RequirementOutput(
            model=model,
            ratio=request.ratio,
            size=SIZE_BY_RATIO.get(request.ratio, "1024x1024"),
            prompt_language=request.output_language,
        )

    @classmethod
    def _fallback(cls, request: UnderstandRequirementRequest) -> RequirementSpec:
        raw = " ".join(request.raw_request.split()).strip()
        style = [term for term in STYLE_TERMS if term.casefold() in raw.casefold()]
        use_case = request.use_case.strip()
        if not use_case:
            use_case = next(
                (label for term, label in USE_CASE_TERMS if term in raw), ""
            )
        missing = []
        if not use_case:
            missing.append("use_case")
        missing.extend(["subject.action", "environment", "composition"])
        if request.reference_mode == "required":
            missing.append("references")
        return RequirementSpec(
            raw_request=raw,
            use_case=use_case,
            subject=RequirementSubject(description=raw),
            style=style,
            text=RequirementText(content=request.text_content),
            output=cls._output(request),
            assumptions=(
                ["尚未解析参考图片的视觉内容"]
                if request.reference_mode == "required"
                else []
            ),
            missing_fields=missing,
            confidence=0.45,
        )

    def _cache_key(self, request: UnderstandRequirementRequest) -> str:
        canonical = json.dumps(
            {"analyzer_version": 4, "request": request.model_dump()},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def understand(
        self, request: UnderstandRequirementRequest
    ) -> tuple[RequirementSpec, bool, bool]:
        fallback = self._fallback(request)
        if not self.enabled:
            return fallback, False, False

        cache_key = self._cache_key(request)
        cached = self.store.get_requirement_analysis(cache_key, self.model)
        if cached:
            try:
                return RequirementSpec.model_validate_json(cached), True, True
            except ValidationError:
                pass

        assert self.generator is not None
        raw = self.generator.understand_requirement(
            {
                "raw_request": request.raw_request,
                "explicit_fields": {
                    "use_case": request.use_case,
                    "target_model": request.target_model,
                    "ratio": request.ratio,
                    "text_content": request.text_content,
                    "reference_mode": request.reference_mode,
                    "output_language": request.output_language,
                },
            }
        )
        try:
            parsed = _extract_json(raw)
            subject = parsed.get("subject") if isinstance(parsed.get("subject"), dict) else {}
            camera = parsed.get("camera") if isinstance(parsed.get("camera"), dict) else {}
            parsed_use_case = str(parsed.get("use_case", ""))[:200].strip()
            resolved_use_case = request.use_case.strip() or parsed_use_case or fallback.use_case
            assumptions = _strings(parsed.get("assumptions"))
            missing_fields = [
                item
                for item in _strings(parsed.get("missing_fields"))
                if item in CONFIRMATION_MISSING_FIELDS
            ]
            if not parsed_use_case and not request.use_case.strip() and fallback.use_case:
                assumptions.append(f"根据需求关键词推断用途为 {fallback.use_case}")
                missing_fields = [item for item in missing_fields if item != "use_case"]
            spec = RequirementSpec(
                raw_request=fallback.raw_request,
                use_case=resolved_use_case,
                subject=RequirementSubject(
                    description=str(subject.get("description", ""))[:1000],
                    action=str(subject.get("action", ""))[:500],
                ),
                environment=str(parsed.get("environment", ""))[:1000],
                style=_strings(parsed.get("style")),
                composition=str(parsed.get("composition", ""))[:500],
                camera=RequirementCamera(
                    shot=str(camera.get("shot", ""))[:200],
                    lens=str(camera.get("lens", ""))[:200],
                ),
                lighting=_strings(parsed.get("lighting")),
                palette=_strings(parsed.get("palette")),
                text=RequirementText(content=request.text_content),
                negative_constraints=_strings(parsed.get("negative_constraints"), 50),
                output=self._output(request),
                assumptions=assumptions,
                missing_fields=missing_fields,
                confidence=float(parsed.get("confidence", 0.7)),
            )
        except (ValueError, TypeError, json.JSONDecodeError, ValidationError):
            return fallback, False, False

        self.store.save_requirement_analysis(
            cache_key, self.model, spec.model_dump_json()
        )
        return spec, True, False


class WorkflowService:
    def __init__(self, store: PromptStore, generator: ChatGenerator | None):
        self.store = store
        self.understander = RequirementUnderstander(store, generator)

    def create(self, request: UnderstandRequirementRequest) -> WorkflowRun:
        spec, generated, cached = self.understander.understand(request)
        return self.store.create_workflow_run(
            run_id=f"run_{uuid4().hex}",
            requirement_spec=spec,
            generated=generated,
            model=self.understander.model,
            timestamp=_now(),
            cached=cached,
        )

    def get(self, run_id: str) -> WorkflowRun | None:
        return self.store.get_workflow_run(run_id)

    def list(self, limit: int) -> list[WorkflowRun]:
        return self.store.list_workflow_runs(limit)

    def delete(self, run_id: str) -> bool:
        return self.store.delete_workflow_run(run_id)

    def confirm(self, run_id: str, spec: RequirementSpec) -> WorkflowRun | None:
        resolved = {
            "use_case": bool(spec.use_case.strip()),
            "subject.description": bool(spec.subject.description.strip()),
            "subject.action": bool(spec.subject.action.strip()),
            "environment": bool(spec.environment.strip()),
            "composition": bool(spec.composition.strip()),
            "camera": bool(spec.camera.shot.strip() or spec.camera.lens.strip()),
            "lighting": bool(spec.lighting),
            "palette": bool(spec.palette),
            "references": bool(spec.references),
        }
        remaining = [
            field for field in spec.missing_fields if not resolved.get(field, False)
        ]
        confirmed_spec = spec.model_copy(update={"missing_fields": remaining})
        return self.store.confirm_workflow_requirements(
            run_id, confirmed_spec, _now()
        )
