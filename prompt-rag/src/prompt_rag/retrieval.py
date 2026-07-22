from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

import numpy as np
import httpx

from .database import PromptStore
from .embeddings import Embedder
from .models import PromptDocument, SearchHit, SearchRequest, SearchResponse


CATEGORY_SIGNALS: dict[str, tuple[str, ...]] = {
    "profile-avatar": ("avatar", "profile", "portrait", "headshot", "头像", "肖像", "自拍"),
    "social-media-post": ("social", "instagram", "twitter", "小红书", "社交媒体", "帖子"),
    "product-marketing": ("marketing", "advertisement", "campaign", "营销", "广告", "宣传"),
    "poster-flyer": ("poster", "flyer", "banner", "海报", "传单", "横幅"),
    "infographic-edu-visual": ("infographic", "diagram", "chart", "信息图", "图表", "科普"),
    "ecommerce-main-image": ("ecommerce", "listing", "product photo", "电商", "商品主图", "白底图"),
    "game-asset": ("game", "gameplay", "video game", "游戏", "精灵", "素材"),
    "comic-storyboard": ("comic", "manga", "storyboard", "漫画", "分镜"),
    "youtube-thumbnail": ("youtube", "thumbnail", "视频封面", "缩略图"),
    "app-web-design": ("app", "website", "interface", "dashboard", "网页", "界面", "仪表盘"),
}

QUERY_EXPANSIONS: dict[str, str] = {
    "赛博朋克": "cyberpunk neon futuristic",
    "极简": "minimalist minimal clean",
    "动漫": "anime manga illustration",
    "写实": "photorealistic realistic photography",
    "复古": "vintage retro",
    "科技": "technology futuristic tech",
    "旅行": "travel tourism landscape",
    "美食": "food culinary",
    "汽车": "car automotive vehicle",
    "人物": "person character portrait",
    "猫": "cat feline",
    "狗": "dog canine",
    "宇宙飞船": "spaceship spacecraft",
    "太空": "space cosmic",
    "地球": "earth planet",
    "创业": "startup entrepreneur founder",
    "失败": "failure setback",
    "文章": "article editorial",
    "封面": "cover",
    "护肤品": "skincare cosmetic beauty",
    "透明": "transparent translucent",
    "玻璃": "glass crystal",
    "儿童": "children kids",
    "学习": "educational learning",
    "太阳系": "solar system planets",
    "彩色": "colorful vibrant",
    "游戏画面": "gameplay screenshot in-game scene video game screenshot",
    "游戏场景": "gameplay scene in-game environment video game screenshot",
    "实机画面": "gameplay screenshot in-game HUD playable character",
    "游戏截图": "gameplay screenshot in-game HUD video game",
    "游戏素材": "game asset sprite sheet isolated asset",
    "精灵图": "sprite sheet game asset character turnaround",
    "游戏界面": "game UI HUD interface gameplay screenshot",
    "电影感": "cinematic film still movie scene dramatic lighting",
    "电影": "cinematic movie film still",
    "人工智能": "artificial intelligence AI futuristic technology",
    "科幻": "science fiction sci-fi futuristic",
    "现代": "modern contemporary current-day",
}


def infer_categories(query: str) -> list[str]:
    lowered = query.casefold()
    return [
        category
        for category, signals in CATEGORY_SIGNALS.items()
        if any(signal.casefold() in lowered for signal in signals)
    ]


def expand_query(query: str, inferred_categories: Sequence[str]) -> str:
    additions = [value for key, value in QUERY_EXPANSIONS.items() if key in query]
    for category in inferred_categories:
        additions.extend(signal for signal in CATEGORY_SIGNALS[category][:3])
    return " ".join(dict.fromkeys([query, *additions]))


def should_use_dense_for_query(query: str) -> bool:
    """Short style-only queries are more precise after bilingual lexical expansion.

    Dense retrieval tends to overfit an arbitrary subject when the user supplied
    only a style (for example, 电影感), so it is reserved for composed requests.
    """
    remaining = query.strip()
    for term in sorted(QUERY_EXPANSIONS, key=len, reverse=True):
        remaining = remaining.replace(term, "")
    return bool(remaining.strip())


def query_intent_adjustment(query: str, document: PromptDocument) -> float:
    """Apply small, explicit boosts for hard qualifiers lost by an OR-only FTS query."""
    text = " ".join(
        filter(None, (document.title, document.description, document.prompt))
    ).casefold()
    adjustment = 0.0

    if "现代" in query:
        positive_text = re.sub(
            r"\b(?:no|without)\s+(?:\w+\s+){0,2}(?:modern|contemporary|current-day)\b",
            "",
            text,
        )
        if re.search(r"\b(?:modern|contemporary|current-day)\b", positive_text):
            adjustment += 0.0015
        if re.search(
            r"\b(?:no|without)\s+(?:\w+\s+){0,2}modern\b|\b(?:vintage|retro|19[0-9]{2}s)\b",
            text,
        ):
            adjustment -= 0.002

    gameplay_intent = any(
        term in query for term in ("游戏画面", "游戏场景", "实机画面", "游戏截图")
    )
    if gameplay_intent:
        if re.search(
            r"\b(?:gameplay|in-game|game screenshot|playable character|hud)\b",
            text,
        ):
            adjustment += 0.0015
        if re.search(
            r"\b(?:sprite sheet|asset sheet|sprite atlas|turnaround sheet|isolated asset)\b",
            text,
        ):
            adjustment -= 0.002
    return adjustment


