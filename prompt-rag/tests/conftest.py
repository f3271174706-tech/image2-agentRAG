from __future__ import annotations

import json

import pytest


@pytest.fixture
def sample_jsonl(tmp_path):
    records = [
        {
            "id": "p-avatar",
            "title": "Neon Cyberpunk Avatar",
            "description": "A dramatic profile portrait with neon lighting.",
            "prompt": "Create a cyberpunk portrait, neon rim light, dark city background.",
            "category": "profile-avatar",
            "preview_image": "https://example.com/avatar.jpg",
            "source_media": ["https://example.com/avatar.jpg"],
            "need_reference_images": False,
            "arguments": [],
            "language": "en",
            "content_hash": "a1",
            "status": "active",
            "metadata": {"categories": ["profile-avatar"]},
        },
        {
            "id": "p-product",
            "title": "Minimal Product Photo",
            "description": "Clean studio product photography.",
            "prompt": "A minimalist white-background studio photograph of a luxury bottle.",
            "category": "ecommerce-main-image",
            "preview_image": "https://example.com/product.jpg",
            "source_media": ["https://example.com/product.jpg"],
            "need_reference_images": True,
            "arguments": [],
            "language": "en",
            "content_hash": "b2",
            "status": "active",
            "metadata": {"categories": ["ecommerce-main-image", "product-marketing"]},
        },
        {
            "id": "p-poster",
            "title": "Retro Travel Poster",
            "description": "Vintage tourism poster.",
            "prompt": "A vintage travel poster featuring mountains and a railway.",
            "category": "poster-flyer",
            "preview_image": "https://example.com/poster.jpg",
            "source_media": ["https://example.com/poster.jpg"],
            "need_reference_images": False,
            "arguments": [],
            "language": "en",
            "content_hash": "c3",
            "status": "active",
            "metadata": {"categories": ["poster-flyer", "social-media-post"]},
        },
    ]
    path = tmp_path / "prompts.jsonl"
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path

