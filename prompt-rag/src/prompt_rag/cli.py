from __future__ import annotations

import json
import sys
from dataclasses import asdict

import typer

from .config import get_settings
from .database import PromptStore
from .embeddings import build_embedder
from .ingest import ingest_jsonl
from .models import SearchRequest
from .service import PromptRAGService


app = typer.Typer(no_args_is_help=True, help="Prompt RAG management CLI")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _settings_store() -> tuple:
    settings = get_settings()
    settings.prepare_paths()
    store = PromptStore(settings.db_path)
    return settings, store


@app.command()
def ingest(with_embeddings: bool = typer.Option(False, "--with-embeddings")) -> None:
    """Import the normalized JSONL and optionally build dense vectors."""
    settings, store = _settings_store()
    embedder = build_embedder(settings) if with_embeddings else None
    if with_embeddings and embedder is None:
        raise typer.BadParameter("Configure PROMPT_RAG_EMBEDDING_PROVIDER first")
    result = ingest_jsonl(
        settings.source_path,
        store,
        embedder,
        embedding_batch_size=settings.embedding_batch_size,
        embedding_text_max_chars=settings.embedding_text_max_chars,
    )
    typer.echo(json.dumps(asdict(result), ensure_ascii=False, indent=2))


@app.command()
def search(query: str, top_k: int = 5, category: list[str] | None = None) -> None:
    """Search from the command line."""
    settings, store = _settings_store()
    embedder = build_embedder(settings)
    service = PromptRAGService(settings, store, embedder)
    result = service.search(
        SearchRequest(query=query, top_k=top_k, categories=category or [])
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def stats() -> None:
    """Show index statistics."""
    _, store = _settings_store()
    typer.echo(json.dumps(store.stats(), ensure_ascii=False, indent=2))


@app.command()
def serve() -> None:
    """Start the FastAPI service."""
    import uvicorn

    settings = get_settings()
    uvicorn.run("prompt_rag.api:app", host=settings.host, port=settings.port, reload=False)