class DenseIndex:
    def __init__(self, store: PromptStore, embedder: Embedder):
        self.store = store
        self.embedder = embedder
        self.ids: list[str] = []
        self.matrix = np.empty((0, 0), dtype=np.float32)
        self.refresh()

    @property
    def enabled(self) -> bool:
        return bool(self.ids) and self.matrix.size > 0

    def refresh(self) -> None:
        self.ids, self.matrix = self.store.load_embeddings(self.embedder.model_name)

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        if not self.enabled:
            return []
        vector = np.asarray(self.embedder.embed_query(query), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm:
            vector = vector / norm
        if vector.shape[0] != self.matrix.shape[1]:
            raise ValueError(
                f"Query embedding dimension {vector.shape[0]} does not match index {self.matrix.shape[1]}"
            )
        scores = self.matrix @ vector
        count = min(limit, scores.shape[0])
        if count == 0:
            return []
        indexes = np.argpartition(-scores, count - 1)[:count]
        indexes = indexes[np.argsort(-scores[indexes])]
        return [(self.ids[index], float(scores[index])) for index in indexes]


class HybridRetriever:
    def __init__(
        self,
        store: PromptStore,
        embedder: Embedder | None = None,
        lexical_weight: float = 0.45,
        dense_weight: float = 0.55,
        rrf_k: int = 60,
    ):
        self.store = store
        self.embedder = embedder
        self.dense = DenseIndex(store, embedder) if embedder else None
        self.lexical_weight = lexical_weight
        self.dense_weight = dense_weight
        self.rrf_k = rrf_k

    @property
    def dense_enabled(self) -> bool:
        return bool(self.dense and self.dense.enabled)

    def refresh_dense_index(self) -> None:
        if self.dense:
            self.dense.refresh()

    def search(self, request: SearchRequest) -> SearchResponse:
        inferred = infer_categories(request.query)
        expanded = expand_query(request.query, inferred)
        candidate_limit = max(request.top_k * 10, 50)
        lexical_ids = self.store.lexical_search(
            expanded,
            candidate_limit,
            request.categories,
            request.need_reference_images,
        )
        dense_allowed = request.use_dense and should_use_dense_for_query(request.query)
        dense_error = None
        try:
            dense_results = (
                self.dense.search(request.query, candidate_limit)
                if dense_allowed and self.dense_enabled
                else []
            )
        except httpx.HTTPError:
            dense_results = []
            dense_error = "embedding_api_unavailable"

        scores: dict[str, float] = defaultdict(float)
        lexical_ranks = {prompt_id: rank for rank, prompt_id in enumerate(lexical_ids, 1)}
        dense_ranks = {
            prompt_id: rank for rank, (prompt_id, _) in enumerate(dense_results, 1)
        }
        dense_scores = dict(dense_results)
        for prompt_id, rank in lexical_ranks.items():
            scores[prompt_id] += self.lexical_weight / (self.rrf_k + rank)
        for prompt_id, rank in dense_ranks.items():
            scores[prompt_id] += self.dense_weight / (self.rrf_k + rank)

        documents = self.store.get_many(list(scores))
        filtered: list[tuple[str, float]] = []
        requested_categories = set(request.categories)
        inferred_set = set(inferred)
        for prompt_id, score in scores.items():
            document = documents.get(prompt_id)
            if document is None:
                continue
            document_categories = set(document.categories) | {document.category}
            if requested_categories and not requested_categories.intersection(document_categories):
                continue
            if (
                request.need_reference_images is not None
                and document.need_reference_images != request.need_reference_images
            ):
                continue
            if inferred_set.intersection(document_categories):
                score += 0.002
            score += query_intent_adjustment(request.query, document)
            filtered.append((prompt_id, score))
        filtered.sort(key=lambda item: item[1], reverse=True)
        selected: list[tuple[str, float]] = []
        seen_content: set[str] = set()
        for prompt_id, score in filtered:
            document = documents[prompt_id]
            dedupe_key = document.content_hash or document.prompt.strip()
            if dedupe_key in seen_content:
                continue
            seen_content.add(dedupe_key)
            selected.append((prompt_id, score))
            if len(selected) >= request.top_k:
                break
        max_score = selected[0][1] if selected else 1.0

        hits = []
        for prompt_id, score in selected:
            matched_by = []
            if prompt_id in lexical_ranks:
                matched_by.append("lexical")
            if prompt_id in dense_ranks:
                matched_by.append("dense")
            hits.append(
                SearchHit(
                    document=documents[prompt_id],
                    score=round(score / max_score, 6),
                    lexical_rank=lexical_ranks.get(prompt_id),
                    dense_rank=dense_ranks.get(prompt_id),
                    dense_score=dense_scores.get(prompt_id),
                    matched_by=matched_by,
                )
            )

        return SearchResponse(
            query=request.query,
            expanded_query=expanded,
            inferred_categories=inferred,
            dense_enabled=bool(dense_allowed and self.dense_enabled and not dense_error),
            dense_error=dense_error,
            total=len(hits),
            results=hits,
        )
