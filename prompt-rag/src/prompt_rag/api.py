from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from html import escape
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .database import PromptStore
from .embeddings import build_embedder
from .ingest import ingest_jsonl
from .models import (
    PromptDocument,
    ConfirmRequirementRequest,
    RecommendRequest,
    RecommendResponse,
    RemixRequest,
    RemixResponse,
    SearchRequest,
    SearchResponse,
    UnderstandRequirementRequest,
    WorkflowRun,
)
from .service import PromptRAGService


class LegacyQueryRequest(BaseModel):
    """Compatibility request used by the temporary LangChain chat UI."""

    question: str = Field(min_length=1, max_length=1000)
    session_id: str = "default"
    mode: str = "knowledge"
    deep_think: bool = False
    web_search: bool = False
    language: Literal["zh", "en"] = "zh"


class TranslatePromptRequest(BaseModel):
    prompt_id: str = Field(min_length=1, max_length=200)
    target_language: Literal["zh"] = "zh"


class TranslateTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30000)
    target_language: Literal["zh"] = "zh"


class AnalyzeResultsRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    prompt_ids: list[str] = Field(min_length=1, max_length=3)


class AdminLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=500)


class AdminPromptInput(BaseModel):
    id: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    prompt: str = Field(min_length=1, max_length=50000)
    category: str = Field(default="others", min_length=1, max_length=100)
    categories: list[str] = Field(default_factory=list, max_length=30)
    preview_image: str = Field(default="", max_length=5000)
    source_media: list[str] = Field(default_factory=list, max_length=30)
    need_reference_images: bool = False
    arguments: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    language: str = Field(default="en", min_length=1, max_length=20)
    status: Literal["active", "inactive"] = "active"


CATEGORY_LABELS_ZH = {
    "profile-avatar": "头像 / 肖像",
    "social-media-post": "社交媒体内容",
    "product-marketing": "产品营销",
    "poster-flyer": "海报 / 传单",
    "infographic-edu-visual": "信息图 / 教育视觉",
    "ecommerce-main-image": "电商主图",
    "game-asset": "游戏素材",
    "comic-storyboard": "漫画 / 分镜",
    "youtube-thumbnail": "YouTube 缩略图",
    "app-web-design": "应用 / 网页设计",
    "others": "其他",
}


