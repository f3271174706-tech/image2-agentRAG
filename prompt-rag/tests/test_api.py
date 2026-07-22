from fastapi.testclient import TestClient

from prompt_rag.api import create_app
from prompt_rag.config import Settings


def test_api_auto_ingests_and_searches(tmp_path, sample_jsonl):
    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "api.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health")
        response = client.post(
            "/api/search", json={"query": "minimal bottle product", "top_k": 1}
        )

    assert health.status_code == 200
    assert health.json()["prompts"] == 3
    assert health.json()["embedding_provider"] == "none"
    assert health.json()["embedding_model"] is None
    assert health.json()["embedding_dimensions"] is None
    assert response.status_code == 200
    assert response.json()["results"][0]["document"]["id"] == "p-product"


def test_standard_llm_environment_also_enables_translation(tmp_path, sample_jsonl):
    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "llm.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="llm",
        llm_base_url="https://llm.example/v1",
        llm_api_key="secret",
        llm_model="test-model",
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()

    assert health["generation_enabled"] is True
    assert health["translation_enabled"] is True


def test_frontend_routes_keep_legacy_and_mount_studio(tmp_path, sample_jsonl):
    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "frontend.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    with TestClient(create_app(settings)) as client:
        root = client.get("/")
        legacy = client.get("/legacy")
        studio = client.get("/v2/")
        manage = client.get("/manage")

    assert root.status_code == 200
    assert legacy.status_code == 200
    assert studio.status_code == 200
    assert "Prompt Studio" in studio.text
    assert manage.status_code == 200
    assert "Prompt Studio" in manage.text


def test_admin_center_requires_login_and_manages_single_prompt(tmp_path, sample_jsonl):
    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "admin.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
        admin_password="correct horse battery staple",
        admin_session_secret="test-only-session-secret",
    )
    with TestClient(create_app(settings)) as client:
        unauthorized = client.get("/api/admin/stats")
        wrong_login = client.post("/api/admin/login", json={"password": "wrong"})
        login = client.post(
            "/api/admin/login", json={"password": "correct horse battery staple"}
        )
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        session = client.get("/api/admin/session", headers=headers)
        listing = client.get("/api/admin/prompts?page_size=2", headers=headers)
        created = client.post(
            "/api/admin/prompts",
            headers=headers,
            json={
                "id": "manual-watercolor-owl",
                "title": "Watercolor Owl Storybook",
                "description": "A gentle illustrated owl scene.",
                "prompt": "A soft watercolor owl in a moonlit storybook forest.",
                "category": "comic-storyboard",
                "categories": ["comic-storyboard", "others"],
                "language": "en",
                "status": "active",
            },
        )
        searchable = client.post(
            "/api/search", json={"query": "watercolor owl", "top_k": 3}
        )
        updated = client.put(
            "/api/admin/prompts/manual-watercolor-owl",
            headers=headers,
            json={
                **created.json()["document"],
                "status": "inactive",
            },
        )
        hidden = client.post(
            "/api/search", json={"query": "watercolor owl", "top_k": 3}
        )
        stats = client.get("/api/admin/stats", headers=headers)
        tampered = client.get(
            "/api/admin/session",
            headers={"Authorization": f"Bearer {token}x"},
        )

    assert unauthorized.status_code == 401
    assert wrong_login.status_code == 401
    assert login.status_code == 200
    assert session.status_code == 200
    assert listing.status_code == 200
    assert listing.json()["total"] == 3
    assert created.status_code == 201
    assert created.json()["created"] is True
    assert created.json()["embedding_status"] == "disabled"
    assert any(
        hit["document"]["id"] == "manual-watercolor-owl"
        for hit in searchable.json()["results"]
    )
    assert updated.status_code == 200
    assert updated.json()["document"]["status"] == "inactive"
    assert all(
        hit["document"]["id"] != "manual-watercolor-owl"
        for hit in hidden.json()["results"]
    )
    assert stats.json()["prompts"] == 4
    assert stats.json()["active_prompts"] == 3
    assert stats.json()["inactive_prompts"] == 1
    assert tampered.status_code == 401


