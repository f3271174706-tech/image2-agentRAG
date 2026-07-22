import httpx
import numpy as np
import pytest

from prompt_rag.embeddings import OpenAICompatibleEmbedder


def test_openai_compatible_embedder_requests_and_validates_dimensions():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [3.0, 4.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 0.0, 2.0]},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    embedder = OpenAICompatibleEmbedder(
        "https://example.test/compatible-mode/v1",
        "secret",
        "text-embedding-v4",
        dimensions=3,
        client=client,
    )

    vectors = embedder.embed_documents(["one", "two"])

    assert captured["dimensions"] == 3
    assert captured["encoding_format"] == "float"
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


def test_openai_compatible_embedder_rejects_wrong_dimension():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]}
            )
        )
    )
    embedder = OpenAICompatibleEmbedder(
        "https://example.test/v1",
        "secret",
        "text-embedding-v4",
        dimensions=3,
        client=client,
    )

    with pytest.raises(ValueError, match="expected 3"):
        embedder.embed_query("query")


def test_openai_compatible_embedder_retries_transport_disconnect(monkeypatch):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("disconnected", request=request)
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]}
        )

    monkeypatch.setattr("prompt_rag.embeddings.time.sleep", lambda _: None)
    embedder = OpenAICompatibleEmbedder(
        "https://example.test/v1",
        "secret",
        "text-embedding-v4",
        dimensions=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert embedder.embed_query("query").tolist() == [1.0, 0.0]
    assert attempts == 2
