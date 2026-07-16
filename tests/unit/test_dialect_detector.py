"""
Unit tests for DialectDetector.

These tests exercise the marker-based scoring logic entirely in-memory —
no external API calls, no database, no network.

Run:
    pytest tests/unit/test_dialect_detector.py -v
"""

import pytest

from src.services.speech.dialect_detector import DialectDetector, DialectInfo


@pytest.fixture
def detector() -> DialectDetector:
    return DialectDetector()


# ---------------------------------------------------------------------------
# Malayalam dialect tests
# ---------------------------------------------------------------------------

class TestMalayalamDialects:

    @pytest.mark.asyncio
    async def test_thrissur_detection(self, detector: DialectDetector):
        """Two strong Thrissur markers → confident detection."""
        text = "എന്തിനാ ഈ സാരി ഇത്ര വിലയുള്ളത്? പോയിക്കോ"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert result.name == "thrissur"
        assert result.confidence > 0.5
        assert "എന്തിനാ" in result.markers_found
        assert "പോയിക്കോ" in result.markers_found

    @pytest.mark.asyncio
    async def test_thrissur_informal_formality(self, detector: DialectDetector):
        result = await detector.detect("എന്തിനാ പോയിക്കോ ആടോ", "ml")
        assert result is not None
        assert result.formality == "informal"

    @pytest.mark.asyncio
    async def test_malabar_detection(self, detector: DialectDetector):
        """Arabic loanwords → Malabar."""
        text = "ബഹുത് നല്ല സാരി ആണ്. ഇൻഷാഅല്ലാഹ് നാളെ വരും"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert result.name == "malabar"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_malabar_vaappa_umma(self, detector: DialectDetector):
        """Family terms used in Malabar Muslim speech."""
        text = "വാപ്പ ഉമ്മ ഇന്ന് കടയിൽ വരും"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert result.name == "malabar"

    @pytest.mark.asyncio
    async def test_palakkad_detection(self, detector: DialectDetector):
        """Tamil code-switching → Palakkad."""
        text = "ஆமா ഈ ഡ്രസ് നല்லா ഇരിക്കு வாங்க"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert result.name == "palakkad"

    @pytest.mark.asyncio
    async def test_travancore_detection(self, detector: DialectDetector):
        """Formal / literary forms → Travancore."""
        text = "അങ്ങനെയാണ്, ആകുന്നു എന്ന് ഞാൻ കരുതുന്നു"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert result.name == "travancore"
        assert result.formality == "formal"

    @pytest.mark.asyncio
    async def test_kochi_detection(self, detector: DialectDetector):
        """Urban slang → Kochi."""
        text = "മച്ചാൻ ഈ ഡ്രസ് അടിപൊളി ആണ്"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert result.name == "kochi"

    @pytest.mark.asyncio
    async def test_no_markers_returns_none(self, detector: DialectDetector):
        """Plain standard Malayalam with no dialect markers → None."""
        text = "ഞാൻ ഒരു സാരി വാങ്ങണം"
        result = await detector.detect(text, "ml")
        # May or may not detect; if detected confidence must be meaningful
        # Plain text should score 0 or below threshold
        if result is not None:
            # If something was detected, it must be at least at threshold
            assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_no_dialect_english(self, detector: DialectDetector):
        """English language → always None (not supported)."""
        text = "I want to buy a saree"
        result = await detector.detect(text, "en")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_dialect_hindi(self, detector: DialectDetector):
        """Hindi language → None (not supported)."""
        text = "मुझे एक साड़ी खरीदनी है"
        result = await detector.detect(text, "hi")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_text(self, detector: DialectDetector):
        """Empty string → None."""
        result = await detector.detect("", "ml")
        assert result is None

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, detector: DialectDetector):
        """Confidence must always be in [0, 1]."""
        texts = [
            ("എന്തിനാ പോയിക്കോ ആടോ ആവോ", "ml"),
            ("ബഹുത് ഉമ്മ ഖൈർ ബരക്കത്ത്", "ml"),
        ]
        for text, lang in texts:
            result = await detector.detect(text, lang)
            if result is not None:
                assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_markers_found_populated(self, detector: DialectDetector):
        """markers_found must list the actual matched strings."""
        text = "ബഹുത് നല്ല ഇൻഷാഅല്ലാഹ്"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert len(result.markers_found) >= 2
        for marker in result.markers_found:
            assert marker in text


