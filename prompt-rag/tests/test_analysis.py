import json

from prompt_rag.analysis import CandidateAnalyzer
from prompt_rag.database import PromptStore
from prompt_rag.models import PromptDocument


class FakeAnalysisGenerator:
    enabled = True
    model = "analysis-test"

    def __init__(self):
        self.calls = 0

    def analyze_candidates(self, query, candidates):
        self.calls += 1
        return json.dumps(
            {
                "summary": f"这三个方案都围绕{query}，但侧重点不同。",
                "cards": [
                    {
                        "prompt_id": candidate.id,
                        "personalized_title": f"方案：{candidate.title}",
                        "match_reason": "画面类型与需求一致。",
                        "best_for": "适合快速生成概念图。",
                        "adaptation_tip": "替换主体和场景细节。",
                    }
                    for candidate in candidates
                ],
            },
            ensure_ascii=False,
        )


def test_candidate_analysis_is_structured_and_cached(tmp_path):
    store = PromptStore(tmp_path / "analysis.db")
    generator = FakeAnalysisGenerator()
    analyzer = CandidateAnalyzer(store, generator)
    documents = [
        PromptDocument(
            id=f"p-{index}",
            title=f"Candidate {index}",
            description="A gameplay screenshot.",
            prompt="Create an in-game cinematic scene.",
            category="game-asset",
            content_hash=f"hash-{index}",
        )
        for index in range(1, 4)
    ]

    first = analyzer.analyze("游戏画面", documents)
    second = analyzer.analyze("游戏画面", documents)

    assert first["generated"] is True
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(first["cards"]) == 3
    assert first["cards"][0]["personalized_title"].startswith("方案：")
    assert generator.calls == 1
    assert store.stats()["candidate_analyses"] == 1
