from __future__ import annotations

import hashlib
import json
from typing import Any

from .database import PromptStore
from .generation import ChatGenerator
from .models import PromptDocument


def _clean_text(value: Any, fallback: str, limit: int) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.split()).strip()
    return cleaned[:limit] if cleaned else fallback


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("analysis response does not contain a JSON object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("analysis response must be a JSON object")
    return payload


class CandidateAnalyzer:
    def __init__(self, store: PromptStore, generator: ChatGenerator | None):
        self.store = store
        self.generator = generator

    @property
    def enabled(self) -> bool:
        return bool(self.generator and self.generator.enabled)

    @staticmethod
    def _fallback(query: str, documents: list[PromptDocument]) -> dict[str, Any]:
        return {
            "summary": f"已按“{query}”筛选出 {len(documents)} 个候选模板，可根据画面主体和用途继续细化。",
            "cards": [
                {
                    "prompt_id": document.id,
                    "personalized_title": document.title,
                    "match_reason": "该模板与检索关键词和画面类型具有较高相关性。",
                    "best_for": document.description or "适合作为图像生成的基础模板。",
                    "adaptation_tip": "建议替换主体、场景和风格参数，使其更贴合你的具体需求。",
                }
                for document in documents
            ],
            "generated": False,
            "cached": False,
        }

    def _cache_key(self, query: str, documents: list[PromptDocument]) -> str:
        identity = {
            "query": " ".join(query.casefold().split()),
            "documents": [
                {"id": document.id, "content_hash": document.content_hash}
                for document in documents
            ],
        }
        return hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def analyze(self, query: str, documents: list[PromptDocument]) -> dict[str, Any]:
        if not documents or not self.enabled:
            return self._fallback(query, documents)

        assert self.generator is not None
        cache_key = self._cache_key(query, documents)
        cached = self.store.get_candidate_analysis(cache_key, self.generator.model)
        if cached:
            result = json.loads(cached)
            result["cached"] = True
            return result

        raw = self.generator.analyze_candidates(query, documents)
        try:
            payload = _extract_json(raw)
            supplied_cards = {
                card.get("prompt_id"): card
                for card in payload.get("cards", [])
                if isinstance(card, dict) and card.get("prompt_id")
            }
            cards = []
            for document in documents:
                supplied = supplied_cards.get(document.id, {})
                cards.append(
                    {
                        "prompt_id": document.id,
                        "personalized_title": _clean_text(
                            supplied.get("personalized_title"), document.title, 60
                        ),
                        "match_reason": _clean_text(
                            supplied.get("match_reason"),
                            "该模板与用户需求具有较高相关性。",
                            220,
                        ),
                        "best_for": _clean_text(
                            supplied.get("best_for"),
                            document.description or "适合作为基础图像模板。",
                            180,
                        ),
                        "adaptation_tip": _clean_text(
                            supplied.get("adaptation_tip"),
                            "建议替换主体与场景参数以贴合实际需求。",
                            220,
                        ),
                    }
                )
            result = {
                "summary": _clean_text(
                    payload.get("summary"),
                    f"已结合“{query}”分析这 {len(documents)} 个候选模板。",
                    240,
                ),
                "cards": cards,
                "generated": True,
            }
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._fallback(query, documents)

        self.store.save_candidate_analysis(
            cache_key,
            self.generator.model,
            json.dumps(result, ensure_ascii=False),
        )
        result["cached"] = False
        return result
