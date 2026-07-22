from fastapi.testclient import TestClient

from prompt_rag.api import create_app
from prompt_rag.config import Settings


def _settings(tmp_path, sample_jsonl):
    return Settings(
        source_path=sample_jsonl,
        db_path=tmp_path / "workflow.db",
        auto_ingest=True,
        embedding_provider="none",
        translation_provider="none",
    )


def test_requirement_fallback_is_persisted_and_confirmable(tmp_path, sample_jsonl):
    settings = _settings(tmp_path, sample_jsonl)
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post(
            "/api/workflow-runs",
            json={
                "raw_request": "现代电影感游戏画面",
                "target_model": "GPT Image 2",
                "ratio": "16:9",
                "output_language": "zh",
            },
        )
        body = created.json()
        run_id = body["id"]
        spec = body["requirement_spec"]
        spec["subject"]["action"] = "站在雨夜街道中央"
        spec["environment"] = "霓虹城市"
        confirmed = client.put(
            f"/api/workflow-runs/{run_id}/requirements",
            json={"requirement_spec": spec},
        )

    assert created.status_code == 200
    assert body["status"] == "requirements_ready"
    assert body["generated"] is False
    assert spec["output"]["model"] == "gpt-image-2"
    assert spec["output"]["size"] == "1536x864"
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "requirements_confirmed"
    assert confirmed.json()["confirmed_at"]
    assert "subject.action" not in confirmed.json()["requirement_spec"]["missing_fields"]
    assert "environment" not in confirmed.json()["requirement_spec"]["missing_fields"]

    with TestClient(create_app(settings)) as client:
        restored = client.get(f"/api/workflow-runs/{run_id}")
        listed = client.get("/api/workflow-runs?limit=5")

    assert restored.status_code == 200
    assert restored.json()["requirement_spec"]["environment"] == "霓虹城市"
    assert any(item["id"] == run_id for item in listed.json())


def test_requirement_understanding_uses_model_and_cache(tmp_path, sample_jsonl):
    class FakeGenerator:
        enabled = True
        model = "fake-understander"
        calls = 0

        def understand_requirement(self, payload):
            self.calls += 1
            assert payload["raw_request"] == "雨夜机甲猎人游戏主视觉"
            return """{
                "use_case":"game-key-visual",
                "subject":{"description":"机甲猎人","action":"站立"},
                "environment":"雨夜霓虹城市",
                "style":["现代电影感","科幻"],
                "composition":"中心构图",
                "camera":{"shot":"wide","lens":"35mm"},
                "lighting":["霓虹侧光"],
                "palette":["深蓝","洋红"],
                "negative_constraints":[],
                "assumptions":["未指定角色性别"],
                "missing_fields":[],
                "confidence":0.91
            }"""

    settings = _settings(tmp_path, sample_jsonl)
    app = create_app(settings)
    generator = FakeGenerator()
    payload = {
        "raw_request": "雨夜机甲猎人游戏主视觉",
        "target_model": "gpt-image-2",
        "ratio": "16:9",
        "output_language": "zh",
    }
    with TestClient(app) as client:
        app.state.prompt_rag.workflows.understander.generator = generator
        first = client.post("/api/workflow-runs", json=payload)
        second = client.post("/api/workflow-runs", json=payload)

    assert first.status_code == 200
    assert first.json()["generated"] is True
    assert first.json()["cached"] is False
    assert first.json()["requirement_spec"]["subject"]["description"] == "机甲猎人"
    assert first.json()["requirement_spec"]["confidence"] == 0.91
    assert second.json()["cached"] is True
    assert generator.calls == 1


def test_workflow_run_can_be_deleted(tmp_path, sample_jsonl):
    settings = _settings(tmp_path, sample_jsonl)
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/workflow-runs",
            json={"raw_request": "待删除的测试任务", "output_language": "zh"},
        )
        run_id = created.json()["id"]
        deleted = client.delete(f"/api/workflow-runs/{run_id}")
        missing = client.get(f"/api/workflow-runs/{run_id}")
        deleted_again = client.delete(f"/api/workflow-runs/{run_id}")
        listed = client.get("/api/workflow-runs?limit=20")

    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert deleted_again.status_code == 404
    assert all(item["id"] != run_id for item in listed.json())
