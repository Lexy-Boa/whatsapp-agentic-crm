"""
Normalize transcribed text based on detected language and dialect.

Goals:
  1. Remove foreign-language hallucinations injected by Whisper (Russian,
     French, German, Japanese, etc. fragments that appear in South Indian
     language transcriptions).
  2. Standardize fashion product name spelling variations so downstream
     product-matching code can work against a stable vocabulary.
  3. Handle common Whisper transcription inconsistencies for ML/TA/TE/KN.
  4. Apply light dialect-specific vocabulary normalization.

Normalization is intentionally conservative — we never change meaning,
only resolve clear spelling variants to a canonical form.
"""

from __future__ import annotations

import re
import unicodedata


def _ub(pattern: str, replacement: str) -> tuple[str, str]:
    """
    Convert \\b-bounded patterns to Unicode-aware boundaries.

    Python's \\b only matches ASCII word boundaries, so patterns like
    \\bকসভ্\\b fail on Indic scripts. We replace \\b with lookaround
    assertions that match the start/end of string or any whitespace/
    punctuation boundary.
    """
    p = pattern
    # Replace leading \b
    if p.startswith(r"\b"):
        p = r"(?:(?<=\s)|(?<=^))" + p[2:]
    # Replace trailing \b
    if p.endswith(r"\b"):
        p = p[:-2] + r"(?=\s|$|[.,!?;:])"
    return (p, replacement)


# ---------------------------------------------------------------------------
# Whisper hallucination cleanup (applies to ALL languages)
# ---------------------------------------------------------------------------

# Unicode script ranges for foreign scripts that should never appear in
# South Indian language transcriptions. Whisper hallucinates these when
# it's uncertain about the audio content.
_FOREIGN_SCRIPT_RANGES = [
    ("\u0400", "\u04FF"),   # Cyrillic (Russian, Ukrainian, etc.)
    ("\u0370", "\u03FF"),   # Greek
    ("\u3040", "\u309F"),   # Hiragana (Japanese)
    ("\u30A0", "\u30FF"),   # Katakana (Japanese)
    ("\u4E00", "\u9FFF"),   # CJK Unified Ideographs (Chinese/Japanese/Korean)
    ("\u0600", "\u06FF"),   # Arabic (not expected in native script transcriptions)
    ("\u0590", "\u05FF"),   # Hebrew
    ("\uAC00", "\uD7AF"),   # Hangul (Korean)
    ("\u00C0", "\u00FF"),   # Latin Extended-A (ñ, ü, ö, etc. — not in English loanwords)
    ("\u0100", "\u024F"),   # Latin Extended-B (ą, ę, ś, etc. — Polish, etc.)
    ("\u1E00", "\u1EFF"),   # Latin Extended Additional (Vietnamese ả, ụ, etc.)
]

# Build a single regex character class for foreign scripts
_foreign_chars = "".join(f"{lo}-{hi}" for lo, hi in _FOREIGN_SCRIPT_RANGES)
_FOREIGN_SCRIPT_RE = re.compile(f"[{_foreign_chars}]+")

# Whisper sometimes inserts these English/foreign words into South Indian
# language transcriptions. Remove only when they appear mixed into native
# script text and are clearly hallucinated (not legitimate code-switching).
_HALLUCINATED_WORDS = {
    # Common Whisper hallucinations observed in production
    "regardez", "prochaine", "plötzlich", "Поэтому", "więcej",
    "niños", "saturated", "inspired", "playback", "coral",
    "preoccupative", "utilization", "bookstore", "bedrooms",
    "oven", "wider", "subscribers", "SUBSCRI", "GG", "HIS",
    # Whisper special tokens that leak into output
    "<|eu|>", "<|en|>", "<|ta|>", "<|ml|>", "<|te|>", "<|kn|>",
}

# Regex to match Whisper's leaked language tokens
_WHISPER_TOKEN_RE = re.compile(r"<\|[a-z]{2}\|>")


def _clean_whisper_hallucinations(text: str, language: str) -> str:
    """
    Remove foreign-script hallucinations from transcribed text.

    Only applies when the text is in a South Indian language (ml, ta, te, kn).
    Preserves legitimate English words that commonly appear in code-switching
    (e.g., "delivery", "color", "size", "price", "discount", "online").
    """
    if language not in ("ml", "ta", "te", "kn"):
        return text

    # Remove Whisper special tokens
    text = _WHISPER_TOKEN_RE.sub("", text)

    # Remove foreign script characters (Cyrillic, Greek, CJK, etc.)
    text = _FOREIGN_SCRIPT_RE.sub("", text)

    # Remove known hallucinated words (case-insensitive)
    for word in _HALLUCINATED_WORDS:
        # Use word boundary to avoid partial matches inside native words
        text = re.sub(r"\b" + re.escape(word) + r"\b", "", text, flags=re.IGNORECASE)

    # Clean up resulting whitespace
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s*,\s*,", ",", text)  # double commas from removed words
    text = re.sub(r"^\s*,\s*", "", text)    # leading comma
    text = re.sub(r"\s*,\s*$", "", text)    # trailing comma

    return text.strip()


