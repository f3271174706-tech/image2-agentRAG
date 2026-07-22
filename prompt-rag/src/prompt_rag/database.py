from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .models import PromptDocument, RequirementSpec, WorkflowRun


class PromptStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS prompts (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    category TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    preview_image TEXT NOT NULL,
                    source_media_json TEXT NOT NULL,
                    need_reference_images INTEGER NOT NULL,
                    arguments_json TEXT NOT NULL,
                    language TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    ingest_run TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category);
                CREATE INDEX IF NOT EXISTS idx_prompts_status ON prompts(status);

                CREATE VIRTUAL TABLE IF NOT EXISTS prompts_fts USING fts5(
                    id UNINDEXED,
                    title,
                    description,
                    prompt,
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY (id, model),
                    FOREIGN KEY (id) REFERENCES prompts(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS translations (
                    source_hash TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    model TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    PRIMARY KEY (source_hash, target_language, model)
                );

                CREATE TABLE IF NOT EXISTS candidate_analyses (
                    cache_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    PRIMARY KEY (cache_key, model)
                );

                CREATE TABLE IF NOT EXISTS requirement_analyses (
                    cache_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    PRIMARY KEY (cache_key, model)
                );

                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    requirement_spec_json TEXT NOT NULL,
                    generated INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    confirmed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_workflow_runs_updated
                ON workflow_runs(updated_at DESC);
                """
            )

    @staticmethod
    def _to_db_tuple(document: PromptDocument, ingest_run: str) -> tuple[Any, ...]:
        return (
            document.id,
            document.title,
            document.description,
            document.prompt,
            document.category,
            json.dumps(document.categories, ensure_ascii=False),
            document.preview_image,
            json.dumps(document.source_media, ensure_ascii=False),
            int(document.need_reference_images),
            json.dumps(document.arguments, ensure_ascii=False),
            document.language,
            document.content_hash,
            document.status,
            ingest_run,
        )

    def upsert_batch(self, documents: Sequence[PromptDocument], ingest_run: str) -> None:
        if not documents:
            return
        ids = [document.id for document in documents]
        with self.connect() as connection:
            placeholders = ",".join("?" for _ in ids)
            existing = {
                row["id"]: (row["content_hash"], row["status"])
                for row in connection.execute(
                    f"SELECT id, content_hash, status FROM prompts WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()
            }
            changed = [
                document
                for document in documents
                if document.id not in existing
                or existing[document.id] != (document.content_hash, document.status)
            ]
            changed_ids = {document.id for document in changed}
            unchanged = [document for document in documents if document.id not in changed_ids]
            if changed:
                connection.executemany(
                    """
                    INSERT INTO prompts (
                        id, title, description, prompt, category, categories_json,
                        preview_image, source_media_json, need_reference_images,
                        arguments_json, language, content_hash, status, ingest_run
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        description=excluded.description,
                        prompt=excluded.prompt,
                        category=excluded.category,
                        categories_json=excluded.categories_json,
                        preview_image=excluded.preview_image,
                        source_media_json=excluded.source_media_json,
                        need_reference_images=excluded.need_reference_images,
                        arguments_json=excluded.arguments_json,
                        language=excluded.language,
                        content_hash=excluded.content_hash,
                        status=excluded.status,
                        ingest_run=excluded.ingest_run
                    """,
                    (self._to_db_tuple(document, ingest_run) for document in changed),
                )
            if unchanged:
                connection.executemany(
                    "UPDATE prompts SET ingest_run = ? WHERE id = ?",
                    ((ingest_run, document.id) for document in unchanged),
                )
            changed_existing = [
                (document.id,) for document in changed if document.id in existing
            ]
            if changed_existing:
                connection.executemany(
                    "DELETE FROM prompts_fts WHERE id = ?", changed_existing
                )
            if changed:
                connection.executemany(
                    "INSERT INTO prompts_fts(id, title, description, prompt) VALUES (?, ?, ?, ?)",
                    (
                        (document.id, document.title, document.description, document.prompt)
                        for document in changed
                    ),
                )

    def finalize_ingest(self, ingest_run: str) -> int:
        with self.connect() as connection:
            stale_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM prompts WHERE ingest_run != ?", (ingest_run,)
                ).fetchall()
            ]
            if stale_ids and len(stale_ids) <= 100:
                connection.executemany(
                    "DELETE FROM prompts_fts WHERE id = ?", ((item,) for item in stale_ids)
                )
            if stale_ids:
                connection.executemany(
                    "DELETE FROM prompts WHERE id = ?", ((item,) for item in stale_ids)
                )

            prompt_count = connection.execute(
                "SELECT COUNT(*) FROM prompts WHERE status = 'active'"
            ).fetchone()[0]
            fts_count = connection.execute("SELECT COUNT(*) FROM prompts_fts").fetchone()[0]
            if len(stale_ids) > 100 or fts_count != prompt_count:
                # Recovery path for interrupted imports or large delete waves.
                connection.execute("DELETE FROM prompts_fts")
                connection.execute(
                    """
                    INSERT INTO prompts_fts(id, title, description, prompt)
                    SELECT id, title, description, prompt
                    FROM prompts
                    WHERE status = 'active'
                    """
                )
            return len(stale_ids)

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> PromptDocument:
        return PromptDocument(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            prompt=row["prompt"],
            category=row["category"],
            categories=json.loads(row["categories_json"]),
            preview_image=row["preview_image"],
            source_media=json.loads(row["source_media_json"]),
            need_reference_images=bool(row["need_reference_images"]),
            arguments=json.loads(row["arguments_json"]),
            language=row["language"],
            content_hash=row["content_hash"],
            status=row["status"],
        )

    def get(self, prompt_id: str) -> PromptDocument | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM prompts WHERE id = ?", (prompt_id,)
            ).fetchone()
        return self._row_to_document(row) if row else None

    def get_many(self, prompt_ids: Sequence[str]) -> dict[str, PromptDocument]:
        if not prompt_ids:
            return {}
        placeholders = ",".join("?" for _ in prompt_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM prompts WHERE id IN ({placeholders})", tuple(prompt_ids)
            ).fetchall()
        return {row["id"]: self._row_to_document(row) for row in rows}

    def list_prompts(
        self,
        query: str = "",
        status: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[PromptDocument], int]:
        clauses: list[str] = []
        params: list[Any] = []
        normalized_query = query.strip()
        if normalized_query:
            pattern = f"%{normalized_query}%"
            clauses.append(
                "(id LIKE ? OR title LIKE ? OR description LIKE ? "
                "OR prompt LIKE ? OR category LIKE ?)"
            )
            params.extend([pattern] * 5)
        if status in {"active", "inactive"}:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM prompts {where}", params
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM prompts
                {where}
                ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,
                         title COLLATE NOCASE, id
                LIMIT ? OFFSET ?
                """,
                [*params, safe_limit, safe_offset],
            ).fetchall()
        return [self._row_to_document(row) for row in rows], int(total)

    def management_stats(self, embedding_model: str | None = None) -> dict[str, Any]:
        with self.connect() as connection:
            active = connection.execute(
                "SELECT COUNT(*) FROM prompts WHERE status = 'active'"
            ).fetchone()[0]
            inactive = connection.execute(
                "SELECT COUNT(*) FROM prompts WHERE status != 'active'"
            ).fetchone()[0]
            languages = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT language, COUNT(*) FROM prompts "
                    "GROUP BY language ORDER BY COUNT(*) DESC"
                ).fetchall()
            }
            current_embeddings = 0
            if embedding_model:
                current_embeddings = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM embeddings e
                    JOIN prompts p ON p.id = e.id
                    WHERE e.model = ?
                      AND p.status = 'active'
                      AND e.content_hash = p.content_hash
                    """,
                    (embedding_model,),
                ).fetchone()[0]
        file_names = [self.db_path, Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")]
        db_bytes = sum(path.stat().st_size for path in file_names if path.exists())
        stats = self.stats()
        return {
            **stats,
            "active_prompts": int(active),
            "inactive_prompts": int(inactive),
            "languages": languages,
            "db_bytes": db_bytes,
            "current_embedding_model": embedding_model or "",
            "current_embeddings": int(current_embeddings),
        }

    @staticmethod
    def _fts_expression(query: str) -> str:
        tokens: list[str] = []
        current: list[str] = []
        for char in query:
            if char.isalnum() or char in {"_", "-"} or ord(char) > 127:
                current.append(char)
            elif current:
                tokens.append("".join(current))
                current = []
        if current:
            tokens.append("".join(current))
        unique = list(dict.fromkeys(token for token in tokens if token))
        return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in unique[:40])

    def lexical_search(
        self,
        query: str,
        limit: int,
        categories: Sequence[str] = (),
        need_reference_images: bool | None = None,
    ) -> list[str]:
        expression = self._fts_expression(query)
        if not expression:
            return []
        clauses = ["prompts_fts MATCH ?", "p.status = 'active'"]
        params: list[Any] = [expression]
        if categories:
            placeholders = ",".join("?" for _ in categories)
            clauses.append(
                f"(p.category IN ({placeholders}) OR EXISTS ("
                f"SELECT 1 FROM json_each(p.categories_json) WHERE value IN ({placeholders})"
                "))"
            )
            params.extend(categories)
            params.extend(categories)
        if need_reference_images is not None:
            clauses.append("p.need_reference_images = ?")
            params.append(int(need_reference_images))
        params.append(limit)
        sql = f"""
            SELECT p.id
            FROM prompts_fts
            JOIN prompts p ON p.id = prompts_fts.id
            WHERE {' AND '.join(clauses)}
            ORDER BY bm25(prompts_fts, 0.0, 5.0, 2.0, 1.0)
            LIMIT ?
        """
        with self.connect() as connection:
            return [row[0] for row in connection.execute(sql, params).fetchall()]

    def embedding_candidates(
        self, model: str, text_max_chars: int, expected_dimension: int | None = None
    ) -> Iterable[tuple[str, str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT p.id, p.title, p.description, p.prompt, p.category,
                       p.categories_json, p.content_hash
                FROM prompts p
                LEFT JOIN embeddings e ON e.id = p.id AND e.model = ?
                WHERE p.status = 'active'
                  AND (
                    e.id IS NULL
                    OR e.content_hash != p.content_hash
                    OR (? IS NOT NULL AND e.dimension != ?)
                  )
                ORDER BY p.id
                """,
                (model, expected_dimension, expected_dimension),
            ).fetchall()
        for row in rows:
            categories = ", ".join(json.loads(row["categories_json"]))
            text = (
                f"Title: {row['title']}\n"
                f"Description: {row['description']}\n"
                f"Categories: {categories or row['category']}\n"
                f"Prompt: {row['prompt']}"
            )[:text_max_chars]
            yield row["id"], row["content_hash"], text

    def save_embeddings(
        self,
        model: str,
        rows: Sequence[tuple[str, str, np.ndarray]],
    ) -> None:
        if not rows:
            return
        payload = []
        for prompt_id, content_hash, vector in rows:
            normalized = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(normalized))
            if norm:
                normalized = normalized / norm
            payload.append(
                (prompt_id, model, int(normalized.shape[0]), normalized.tobytes(), content_hash)
            )
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO embeddings(id, model, dimension, vector, content_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id, model) DO UPDATE SET
                    dimension=excluded.dimension,
                    vector=excluded.vector,
                    content_hash=excluded.content_hash
                """,
                payload,
            )

    def load_embeddings(self, model: str) -> tuple[list[str], np.ndarray]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.id, e.dimension, e.vector
                FROM embeddings e
                JOIN prompts p ON p.id = e.id
                WHERE e.model = ?
                  AND p.status = 'active'
                  AND e.content_hash = p.content_hash
                ORDER BY e.id
                """,
                (model,),
            ).fetchall()
        if not rows:
            return [], np.empty((0, 0), dtype=np.float32)
        dimensions = {row["dimension"] for row in rows}
        if len(dimensions) != 1:
            raise ValueError(f"Embedding dimension mismatch for model {model}: {dimensions}")
        matrix = np.vstack(
            [np.frombuffer(row["vector"], dtype=np.float32) for row in rows]
        )
        return [row["id"] for row in rows], matrix

    def stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            prompts = connection.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
            embeddings = connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            categories = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT category, COUNT(*) FROM prompts GROUP BY category ORDER BY COUNT(*) DESC"
                ).fetchall()
            }
            models = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT model, COUNT(*) FROM embeddings GROUP BY model"
                ).fetchall()
            }
            translations = connection.execute(
                "SELECT COUNT(*) FROM translations"
            ).fetchone()[0]
            candidate_analyses = connection.execute(
                "SELECT COUNT(*) FROM candidate_analyses"
            ).fetchone()[0]
            workflow_runs = connection.execute(
                "SELECT COUNT(*) FROM workflow_runs"
            ).fetchone()[0]
        return {
            "prompts": prompts,
            "embeddings": embeddings,
            "embedding_models": models,
            "translations": translations,
            "candidate_analyses": candidate_analyses,
            "workflow_runs": workflow_runs,
            "categories": categories,
            "db_path": str(self.db_path),
        }

    def get_translation(
        self, source_hash: str, target_language: str, model: str
    ) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT translated_text FROM translations
                WHERE source_hash = ? AND target_language = ? AND model = ?
                """,
                (source_hash, target_language, model),
            ).fetchone()
        return row[0] if row else None

    def save_translation(
        self,
        source_hash: str,
        target_language: str,
        model: str,
        translated_text: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO translations(source_hash, target_language, model, translated_text)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_hash, target_language, model) DO UPDATE SET
                    translated_text = excluded.translated_text
                """,
                (source_hash, target_language, model, translated_text),
            )

    def get_candidate_analysis(self, cache_key: str, model: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT analysis_json FROM candidate_analyses
                WHERE cache_key = ? AND model = ?
                """,
                (cache_key, model),
            ).fetchone()
        return row[0] if row else None

    def save_candidate_analysis(
        self, cache_key: str, model: str, analysis_json: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO candidate_analyses(cache_key, model, analysis_json)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key, model) DO UPDATE SET
                    analysis_json = excluded.analysis_json
                """,
                (cache_key, model, analysis_json),
            )

    def get_requirement_analysis(self, cache_key: str, model: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT spec_json FROM requirement_analyses
                WHERE cache_key = ? AND model = ?
                """,
                (cache_key, model),
            ).fetchone()
        return row[0] if row else None

    def save_requirement_analysis(
        self, cache_key: str, model: str, spec_json: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO requirement_analyses(cache_key, model, spec_json)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key, model) DO UPDATE SET
                    spec_json = excluded.spec_json
                """,
                (cache_key, model, spec_json),
            )

    @staticmethod
    def _row_to_workflow_run(row: sqlite3.Row, cached: bool = False) -> WorkflowRun:
        return WorkflowRun(
            id=row["id"],
            status=row["status"],
            requirement_spec=RequirementSpec.model_validate_json(
                row["requirement_spec_json"]
            ),
            generated=bool(row["generated"]),
            cached=cached,
            model=row["model"],
            schema_version=row["schema_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            confirmed_at=row["confirmed_at"],
        )

    def create_workflow_run(
        self,
        run_id: str,
        requirement_spec: RequirementSpec,
        generated: bool,
        model: str,
        timestamp: str,
        cached: bool = False,
    ) -> WorkflowRun:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs(
                    id, status, requirement_spec_json, generated, model,
                    schema_version, created_at, updated_at, confirmed_at
                ) VALUES (?, 'requirements_ready', ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_id,
                    requirement_spec.model_dump_json(),
                    int(generated),
                    model,
                    requirement_spec.schema_version,
                    timestamp,
                    timestamp,
                ),
            )
        result = self.get_workflow_run(run_id)
        assert result is not None
        result.cached = cached
        return result

    def get_workflow_run(self, run_id: str) -> WorkflowRun | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._row_to_workflow_run(row) if row else None

    def list_workflow_runs(self, limit: int = 20) -> list[WorkflowRun]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_workflow_run(row) for row in rows]

    def delete_workflow_run(self, run_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM workflow_runs WHERE id = ?", (run_id,)
            )
        return bool(cursor.rowcount)

    def confirm_workflow_requirements(
        self, run_id: str, requirement_spec: RequirementSpec, timestamp: str
    ) -> WorkflowRun | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE workflow_runs
                SET status = 'requirements_confirmed',
                    requirement_spec_json = ?,
                    schema_version = ?,
                    updated_at = ?,
                    confirmed_at = ?
                WHERE id = ?
                """,
                (
                    requirement_spec.model_dump_json(),
                    requirement_spec.schema_version,
                    timestamp,
                    timestamp,
                    run_id,
                ),
            )
        return self.get_workflow_run(run_id) if cursor.rowcount else None
