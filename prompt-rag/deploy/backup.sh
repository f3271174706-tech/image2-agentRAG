#!/usr/bin/env bash
set -euo pipefail

DB_PATH="/opt/prompt-rag/data/prompt_rag.db"
BACKUP_DIR="/opt/prompt-rag/backups"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TEMP_PATH="$BACKUP_DIR/prompt_rag-$STAMP.db"

umask 077
mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" ".timeout 30000" ".backup '$TEMP_PATH'"
gzip -9 "$TEMP_PATH"
find "$BACKUP_DIR" -type f -name 'prompt_rag-*.db.gz' -mtime +14 -delete