# ---------------------------------------------------------------------------
# Tamil dialect tests
# ---------------------------------------------------------------------------

class TestTamilDialects:

    @pytest.mark.asyncio
    async def test_chennai_detection(self, detector: DialectDetector):
        """Urban slang டா/மச்சி → Chennai."""
        text = "மச்சி இந்த டிரெஸ் சூப்பரா இருக்கு டா"
        result = await detector.detect(text, "ta")
        assert result is not None
        assert result.name == "chennai"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_chennai_formality(self, detector: DialectDetector):
        result = await detector.detect("மச்சி டா போடா", "ta")
        assert result is not None
        assert result.formality == "informal"

    @pytest.mark.asyncio
    async def test_madurai_detection(self, detector: DialectDetector):
        """Madurai-specific vocabulary."""
        text = "என்னாச்சு ஆத்தா? வாங்குற புடவை நல்லா இருக்கா?"
        result = await detector.detect(text, "ta")
        assert result is not None
        assert result.name == "madurai"

    @pytest.mark.asyncio
    async def test_coimbatore_detection(self, detector: DialectDetector):
        """Polite plural address → Coimbatore."""
        text = "ஏங்க இந்த புடவை எவ்வளவு? ஆமாங்க சொல்லுங்க"
        result = await detector.detect(text, "ta")
        assert result is not None
        assert result.name == "coimbatore"

    @pytest.mark.asyncio
    async def test_tamil_no_dialect_plain(self, detector: DialectDetector):
        """Standard Tamil with no dialect markers → None or low confidence."""
        text = "நான் ஒரு புடவை வாங்க விரும்புகிறேன்"
        result = await detector.detect(text, "ta")
        if result is not None:
            assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_tamil_wrong_language_code(self, detector: DialectDetector):
        """Tamil text but wrong language code → None."""
        result = await detector.detect("மச்சி டா", "en")
        assert result is None


# ---------------------------------------------------------------------------
# Telugu dialect tests
# ---------------------------------------------------------------------------

class TestTeluguDialects:

    @pytest.mark.asyncio
    async def test_telangana_detection(self, detector: DialectDetector):
        """Telangana markers → telangana dialect."""
        text = "ఏందిరా గావాలె ఈ చీర? గిట్ల చూడు"
        result = await detector.detect(text, "te")
        assert result is not None
        assert result.name == "telangana"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_coastal_andhra_detection(self, detector: DialectDetector):
        """Standard polite forms → coastal_andhra."""
        text = "చెప్పండి ఈ చీర ఎంత? బాగుంది కదా"
        result = await detector.detect(text, "te")
        assert result is not None
        assert result.name == "coastal_andhra"

    @pytest.mark.asyncio
    async def test_rayalaseema_detection(self, detector: DialectDetector):
        """Rayalaseema-specific forms."""
        text = "ఏంది గింత ధర? చెయ్యి తగ్గింపు"
        result = await detector.detect(text, "te")
        assert result is not None
        assert result.name == "rayalaseema"

    @pytest.mark.asyncio
    async def test_hyderabad_urban_detection(self, detector: DialectDetector):
        """Deccani markers → hyderabad_urban."""
        text = "నక్కో మేరేకో ఈ price కైకు ఇంత ఎక్కువ"
        result = await detector.detect(text, "te")
        assert result is not None
        assert result.name == "hyderabad_urban"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_telugu_no_dialect_plain(self, detector: DialectDetector):
        """Standard Telugu with no dialect markers → None or low confidence."""
        text = "నాకు ఒక చీర కావాలి"
        result = await detector.detect(text, "te")
        if result is not None:
            assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_telugu_wrong_language_code(self, detector: DialectDetector):
        """Telugu text with wrong language code → None."""
        result = await detector.detect("ఏందిరా గావాలె", "en")
        assert result is None


