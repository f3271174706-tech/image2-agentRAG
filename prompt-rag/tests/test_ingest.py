from prompt_rag.database import PromptStore
from prompt_rag.ingest import ingest_jsonl


def test_ingest_is_idempotent_and_preserves_metadata(tmp_path, sample_jsonl):
    store = PromptStore(tmp_path / "rag.db")
    first = ingest_jsonl(sample_jsonl, store, batch_size=2)
    second = ingest_jsonl(sample_jsonl, store, batch_size=2)

    assert first.indexed == 3
    assert second.indexed == 3
    assert store.stats()["prompts"] == 3
    product = store.get("p-product")
    assert product is not None
    assert product.categories == ["ecommerce-main-image", "product-marketing"]
    assert product.need_reference_images is True


def test_ingest_removes_records_missing_from_latest_snapshot(tmp_path, sample_jsonl):
    store = PromptStore(tmp_path / "rag.db")
    ingest_jsonl(sample_jsonl, store)
    lines = sample_jsonl.read_text(encoding="utf-8").splitlines()
    sample_jsonl.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")

    result = ingest_jsonl(sample_jsonl, store)

    assert result.removed == 1
    assert store.get("p-poster") is None


def test_changed_record_replaces_fts_content(tmp_path, sample_jsonl):
    import json

    store = PromptStore(tmp_path / "rag.db")
    ingest_jsonl(sample_jsonl, store)
    rows = [json.loads(line) for line in sample_jsonl.read_text(encoding="utf-8").splitlines()]
    rows[0]["title"] = "Watercolor Astronaut"
    rows[0]["description"] = "A quiet observatory portrait."
    rows[0]["prompt"] = "A watercolor astronaut portrait in a quiet observatory."
    rows[0]["content_hash"] = "changed"
    sample_jsonl.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    ingest_jsonl(sample_jsonl, store)

    assert store.lexical_search("watercolor astronaut", 5) == ["p-avatar"]
    assert store.lexical_search("cyberpunk neon", 5) == []
