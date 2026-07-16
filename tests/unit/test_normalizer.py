"""
Unit tests for DialectNormalizer, including Whisper hallucination cleanup.
"""

import pytest

from src.services.speech.normalizer import DialectNormalizer


@pytest.fixture
def normalizer() -> DialectNormalizer:
    return DialectNormalizer()


# ---------------------------------------------------------------------------
# Whisper hallucination cleanup
# ---------------------------------------------------------------------------

class TestHallucinationCleanup:

    def test_removes_cyrillic(self, normalizer: DialectNormalizer):
        """Cyrillic characters are removed from Tamil text."""
        text = "இது ஒரு Поэтому கோபி கலர்"
        result = normalizer.normalize(text, "ta", None)
        assert "Поэтому" not in result
        assert "கோபி" in result
        assert "கலர்" in result

    def test_removes_greek(self, normalizer: DialectNormalizer):
        """Greek characters are removed."""
        text = "நீங்களுக்கு ρω டெல்வெரி"
        result = normalizer.normalize(text, "ta", None)
        assert "ρω" not in result
        assert "டெல்வெரி" in result

    def test_removes_japanese(self, normalizer: DialectNormalizer):
        """Japanese characters are removed."""
        text = "ஆலோなるほど இயல்பு"
        result = normalizer.normalize(text, "ta", None)
        assert "なるほど" not in result
        assert "இயல்பு" in result

    def test_removes_whisper_tokens(self, normalizer: DialectNormalizer):
        """Whisper language tokens like <|eu|> are removed."""
        text = "இது <|eu|> ஒரு சீலை"
        result = normalizer.normalize(text, "ta", None)
        assert "<|eu|>" not in result
        assert "ஒரு" in result

    def test_removes_hallucinated_words(self, normalizer: DialectNormalizer):
        """Known hallucinated English words are removed."""
        text = "பின்னே சிங்கலும் playback coral"
        result = normalizer.normalize(text, "ta", None)
        assert "playback" not in result
        assert "coral" not in result
        assert "பின்னே" in result

    def test_preserves_legitimate_english(self, normalizer: DialectNormalizer):
        """Legitimate English words used in code-switching are preserved."""
        text = "இது coffee color அணை"
        result = normalizer.normalize(text, "ta", None)
        assert "coffee" in result
        assert "color" in result

    def test_preserves_english_language_text(self, normalizer: DialectNormalizer):
        """English-detected text is not touched by hallucination cleanup."""
        text = "I want a red silk saree Поэтому"
        result = normalizer.normalize(text, "en", None)
        # English text is not cleaned for foreign scripts
        assert "Поэтому" in result.lower() or "поэтому" in result.lower()

    def test_cleans_multiple_issues(self, normalizer: DialectNormalizer):
        """Multiple hallucination types cleaned in one pass."""
        text = "இது ஒரு கோபி கpreadக்கலர் அணை, regardez, Поэтому நல்ல"
        result = normalizer.normalize(text, "ta", None)
        assert "regardez" not in result
        assert "Поэтому" not in result
        assert "நல்ல" in result

    def test_no_double_spaces_after_cleanup(self, normalizer: DialectNormalizer):
        """Cleanup doesn't leave double spaces."""
        text = "இது  Поэтому  நல்ல  regardez  சீலை"
        result = normalizer.normalize(text, "ta", None)
        assert "  " not in result


# ---------------------------------------------------------------------------
# Malayalam product normalization
# ---------------------------------------------------------------------------

class TestMalayalamNormalization:

    def test_kasavu_variant_normalized(self, normalizer: DialectNormalizer):
        text = "ഒരു കാസവ് സാരി വേണം"
        result = normalizer.normalize(text, "ml", None)
        assert "കസവ്" in result

    def test_churidar_variant(self, normalizer: DialectNormalizer):
        text = "ചുരിദർ ഒന്ന് കാണിക്കൂ"
        result = normalizer.normalize(text, "ml", None)
        assert "ചുരിദാർ" in result


# ---------------------------------------------------------------------------
# Tamil product normalization
# ---------------------------------------------------------------------------

class TestTamilNormalization:

    def test_pudavai_variant(self, normalizer: DialectNormalizer):
        text = "புடைவை ஒன்று வேண்டும்"
        result = normalizer.normalize(text, "ta", None)
        assert "புடவை" in result

    def test_chennai_dialect_vocab(self, normalizer: DialectNormalizer):
        text = "வேணு ஒரு புடவை"
        result = normalizer.normalize(text, "ta", "chennai")
        assert "வேணும்" in result


# ---------------------------------------------------------------------------
# Telugu normalization
# ---------------------------------------------------------------------------

class TestTeluguNormalization:

    def test_removes_english_article_before_telugu(self, normalizer: DialectNormalizer):
        """'the' before Telugu script is removed."""
        text = "the చీర బాగుంది"
        result = normalizer.normalize(text, "te", None)
        assert result.startswith("చీర")

    def test_telangana_verb_normalization(self, normalizer: DialectNormalizer):
        text = "గావాల ఈ చీర"
        result = normalizer.normalize(text, "te", "telangana")
        assert "గావాలె" in result


# ---------------------------------------------------------------------------
# Kannada normalization
# ---------------------------------------------------------------------------

class TestKannadaNormalization:

    def test_saree_to_seere(self, normalizer: DialectNormalizer):
        """ಸಾರಿ normalized to ಸೀರೆ (Kannada native form)."""
        text = "ಒಂದು ಸಾರಿ ಬೇಕು"
        result = normalizer.normalize(text, "kn", None)
        assert "ಸೀರೆ" in result

    def test_kurta_to_kurte(self, normalizer: DialectNormalizer):
        """ಕುರ್ತಾ normalized to ಕುರ್ತೆ."""
        text = "ಕುರ್ತಾ ತೋರಿಸಿ"
        result = normalizer.normalize(text, "kn", None)
        assert "ಕುರ್ತೆ" in result


# ---------------------------------------------------------------------------
# Generic / English normalization
# ---------------------------------------------------------------------------

class TestGenericNormalization:

    def test_kasavu_transliteration(self, normalizer: DialectNormalizer):
        text = "I want a kaasavu saree"
        result = normalizer.normalize(text, "en", None)
        assert "kasavu" in result

    def test_churidar_spelling(self, normalizer: DialectNormalizer):
        text = "show me churidaar options"
        result = normalizer.normalize(text, "en", None)
        assert "churidar" in result

    def test_empty_text(self, normalizer: DialectNormalizer):
        assert normalizer.normalize("", "ta", None) == ""

    def test_none_dialect_is_safe(self, normalizer: DialectNormalizer):
        result = normalizer.normalize("நான் ஒரு புடவை வேண்டும்", "ta", None)
        assert "புடவை" in result
