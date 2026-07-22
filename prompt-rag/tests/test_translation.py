from prompt_rag.database import PromptStore
from prompt_rag.translation import PromptTranslator, materialize_prompt


class FakeMiMoGenerator:
    enabled = True
    model = "mimo-test"
    calls = 0

    def translate_to_chinese(self, text: str) -> str:
        self.calls += 1
        assert "{argument" not in text
        assert "1990s American sci-fi action movie" in text
        return "一张来自20世纪90年代美国科幻动作电影的电影剧照。"


def test_materialize_prompt_uses_argument_defaults():
    source = (
        'A still from a {argument name="genre" '
        'default="1990s American sci-fi action movie"}.'
    )

    result = materialize_prompt(source)

    assert result == "A still from a 1990s American sci-fi action movie."


def test_translation_is_cached_in_sqlite(tmp_path):
    store = PromptStore(tmp_path / "translations.db")
    generator = FakeMiMoGenerator()
    translator = PromptTranslator(store, generator)
    source = (
        'A still from a {argument name="genre" '
        'default="1990s American sci-fi action movie"}.'
    )

    first = translator.to_chinese(source)
    second = translator.to_chinese(source)

    assert first == second
    assert generator.calls == 1
    assert store.stats()["translations"] == 1