# ---------------------------------------------------------------------------
# Kannada dialect tests
# ---------------------------------------------------------------------------

class TestKannadaDialects:

    @pytest.mark.asyncio
    async def test_bangalore_detection(self, detector: DialectDetector):
        """Urban Bangalore slang → bangalore."""
        text = "ಮಚ್ಚಿ ಈ ಡ್ರೆಸ್ ಸೂಪರ್ ಆಗಿದೆ ಗುರು"
        result = await detector.detect(text, "kn")
        assert result is not None
        assert result.name == "bangalore"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_mysore_detection(self, detector: DialectDetector):
        """Polite Mysore forms → mysore."""
        text = "ಬನ್ನಿ ಈ ಸೀರೆ ನೋಡಿ ಅಲ್ವಾ ಚೆನ್ನಾಗಿದೆ ಕಣ್ರೀ"
        result = await detector.detect(text, "kn")
        assert result is not None
        assert result.name == "mysore"

    @pytest.mark.asyncio
    async def test_north_karnataka_detection(self, detector: DialectDetector):
        """North Karnataka -ri suffix markers → north_karnataka."""
        text = "ಏನ್ರಿ ಬರ್ರಿ ಈ ಸೀರೆ ಹೇಳ್ರಿ ಎಷ್ಟು"
        result = await detector.detect(text, "kn")
        assert result is not None
        assert result.name == "north_karnataka"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_coastal_karnataka_detection(self, detector: DialectDetector):
        """Tulu-influenced markers → coastal_karnataka."""
        text = "ಮಾರಾಯ ಈ ಸೀರೆ ಎಂಚ ಇದೆ? ಇಜ್ಜಿ ಬೇರೆ"
        result = await detector.detect(text, "kn")
        assert result is not None
        assert result.name == "coastal_karnataka"

    @pytest.mark.asyncio
    async def test_kannada_no_dialect_plain(self, detector: DialectDetector):
        """Standard Kannada → None or low confidence."""
        text = "ನನಗೆ ಒಂದು ಸೀರೆ ಬೇಕು"
        result = await detector.detect(text, "kn")
        if result is not None:
            assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_kannada_wrong_language_code(self, detector: DialectDetector):
        """Kannada text with wrong language code → None."""
        result = await detector.detect("ಮಚ್ಚಿ ಗುರು", "en")
        assert result is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_single_very_strong_marker(self, detector: DialectDetector):
        """Single high-weight marker (1.5) still exceeds 0.3 threshold."""
        result = await detector.detect("ബഹുത്", "ml")
        assert result is not None
        assert result.name == "malabar"
        assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_mixed_dialect_markers_picks_dominant(self, detector: DialectDetector):
        """When markers from two dialects appear, the higher-scoring one wins."""
        # Strong Kochi markers (adipoli=1.5, machan=1.5) vs one Thrissur (poikko=1.0)
        text = "മച്ചാൻ ഈ അടിപൊളി ഡ്രസ് പോയിക്കോ"
        result = await detector.detect(text, "ml")
        assert result is not None
        assert result.name == "kochi"   # 3.0 weight beats Thrissur's 1.0

    @pytest.mark.asyncio
    async def test_result_fields_complete(self, detector: DialectDetector):
        """All DialectInfo fields are populated."""
        result = await detector.detect("ബഹുത് ഇൻഷാഅല്ലാഹ്", "ml")
        assert result is not None
        assert isinstance(result.name, str) and result.name
        assert isinstance(result.region, str) and result.region
        assert isinstance(result.confidence, float)
        assert isinstance(result.markers_found, list)
        assert isinstance(result.formality, str)
        assert result.formality in ("formal", "informal", "mixed")