def test_admin_center_stays_disabled_without_password(tmp_path, sample_jsonl):
    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "admin-disabled.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    with TestClient(create_app(settings)) as client:
        login = client.post("/api/admin/login", json={"password": "anything"})
        stats = client.get("/api/admin/stats")

    assert login.status_code == 503
    assert stats.status_code == 503


def test_legacy_query_adapter_returns_chat_shape(tmp_path, sample_jsonl):
    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "legacy.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/query",
            json={
                "question": "retro travel poster",
                "session_id": "test-session",
                "language": "zh",
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["source"] == "knowledge_base"
    assert body["session_id"] == "test-session"
    assert body["language"] == "zh"
    assert f"筛选出 {len(body['documents'])} 个候选模板" in body["answer"]
    assert "A vintage travel poster" in body["documents"][0]["prompt"]
    assert "Retro Travel Poster" not in body["answer"]
    assert body["documents"][0]["id"] == "p-poster"
    assert all(document["prompt"] for document in body["documents"])
    assert body["translation_prompt_id"] is None


def test_legacy_query_adapter_can_switch_to_english(tmp_path, sample_jsonl):
    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "english.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/query",
            json={"question": "retro travel poster", "language": "en"},
        )

    body = response.json()
    assert body["language"] == "en"
    assert "Knowledge-base results" in body["answer"]
    assert "Retro Travel Poster" in body["answer"]
    assert "Complete prompt ready to use" in body["answer"]


def test_chinese_query_returns_before_translation_and_supports_translate_endpoint(
    tmp_path, sample_jsonl
):
    class FakeTranslator:
        enabled = True

        def to_chinese(self, prompt: str) -> str:
            assert prompt.startswith("A vintage travel poster")
            return "一张复古铁路旅行海报。"

    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "async-translation.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.prompt_rag.translator = FakeTranslator()
        query = client.post(
            "/api/query",
            json={"question": "retro travel poster", "language": "zh"},
        )
        translation = client.post(
            "/api/translate",
            json={"prompt_id": "p-poster", "target_language": "zh"},
        )

    body = query.json()
    assert query.status_code == 200
    assert body["translation_prompt_id"] == "p-poster"
    assert "自动翻译" in body["answer"]
    assert all(document["prompt"] for document in body["documents"])
    assert body["documents"][0]["can_translate"] is True
    assert translation.status_code == 200
    assert translation.json()["translation"] == "一张复古铁路旅行海报。"


def test_translate_text_supports_generated_prompt_output(tmp_path, sample_jsonl):
    class FakeTranslator:
        enabled = True

        def to_chinese(self, prompt: str) -> str:
            assert prompt == "A cinematic rainy city at night."
            return "电影感雨夜城市。"

    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "translate-text.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.prompt_rag.translator = FakeTranslator()
        response = client.post(
            "/api/translate-text",
            json={"text": "A cinematic rainy city at night.", "target_language": "zh"},
        )

    assert response.status_code == 200
    assert response.json()["translation"] == "电影感雨夜城市。"


def test_candidate_analysis_endpoint_uses_selected_documents(tmp_path, sample_jsonl):
    class FakeAnalyzer:
        enabled = True

        def analyze(self, query, documents):
            return {
                "summary": f"已分析：{query}",
                "cards": [
                    {
                        "prompt_id": document.id,
                        "personalized_title": document.title,
                        "match_reason": "匹配",
                        "best_for": "概念图",
                        "adaptation_tip": "替换主体",
                    }
                    for document in documents
                ],
                "generated": True,
                "cached": False,
            }

    settings = Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "analysis-api.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.prompt_rag.analyzer = FakeAnalyzer()
        query = client.post(
            "/api/query", json={"question": "retro travel poster", "language": "zh"}
        ).json()
        response = client.post(
            "/api/analyze-results",
            json={
                "query": "retro travel poster",
                "prompt_ids": ["p-poster", "p-avatar", "p-product"],
            },
        )

    assert len(query["analysis_prompt_ids"]) == len(query["documents"])
    assert response.status_code == 200
    assert len(response.json()["cards"]) == 3
