import numpy as np
import httpx

from prompt_rag.database import PromptStore
from prompt_rag.ingest import ingest_jsonl
from prompt_rag.models import SearchRequest
from prompt_rag.models import PromptDocument
from prompt_rag.retrieval import (
    HybridRetriever,
    expand_query,
    query_intent_adjustment,
    should_use_dense_for_query,
)


class FakeMultilingualEmbedder:
    model_name = "fake-multilingual"

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        lowered = text.lower()
        if any(token in lowered for token in ("avatar", "portrait", "头像")):
            return np.array([1.0, 0.0, 0.0], dtype=np.float32)
        if any(token in lowered for token in ("product", "bottle", "商品")):
            return np.array([0.0, 1.0, 0.0], dtype=np.float32)
        return np.array([0.0, 0.0, 1.0], dtype=np.float32)

    def embed_documents(self, texts):
        return np.vstack([self._vector(text) for text in texts])

    def embed_query(self, text):
        return self._vector(text)


def test_chinese_cinematic_style_is_expanded_for_lexical_recall():
    expanded = expand_query("电影感", [])

    assert "cinematic" in expanded
    assert "film still" in expanded
    assert should_use_dense_for_query("电影感") is False
    assert should_use_dense_for_query("现代电影感") is False
    assert should_use_dense_for_query("我想要一张电影感的雨夜人像") is True


def test_gameplay_query_expands_to_screenshot_instead_of_sprite_asset():
    expanded = expand_query("游戏画面", ["game-asset"])

    assert "gameplay screenshot" in expanded
    assert "video game" in expanded
    assert "sprite asset" not in expanded
    assert should_use_dense_for_query("游戏画面") is False


def test_modern_qualifier_penalizes_explicitly_vintage_results():
    common = {
        "id": "test",
        "categories": [],
        "need_reference_images": False,
        "status": "active",
    }
    modern = PromptDocument(
        **common,
        title="Modern cinematic portrait",
        description="A contemporary city scene",
        prompt="Cinematic lighting in a modern downtown street.",
        category="profile-avatar",
    )
    vintage = PromptDocument(
        **common,
        title="Vintage road movie",
        description="A 1970s Americana scene",
        prompt="Cinematic still with no modern branding.",
        category="comic-storyboard",
    )

    assert query_intent_adjustment("现代电影感", modern) > 0
    assert query_intent_adjustment("现代电影感", vintage) < 0


def test_gameplay_intent_prefers_screenshot_over_sprite_sheet():
    common = {
        "id": "test",
        "category": "game-asset",
        "categories": [],
        "need_reference_images": False,
        "status": "active",
    }
    gameplay = PromptDocument(
        **common,
        title="Open World Gameplay Screenshot",
        description="A realistic in-game scene with a playable character and HUD.",
        prompt="Create a video game screenshot of an open-world environment.",
    )
    sprite = PromptDocument(
        **common,
        title="Character Sprite Sheet",
        description="An isolated game asset turnaround sheet.",
        prompt="Create eight pixel sprites on a white background.",
    )

    assert query_intent_adjustment("游戏画面", gameplay) > 0
    assert query_intent_adjustment("游戏画面", sprite) < 0


def test_lexical_search_returns_complete_document(tmp_path, sample_jsonl):
    store = PromptStore(tmp_path / "rag.db")
    ingest_jsonl(sample_jsonl, store)
    retriever = HybridRetriever(store)

    result = retriever.search(SearchRequest(query="vintage railway poster", top_k=2))

    assert result.results[0].document.id == "p-poster"
    assert result.results[0].document.prompt.startswith("A vintage travel poster")
    assert result.results[0].matched_by == ["lexical"]


def test_hybrid_search_supports_cross_language_query(tmp_path, sample_jsonl):
    store = PromptStore(tmp_path / "rag.db")
    embedder = FakeMultilingualEmbedder()
    ingest_jsonl(sample_jsonl, store, embedder=embedder, embedding_batch_size=2)
    retriever = HybridRetriever(store, embedder)

    result = retriever.search(SearchRequest(query="我想要一个霓虹头像", top_k=1))

    assert result.dense_enabled is True
    assert result.results[0].document.id == "p-avatar"
    assert "dense" in result.results[0].matched_by


def test_embedding_api_failure_falls_back_to_lexical_results(tmp_path, sample_jsonl):
    class FailingQueryEmbedder(FakeMultilingualEmbedder):
        def embed_query(self, text):
            request = httpx.Request("POST", "https://embedding.test/v1/embeddings")
            raise httpx.ConnectError("offline", request=request)

    store = PromptStore(tmp_path / "fallback.db")
    ingest_jsonl(sample_jsonl, store, embedder=FakeMultilingualEmbedder())
    retriever = HybridRetriever(store, FailingQueryEmbedder())

    result = retriever.search(
        SearchRequest(query="I need a detailed cyberpunk neon avatar portrait", top_k=1)
    )

    assert result.results[0].document.id == "p-avatar"
    assert result.dense_enabled is False
    assert result.dense_error == "embedding_api_unavailable"


def test_metadata_filters_are_applied_to_dense_results(tmp_path, sample_jsonl):
    store = PromptStore(tmp_path / "rag.db")
    embedder = FakeMultilingualEmbedder()
    ingest_jsonl(sample_jsonl, store, embedder=embedder)
    retriever = HybridRetriever(store, embedder)

    result = retriever.search(
        SearchRequest(
            query="商品照片",
            top_k=5,
            categories=["product-marketing"],
            need_reference_images=True,
        )
    )

    assert [hit.document.id for hit in result.results] == ["p-product"]


def test_duplicate_prompt_content_only_occupies_one_result(tmp_path, sample_jsonl):
    import json

    rows = [json.loads(line) for line in sample_jsonl.read_text(encoding="utf-8").splitlines()]
    duplicate = dict(rows[0])
    duplicate["id"] = "p-avatar-copy"
    duplicate["title"] = "Copy of Neon Avatar"
    sample_jsonl.write_text(
        "".join(json.dumps(row) + "\n" for row in [*rows, duplicate]), encoding="utf-8"
    )
    store = PromptStore(tmp_path / "rag.db")
    ingest_jsonl(sample_jsonl, store)
    result = HybridRetriever(store).search(
        SearchRequest(query="cyberpunk neon avatar", top_k=5)
    )

    avatar_hits = [
        hit for hit in result.results if hit.document.content_hash == rows[0]["content_hash"]
    ]
    assert len(avatar_hits) == 1
