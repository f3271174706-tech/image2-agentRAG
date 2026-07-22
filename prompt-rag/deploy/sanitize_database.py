from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: sanitize_database.py SOURCE_DB TARGET_DB")
    source_path = Path(sys.argv[1]).resolve()
    target_path = Path(sys.argv[2]).resolve()
    if source_path == target_path:
        raise SystemExit("source and target database paths must differ")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()

    with sqlite3.connect(source_path) as source, sqlite3.connect(target_path) as target:
        source.backup(target)

    with sqlite3.connect(target_path) as connection:
        connection.execute(
            "DELETE FROM embeddings WHERE model != ? OR dimension != ?",
            ("text-embedding-v4", 1024),
        )
        for table in (
            "workflow_runs",
            "requirement_analyses",
            "candidate_analyses",
            "translations",
        ):
            connection.execute(f'DELETE FROM "{table}"')
        connection.commit()
        prompts = connection.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
        vectors = connection.execute(
            "SELECT COUNT(*) FROM embeddings WHERE model = ? AND dimension = ?",
            ("text-embedding-v4", 1024),
        ).fetchone()[0]
        private_rows = sum(
            connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in ("workflow_runs", "requirement_analyses", "candidate_analyses", "translations")
        )
        if prompts <= 0 or vectors != prompts or private_rows:
            raise SystemExit(
                f"release database validation failed: prompts={prompts}, vectors={vectors}, private_rows={private_rows}"
            )
        connection.execute("VACUUM")
    print(f"sanitized database: prompts={prompts}, vectors={vectors}, private_rows=0")


if __name__ == "__main__":
    main()