class DialectNormalizer:
    """Normalize transcribed text to standard forms."""

    def normalize(
        self,
        text: str,
        language: str,
        dialect: str | None,
    ) -> str:
        """
        Args:
            text: Raw transcription text.
            language: ISO 639-1 code (ml, ta, te, kn, en, …).
            dialect: Detected dialect name, or None.

        Returns:
            Normalized text.  If no rules apply, the original text is
            returned unchanged.
        """
        if not text:
            return text

        # Step 0: Clean Whisper hallucinations (all South Indian languages)
        text = _clean_whisper_hallucinations(text, language)

        if language == "ml":
            text = _normalize_malayalam(text, dialect)
        elif language == "ta":
            text = _normalize_tamil(text, dialect)
        elif language == "te":
            text = _normalize_telugu(text, dialect)
        elif language == "kn":
            text = _normalize_kannada(text, dialect)
        else:
            text = _normalize_generic(text)

        return text.strip()


# ---------------------------------------------------------------------------
# Malayalam normalizations
# ---------------------------------------------------------------------------

# (pattern, replacement) — applied in order; pattern can be str or regex
_ML_PRODUCT_VARIANTS: list[tuple[str, str]] = [
    # Kasavu (gold-border saree from Kerala) — many transliteration spellings
    _ub(r"\bകാസവ്\b", "കസവ്"),
    _ub(r"\bകശ്ശ\b", "കസവ്"),
    _ub(r"\bകസാവ്\b", "കസവ്"),
    # Pattu (silk) variants
    _ub(r"\bപട്ടൂ\b", "പട്ടു"),
    _ub(r"\bപട്ടൂസ്\b", "പട്ടുസ്"),
    # Mundu (dhoti) variants
    _ub(r"\bമുണ്ടൂ\b", "മുണ്ട്"),
    # Set saree (two-piece set)
    _ub(r"\bസെറ്റ് സാരി\b", "സെറ്റ്‌സാരി"),
    # Churidar variants
    _ub(r"\bചുരിദർ\b", "ചുരിദാർ"),
    _ub(r"\bചൂരിദർ\b", "ചുരിദാർ"),
    # Kurta variants
    _ub(r"\bകുർത\b", "കുർത്ത"),
]

# Dialect-specific vocabulary → standard Malayalam
_ML_DIALECT_VOCAB: dict[str, list[tuple[str, str]]] = {
    "malabar": [
        _ub(r"\bബഹു\b", "ബഹുത്"),
    ],
    "palakkad": [
        _ub(r"\bஆமாா\b", "ஆமா"),
        _ub(r"\bவாங்கா\b", "வாங்க"),
    ],
    "thrissur": [
        (r"എന്തിന(?!ാ)", "എന്തിനാ"),
    ],
}


def _normalize_malayalam(text: str, dialect: str | None) -> str:
    # 1. Product name standardization
    for pattern, replacement in _ML_PRODUCT_VARIANTS:
        text = re.sub(pattern, replacement, text)

    # 2. Common Whisper spacing issues in Malayalam
    text = re.sub(r"\u200c{2,}", "\u200c", text)   # deduplicate ZWNJ
    text = re.sub(r"\u200d{2,}", "\u200d", text)   # deduplicate ZWJ

    # 3. Dialect-specific vocabulary
    if dialect and dialect in _ML_DIALECT_VOCAB:
        for pattern, replacement in _ML_DIALECT_VOCAB[dialect]:
            text = re.sub(pattern, replacement, text)

    return text


# ---------------------------------------------------------------------------
# Tamil normalizations
# ---------------------------------------------------------------------------

_TA_PRODUCT_VARIANTS: list[tuple[str, str]] = [
    # Saree (புடவை) variants
    _ub(r"\bபுடைவை\b", "புடவை"),
    _ub(r"\bபுட்டவை\b", "புடவை"),
    # Pattu (பட்டு) variants
    _ub(r"\bபட்டூ\b", "பட்டு"),
    # Churidar
    _ub(r"\bசுரிதார்\b", "சுரிதார்"),
    _ub(r"\bசூரிதார்\b", "சுரிதார்"),
    # Kurta
    _ub(r"\bகுர்தா\b", "குர்த்தா"),
]

_TA_DIALECT_VOCAB: dict[str, list[tuple[str, str]]] = {
    "chennai": [
        _ub(r"\bவேணு\b", "வேணும்"),
        _ub(r"\bஆகணு\b", "ஆகணும்"),
    ],
    "madurai": [],
    "coimbatore": [],
}


def _normalize_tamil(text: str, dialect: str | None) -> str:
    # 1. Product name standardization
    for pattern, replacement in _TA_PRODUCT_VARIANTS:
        text = re.sub(pattern, replacement, text)

    # 2. Dialect-specific vocabulary
    if dialect and dialect in _TA_DIALECT_VOCAB:
        for pattern, replacement in _TA_DIALECT_VOCAB[dialect]:
            text = re.sub(pattern, replacement, text)

    return text


