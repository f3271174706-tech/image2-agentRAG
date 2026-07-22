from __future__ import annotations

import hashlib
import re

from .database import PromptStore
from .generation import ChatGenerator


ARGUMENT_ESCAPED = re.compile(
    r'\{argument\s+name=\\"([^\"]*?)\\"\s+default=\\"([^\"]*?)\\"\}'
)
ARGUMENT_PLAIN = re.compile(
    r'\{argument\s+name="([^"]*?)"\s+default="([^"]*?)"\}'
)


def materialize_prompt(prompt: str) -> str:
    """Replace dynamic template arguments with their defaults before translation."""

    def replace(match: re.Match[str]) -> str:
        return match.group(2) or match.group(1)

    result = ARGUMENT_ESCAPED.sub(replace, prompt)
    return ARGUMENT_PLAIN.sub(replace, result)


def is_mostly_chinese(text: str) -> bool:
    visible = [character for character in text if not character.isspace()]
    if not visible:
        return True
    cjk = sum("\u4e00" <= character <= "\u9fff" for character in visible)
    return cjk / len(visible) >= 0.30


class PromptTranslator:
    def __init__(
        self,
        store: PromptStore,
        generator: ChatGenerator | None,
    ):
        self.store = store
        self.generator = generator

    @property
    def enabled(self) -> bool:
        return bool(self.generator and self.generator.enabled)

    def to_chinese(self, prompt: str) -> str:
        materialized = materialize_prompt(prompt)
        if is_mostly_chinese(materialized) or not self.enabled:
            return materialized

        assert self.generator is not None
        source_hash = hashlib.sha256(materialized.encode("utf-8")).hexdigest()
        cached = self.store.get_translation(
            source_hash, "zh", self.generator.model
        )
        if cached:
            return cached

        translated = self.generator.translate_to_chinese(materialized).strip()
        if translated.startswith("```") and translated.endswith("```"):
            translated = translated.strip("`").strip()
        if not translated:
            return materialized
        self.store.save_translation(
            source_hash, "zh", self.generator.model, translated
        )
        return translated

