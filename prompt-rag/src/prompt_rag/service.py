from __future__ import annotations

import uuid

import httpx

from .analysis import CandidateAnalyzer
from .config import Settings
from .database import PromptStore
from .embeddings import Embedder
from .generation import ChatGenerator, generator_from_mimo_config
from .models import (
    PromptDocument,
    RecommendRequest,
    RecommendResponse,
    RemixRequest,
    RemixResponse,
    SearchRequest,
    SearchResponse,
)
from .retrieval import HybridRetriever
from .translation import PromptTranslator
from .workflow import WorkflowService


class PromptRAGService:
    def __init__(self, settings: Settings, store: PromptStore, embedder: Embedder | None):
        self.settings = settings
        self.store = store
        self.retriever = HybridRetriever(
            store,
            embedder,
            settings.lexical_weight,
            settings.dense_weight,
            settings.rrf_k,
        )
        configured_generator = ChatGenerator(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
        )
        mimo_generator = (
            generator_from_mimo_config(settings.mimo_config_path)
            if settings.translation_provider.strip().lower() == "mimo"
            else None
        )
        self.generator = configured_generator if configured_generator.enabled else (
            mimo_generator or configured_generator
        )
        translation_generator = (
            configured_generator if configured_generator.enabled else mimo_generator
        )
        self.translator = PromptTranslator(store, translation_generator)
        self.analyzer = CandidateAnalyzer(store, self.generator)
        self.workflows = WorkflowService(store, self.generator)

    def search(self, request: SearchRequest) -> SearchResponse:
        return self.retriever.search(request)

    def recommend(self, request: RecommendRequest) -> RecommendResponse:
        search_result = self.search(SearchRequest(**request.model_dump(exclude={"explain"})))
        explanation = (
            self.generator.explain_recommendations(request.query, search_result.results)
            if request.explain
            else None
        )
        return RecommendResponse(**search_result.model_dump(), recommendation=explanation)

    def remix(self, request: RemixRequest) -> RemixResponse:
        source = self.store.get(request.prompt_id)
        if source is None:
            raise KeyError(request.prompt_id)
        result = self.generator.remix(source, request.requirement)
        return RemixResponse(
            prompt_id=source.id,
            source_title=source.title,
            remixed_prompt=result,
            generated=self.generator.enabled,
        )

    def save_prompt(self, document: PromptDocument) -> tuple[PromptDocument, str, bool]:
        created = self.store.get(document.id) is None
        self.store.upsert_batch([document], f"admin-{uuid.uuid4().hex}")
        embedding_status = "disabled"
        embedder = self.retriever.embedder
        if embedder is not None and document.status == "active":
            categories = ", ".join(document.categories or [document.category])
            text = (
                f"Title: {document.title}\n"
                f"Description: {document.description}\n"
                f"Categories: {categories}\n"
                f"Prompt: {document.prompt}"
            )[: self.settings.embedding_text_max_chars]
            try:
                vector = embedder.embed_documents([text])[0]
                self.store.save_embeddings(
                    embedder.model_name,
                    [(document.id, document.content_hash, vector)],
                )
                embedding_status = "updated"
            except httpx.HTTPError:
                embedding_status = "pending"
        elif embedder is not None:
            embedding_status = "not_required"
        self.retriever.refresh_dense_index()
        saved = self.store.get(document.id)
        if saved is None:
            raise RuntimeError("Prompt disappeared after save")
        return saved, embedding_status, created