# ---------------------------------------------------------------------------
# Telugu normalizations
# ---------------------------------------------------------------------------

_TE_PRODUCT_VARIANTS: list[tuple[str, str]] = [
    # Saree variants
    _ub(r"\bసారీ\b", "చీర"),         # "saari" → చీర (cheera, native Telugu word)
    # Pattu (silk) variants
    _ub(r"\bపట్టూ\b", "పట్టు"),
    # Churidar variants
    _ub(r"\bచూరీదారు\b", "చుడీదార్"),
    _ub(r"\bచురిదార్\b", "చుడీదార్"),
    # Langa Voni (half-saree, popular in Telugu regions)
    _ub(r"\bలంగావోణీ\b", "లంగావోణి"),
    _ub(r"\bలంగా వోణి\b", "లంగావోణి"),
]

_TE_DIALECT_VOCAB: dict[str, list[tuple[str, str]]] = {
    "telangana": [
        _ub(r"\bగావాల\b", "గావాలె"),
    ],
    "coastal_andhra": [],
    "rayalaseema": [],
    "hyderabad_urban": [],
}


def _normalize_telugu(text: str, dialect: str | None) -> str:
    # 1. Product name standardization
    for pattern, replacement in _TE_PRODUCT_VARIANTS:
        text = re.sub(pattern, replacement, text)

    # 2. Common Whisper issues in Telugu
    # Whisper sometimes adds English articles before Telugu words
    text = re.sub(r"\bthe\s+(?=[\u0C00-\u0C7F])", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\ba\s+(?=[\u0C00-\u0C7F])", "", text, flags=re.IGNORECASE)

    # 3. Dialect-specific vocabulary
    if dialect and dialect in _TE_DIALECT_VOCAB:
        for pattern, replacement in _TE_DIALECT_VOCAB[dialect]:
            text = re.sub(pattern, replacement, text)

    return text


# ---------------------------------------------------------------------------
# Kannada normalizations
# ---------------------------------------------------------------------------

_KN_PRODUCT_VARIANTS: list[tuple[str, str]] = [
    # Saree variants — Kannada uses ಸೀರೆ (seere)
    _ub(r"\bಸಾರಿ\b", "ಸೀರೆ"),
    _ub(r"\bಸಾರೀ\b", "ಸೀರೆ"),
    # Silk
    _ub(r"\bರೇಷ್ಮೇ\b", "ರೇಷ್ಮೆ"),
    _ub(r"\bಪಟ್ಟೂ\b", "ಪಟ್ಟು"),
    # Churidar
    _ub(r"\bಚೂರಿದಾರು\b", "ಚೂಡಿದಾರ"),
    _ub(r"\bಚುರಿದಾರ\b", "ಚೂಡಿದಾರ"),
    # Kurta
    _ub(r"\bಕುರ್ತಾ\b", "ಕುರ್ತೆ"),    # Kannada uses ಕುರ್ತೆ (kurte)
]

_KN_DIALECT_VOCAB: dict[str, list[tuple[str, str]]] = {
    "bangalore": [],
    "mysore": [],
    "north_karnataka": [],
    "coastal_karnataka": [],
}


def _normalize_kannada(text: str, dialect: str | None) -> str:
    # 1. Product name standardization
    for pattern, replacement in _KN_PRODUCT_VARIANTS:
        text = re.sub(pattern, replacement, text)

    # 2. Common Whisper issues in Kannada
    # Same English article injection as Telugu
    text = re.sub(r"\bthe\s+(?=[\u0C80-\u0CFF])", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\ba\s+(?=[\u0C80-\u0CFF])", "", text, flags=re.IGNORECASE)

    # 3. Dialect-specific vocabulary
    if dialect and dialect in _KN_DIALECT_VOCAB:
        for pattern, replacement in _KN_DIALECT_VOCAB[dialect]:
            text = re.sub(pattern, replacement, text)

    return text


# ---------------------------------------------------------------------------
# Generic (English / other) normalizations
# ---------------------------------------------------------------------------

_GENERIC_PRODUCT_VARIANTS: list[tuple[str, str]] = [
    # Transliterated Malayalam/Tamil product names from English text
    (r"\bkasav\b", "kasavu"),
    (r"\bkaasavu\b", "kasavu"),
    (r"\bkashav\b", "kasavu"),
    (r"\bkasaavu\b", "kasavu"),
    (r"\bmundu\b", "mundu"),      # already canonical
    (r"\bkurtha\b", "kurta"),
    (r"\bkurthaa\b", "kurta"),
    (r"\bchuridar\b", "churidar"),
    (r"\bchuridaar\b", "churidar"),
    # Telugu/Kannada transliterations
    (r"\bcheera\b", "cheera"),    # Telugu saree — canonical
    (r"\bseere\b", "seere"),      # Kannada saree — canonical
    (r"\bpattu\b", "pattu"),      # silk — canonical
]


def _normalize_generic(text: str) -> str:
    lower = text.lower()
    for pattern, replacement in _GENERIC_PRODUCT_VARIANTS:
        lower = re.sub(pattern, replacement, lower)
    return lower
