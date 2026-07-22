from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from .database import PromptStore
from .embeddings import Embedder
from .models import PromptDocument


@dataclass(slots=True)
class IngestResult:
    source: str
    indexed: int
    removed: int
    embedded: int
    skipped_lines: int


def parse_source_record(raw: dict) -> PromptDocument:
    metadata = raw.get("metadata") or {}
    prompt = raw.get("prompt") or raw.get("content") or ""
    categories = metadata.get("categories") or [raw.get("category", "others")]
    return PromptDocument(
        id=str(raw["id"]),
        title=str(raw.get("title") or metadata.get("title") or "Untitled"),
        description=str(raw.get("description") or metadata.get("description") or ""),
        prompt=str(prompt),
        category=str(raw.get("category") or metadata.get("primary_category") or "others"),
        categories=[str(item) for item in categories],
        preview_image=str(raw.get("preview_image") or metadata.get("preview_image") or ""),
        source_media=list(raw.get("source_media") or metadata.get("source_media") or []),
        need_reference_images=bool(
            raw.get("need_reference_images", metadata.get("need_reference_images", False))
        ),
        arguments=list(raw.get("arguments") or metadata.get("arguments") or []),
        language=str(raw.get("language") or "en"),
        content_hash=str(
            metadata.get("content_hash") or raw.get("content_hash") or ""
        ),
        status=str(raw.get("status") or metadata.get("status") or "active"),
    )


def ingest_jsonl(
    source_path: Path | str,
    store: PromptStore,
    embedder: Embedder | None = None,
    batch_size: int = 500,
    embedding_batch_size: int = 32,
    embedding_text_max_chars: int = 6000,
) -> IngestResult:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(path)
    ingest_run = uuid.uuid4().hex
    batch: list[PromptDocument] = []
    indexed = 0
    skipped = 0
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                document = parse_source_record(json.loads(line))
                if not document.prompt.strip():
                    raise ValueError("empty prompt")
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                skipped += 1
                continue
            batch.append(document)
            if len(batch) >= batch_size:
                store.upsert_batch(batch, ingest_run)
                indexed += len(batch)
                batch.clear()
        if batch:
            store.upsert_batch(batch, ingest_run)
            indexed += len(batch)
    removed = store.finalize_ingest(ingest_run)

    embedded = 0
    if embedder is not None:
        pending = list(
            store.embedding_candidates(
                embedder.model_name,
                embedding_text_max_chars,
                getattr(embedder, "dimensions", None),
            )
        )
        for offset in range(0, len(pending), embedding_batch_size):
            chunk = pending[offset : offset + embedding_batch_size]
            vectors = embedder.embed_documents([item[2] for item in chunk])
            store.save_embeddings(
                embedder.model_name,
                [
                    (prompt_id, content_hash, vector)
                    for (prompt_id, content_hash, _), vector in zip(chunk, vectors, strict=True)
                ],
            )
            embedded += len(chunk)

    return IngestResult(
        source=str(path.resolve()),
        indexed=indexed,
        removed=removed,
        embedded=embedded,
        skipped_lines=skipped,
    )