def _admin_document(payload: AdminPromptInput, prompt_id: str) -> PromptDocument:
    title = payload.title.strip()
    prompt = payload.prompt.strip()
    category = payload.category.strip()
    language = payload.language.strip().lower()
    if not title or not prompt or not category or not language:
        raise HTTPException(status_code=422, detail="标题、提示词、分类和语言不能为空")
    categories = list(
        dict.fromkeys(
            item.strip()
            for item in [category, *payload.categories]
            if item.strip()
        )
    )
    semantic_content = {
        "id": prompt_id,
        "title": title,
        "description": payload.description.strip(),
        "prompt": prompt,
        "category": category,
        "categories": categories,
        "preview_image": payload.preview_image.strip(),
        "source_media": [item.strip() for item in payload.source_media if item.strip()],
        "need_reference_images": payload.need_reference_images,
        "arguments": payload.arguments,
        "language": language,
        "status": payload.status,
    }
    content_hash = hashlib.sha256(
        json.dumps(
            semantic_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return PromptDocument(**semantic_content, content_hash=content_hash)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    resolved.prepare_paths()
    login_attempts: dict[str, list[float]] = {}
    login_lock = threading.Lock()
    admin_signing_key = (
        resolved.admin_session_secret or resolved.admin_password
    ).encode("utf-8")

    def issue_admin_token() -> str:
        expires = int(time.time() + resolved.admin_session_hours * 3600)
        payload = str(expires)
        signature = hmac.new(
            admin_signing_key, payload.encode("ascii"), hashlib.sha256
        ).digest()
        encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return f"{payload}.{encoded}"

    def valid_admin_token(token: str) -> bool:
        if not resolved.admin_password or not admin_signing_key:
            return False
        try:
            payload, encoded = token.split(".", 1)
            if int(payload) <= int(time.time()):
                return False
        except (TypeError, ValueError):
            return False
        expected = base64.urlsafe_b64encode(
            hmac.new(admin_signing_key, payload.encode("ascii"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        return secrets.compare_digest(encoded, expected)

    def require_admin(request: Request) -> None:
        if not resolved.admin_password:
            raise HTTPException(status_code=503, detail="管理中心尚未配置")
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not valid_admin_token(token.strip()):
            raise HTTPException(status_code=401, detail="管理员登录已失效")

    def login_client_key(request: Request) -> str:
        if request.client is None:
            return "unknown"
        return request.client.host

    def login_is_limited(client_key: str) -> bool:
        now = time.monotonic()
        with login_lock:
            recent = [stamp for stamp in login_attempts.get(client_key, []) if now - stamp < 300]
            login_attempts[client_key] = recent
            return len(recent) >= 5

    def record_failed_login(client_key: str) -> None:
        with login_lock:
            login_attempts.setdefault(client_key, []).append(time.monotonic())

    def clear_failed_logins(client_key: str) -> None:
        with login_lock:
            login_attempts.pop(client_key, None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = PromptStore(resolved.db_path)
        if resolved.auto_ingest and store.stats()["prompts"] == 0 and resolved.source_path.exists():
            ingest_jsonl(resolved.source_path, store)
        embedder = build_embedder(resolved)
        app.state.prompt_rag = PromptRAGService(resolved, store, embedder)
        yield

    app = FastAPI(
        title="Prompt RAG",
        description="Hybrid retrieval and recommendation for the GPT Image prompt knowledge base",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
    if resolved.legacy_static_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(resolved.legacy_static_dir)),
            name="legacy-static",
        )
    if resolved.studio_dist_dir.exists():
        app.mount(
            "/v2",
            StaticFiles(directory=str(resolved.studio_dist_dir), html=True),
            name="prompt-studio",
        )

    def service(request: Request) -> PromptRAGService:
        return request.app.state.prompt_rag

    @app.get("/", include_in_schema=False)
    def legacy_frontend() -> FileResponse:
        if not resolved.legacy_frontend_path.exists():
            raise HTTPException(status_code=404, detail="Temporary frontend not found")
        return FileResponse(resolved.legacy_frontend_path)

    @app.get("/legacy", include_in_schema=False)
    def legacy_frontend_alias() -> FileResponse:
        if not resolved.legacy_frontend_path.exists():
            raise HTTPException(status_code=404, detail="Temporary frontend not found")
        return FileResponse(resolved.legacy_frontend_path)

    @app.get("/manage", include_in_schema=False)
    def management_frontend() -> FileResponse:
        index_path = resolved.studio_dist_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="管理中心前端尚未构建")
        return FileResponse(index_path)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        current = service(request)
        stats = current.store.stats()
        return {
            "status": "ok",
            "prompts": stats["prompts"],
            "dense_enabled": current.retriever.dense_enabled,
            "embedding_provider": resolved.embedding_provider,
            "embedding_model": (
                current.retriever.dense.embedder.model_name
                if current.retriever.dense is not None
                else None
            ),
            "embedding_dimensions": (
                int(current.retriever.dense.matrix.shape[1])
                if current.retriever.dense is not None
                and current.retriever.dense.matrix.ndim == 2
                and current.retriever.dense.matrix.size
                else None
            ),
            "generation_enabled": current.generator.enabled,
            "translation_enabled": current.translator.enabled,
            "analysis_enabled": current.analyzer.enabled,
            "requirement_understanding_enabled": current.workflows.understander.enabled,
        }

    @app.get("/api/stats")
    def stats(request: Request) -> dict:
        return service(request).store.stats()

    @app.post("/api/admin/login")
    def admin_login(payload: AdminLoginRequest, request: Request) -> dict:
        if not resolved.admin_password:
            raise HTTPException(status_code=503, detail="管理中心尚未配置")
        client_key = login_client_key(request)
        if login_is_limited(client_key):
            raise HTTPException(status_code=429, detail="登录尝试过多，请五分钟后再试")
        if not secrets.compare_digest(payload.password, resolved.admin_password):
            record_failed_login(client_key)
            raise HTTPException(status_code=401, detail="管理员密码错误")
        clear_failed_logins(client_key)
        return {
            "token": issue_admin_token(),
            "expires_in": resolved.admin_session_hours * 3600,
        }

    @app.get("/api/admin/session")
    def admin_session(request: Request) -> dict:
        require_admin(request)
        return {"authenticated": True}

    @app.get("/api/admin/stats")
    def admin_stats(request: Request) -> dict:
        require_admin(request)
        current = service(request)
        model = current.retriever.embedder.model_name if current.retriever.embedder else None
        return current.store.management_stats(model)

    @app.get("/api/admin/prompts")
    def admin_prompts(
        request: Request,
        query: str = "",
        status: Literal["active", "inactive", "all"] = "all",
        page: int = 1,
        page_size: int = 30,
    ) -> dict:
        require_admin(request)
        safe_page = max(1, page)
        safe_page_size = max(1, min(page_size, 100))
        items, total = service(request).store.list_prompts(
            query=query,
            status=None if status == "all" else status,
            limit=safe_page_size,
            offset=(safe_page - 1) * safe_page_size,
        )
        return {
            "items": [item.model_dump() for item in items],
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
        }

    @app.post("/api/admin/prompts", status_code=201)
    def create_admin_prompt(payload: AdminPromptInput, request: Request) -> dict:
        require_admin(request)
        prompt_id = (payload.id or f"manual-{uuid.uuid4().hex}").strip()
        if not prompt_id:
            raise HTTPException(status_code=422, detail="提示词 ID 不能为空")
        if "/" in prompt_id:
            raise HTTPException(status_code=422, detail="提示词 ID 不能包含斜杠")
        if service(request).store.get(prompt_id) is not None:
            raise HTTPException(status_code=409, detail="提示词 ID 已存在")
        document = _admin_document(payload, prompt_id)
        saved, embedding_status, created = service(request).save_prompt(document)
        return {
            "document": saved.model_dump(),
            "embedding_status": embedding_status,
            "created": created,
        }

    @app.put("/api/admin/prompts/{prompt_id}")
    def update_admin_prompt(
        prompt_id: str, payload: AdminPromptInput, request: Request
    ) -> dict:
        require_admin(request)
        if service(request).store.get(prompt_id) is None:
            raise HTTPException(status_code=404, detail="提示词不存在")
        document = _admin_document(payload, prompt_id)
        saved, embedding_status, created = service(request).save_prompt(document)
        return {
            "document": saved.model_dump(),
            "embedding_status": embedding_status,
            "created": created,
        }

    @app.post("/api/workflow-runs", response_model=WorkflowRun)
    def create_workflow_run(
        payload: UnderstandRequirementRequest, request: Request
    ) -> WorkflowRun:
        return service(request).workflows.create(payload)

    @app.get("/api/workflow-runs", response_model=list[WorkflowRun])
    def list_workflow_runs(request: Request, limit: int = 20) -> list[WorkflowRun]:
        safe_limit = max(1, min(limit, 100))
        return service(request).workflows.list(safe_limit)

    @app.get("/api/workflow-runs/{run_id}", response_model=WorkflowRun)
    def workflow_run(run_id: str, request: Request) -> WorkflowRun:
        result = service(request).workflows.get(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="工作流记录不存在")
        return result

    @app.delete("/api/workflow-runs/{run_id}", status_code=204)
    def delete_workflow_run(run_id: str, request: Request) -> None:
        if not service(request).workflows.delete(run_id):
            raise HTTPException(status_code=404, detail="工作流记录不存在")

    @app.put("/api/workflow-runs/{run_id}/requirements", response_model=WorkflowRun)
    def confirm_workflow_requirements(
        run_id: str, payload: ConfirmRequirementRequest, request: Request
    ) -> WorkflowRun:
        result = service(request).workflows.confirm(
            run_id, payload.requirement_spec
        )
        if result is None:
            raise HTTPException(status_code=404, detail="工作流记录不存在")
        return result

    @app.get("/api/prompts/{prompt_id}", response_model=PromptDocument)
    def prompt(prompt_id: str, request: Request) -> PromptDocument:
        result = service(request).store.get(prompt_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return result

    @app.post("/api/search", response_model=SearchResponse)
    def search(payload: SearchRequest, request: Request) -> SearchResponse:
        return service(request).search(payload)

    @app.post("/api/query")
    def legacy_query(payload: LegacyQueryRequest, request: Request) -> dict:
        """Adapt Prompt RAG search results to the legacy chat response shape."""
        result = service(request).search(
            SearchRequest(query=payload.question, top_k=3, use_dense=True)
        )
        if not result.results:
            return {
                "question": payload.question,
                "rewritten_query": result.expanded_query,
                "answer": (
                    "没有找到匹配的提示词，请换一种描述。"
                    if payload.language == "zh"
                    else "No matching prompt was found. Try describing the request differently."
                ),
                "documents": [],
                "confidence": 0.0,
                "source": "knowledge_base",
                "session_id": payload.session_id,
                "language": payload.language,
            }

        chinese = payload.language == "zh"
        translation_prompt_id = (
            result.results[0].document.id
            if chinese and service(request).translator.enabled
            else None
        )
        analysis_prompt_ids = (
            [hit.document.id for hit in result.results]
            if chinese and service(request).analyzer.enabled
            else []
        )
        answer_parts = (
            [
                f"📚 已从知识库筛选出 {len(result.results)} 个候选模板。",
                "正在结合你的真实需求分析差异；首选提示词会自动翻译，所有原始提示词均可在卡片中查看。",
            ]
            if chinese
            else ["📚 Knowledge-base results:", "The following prompt templates match your request:"]
        )
        documents = []
        for index, hit in enumerate(result.results, start=1):
            document = hit.document
            if chinese:
                category_label = CATEGORY_LABELS_ZH.get(document.category, "其他")
                display_title = f"候选提示词 {index} · {category_label}"
                source_label = display_title
                content_label = "原始英文生成提示词："
            else:
                answer_parts.extend(
                    [
                        "",
                        f"**{index}. {document.title}**",
                        document.description or "No description available.",
                        f"Category: {document.category}",
                    ]
                )
                if index == 1:
                    answer_parts.extend(
                        [
                            "",
                            "**Complete prompt ready to use:**",
                            document.prompt,
                            "",
                            "See the references below for the complete alternative prompts.",
                        ]
                    )
                source_label = document.title
                content_label = "Original generation prompt:"
            prompt_text = escape(document.prompt)
            documents.append(
                {
                    "source": escape(source_label),
                    "content": f"{content_label}\n{prompt_text}",
                    "id": document.id,
                    "title": document.title,
                    "description": document.description,
                    "prompt": document.prompt,
                    "category": document.category,
                    "category_label": CATEGORY_LABELS_ZH.get(
                        document.category, document.category
                    ),
                    "need_reference_images": document.need_reference_images,
                    "preview_image": document.preview_image,
                    "score": hit.score,
                    "rank": index,
                    "can_translate": chinese and service(request).translator.enabled,
                }
            )
        return {
            "question": payload.question,
            "rewritten_query": result.expanded_query,
            "answer": "\n".join(answer_parts),
            "documents": documents,
            "confidence": result.results[0].score,
            "source": "knowledge_base",
            "session_id": payload.session_id,
            "route": "prompt_rag_compat",
            "videos": [],
            "language": payload.language,
            "translation_prompt_id": translation_prompt_id,
            "analysis_prompt_ids": analysis_prompt_ids,
        }

    @app.post("/api/analyze-results")
    def analyze_results(payload: AnalyzeResultsRequest, request: Request) -> dict:
        current = service(request)
        prompt_ids = list(dict.fromkeys(payload.prompt_ids))
        documents_by_id = current.store.get_many(prompt_ids)
        missing = [prompt_id for prompt_id in prompt_ids if prompt_id not in documents_by_id]
        if missing:
            raise HTTPException(status_code=404, detail="候选提示词不存在")
        documents = [documents_by_id[prompt_id] for prompt_id in prompt_ids]
        return current.analyzer.analyze(payload.query, documents)

    @app.post("/api/translate")
    def translate_prompt(payload: TranslatePromptRequest, request: Request) -> dict:
        current = service(request)
        if not current.translator.enabled:
            raise HTTPException(status_code=503, detail="翻译服务尚未配置")
        document = current.store.get(payload.prompt_id)
        if document is None:
            raise HTTPException(status_code=404, detail="提示词不存在")
        return {
            "prompt_id": document.id,
            "target_language": payload.target_language,
            "translation": current.translator.to_chinese(document.prompt),
        }

    @app.post("/api/translate-text")
    def translate_text(payload: TranslateTextRequest, request: Request) -> dict:
        """Translate a generated prompt while reusing the same guarded cache."""
        current = service(request)
        if not current.translator.enabled:
            raise HTTPException(status_code=503, detail="翻译服务尚未配置")
        return {
            "target_language": payload.target_language,
            "translation": current.translator.to_chinese(payload.text),
        }

    @app.post("/api/recommend", response_model=RecommendResponse)
    def recommend(payload: RecommendRequest, request: Request) -> RecommendResponse:
        return service(request).recommend(payload)

    @app.post("/api/remix", response_model=RemixResponse)
    def remix(payload: RemixRequest, request: Request) -> RemixResponse:
        try:
            return service(request).remix(payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Prompt not found") from exc

    return app


app = create_app()
