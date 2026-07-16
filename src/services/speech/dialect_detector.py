"""
Detect South Indian language dialects from transcribed text using
linguistic marker scoring.

Supported:
  Malayalam (ml): thrissur, malabar, palakkad, travancore, kochi
  Tamil     (ta): chennai, madurai, coimbatore
  Telugu    (te): telangana, coastal_andhra, rayalaseema, hyderabad_urban
  Kannada   (kn): bangalore, mysore, north_karnataka, coastal_karnataka

Design
------
Each dialect is described by a list of weighted marker strings.  The
detector scans the text for each marker, accumulates the matched weights,
then picks the highest-scoring dialect.  Raw score is mapped to a [0, 1]
confidence value via ``min(1.0, raw_score / 2.0)`` — meaning two
high-weight markers give full confidence.  Results below 0.3 are
discarded (return None).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class DialectInfo:
    name: str               # thrissur, malabar, palakkad, travancore, kochi,
    #                         chennai, madurai, coimbatore,
    #                         telangana, coastal_andhra, rayalaseema, hyderabad_urban,
    #                         bangalore, mysore, north_karnataka, coastal_karnataka
    region: str             # human-readable region label
    confidence: float       # 0–1
    markers_found: list[str]
    formality: str          # formal | informal | mixed


# ---------------------------------------------------------------------------
# Internal marker definition
# ---------------------------------------------------------------------------

class _Marker(NamedTuple):
    pattern: str            # literal substring or regex pattern string
    weight: float           # marker specificity weight
    is_regex: bool = False  # set True for regex patterns


@dataclass
class _DialectDef:
    name: str
    region: str
    formality: str
    markers: list[_Marker]


# ---------------------------------------------------------------------------
# Malayalam dialect definitions
# ---------------------------------------------------------------------------

_MALAYALAM_DIALECTS: list[_DialectDef] = [
    _DialectDef(
        name="thrissur",
        region="Central Kerala (Thrissur)",
        formality="informal",
        markers=[
            # Distinctive colloquial particles / question tags
            _Marker("എന്തിനാ", 1.0),       # enthina  — "why" (colloquial)
            _Marker("പോയിക്കോ", 1.0),      # poyikko  — "just go"
            _Marker("വരുന്നില്ലേ", 0.8),   # varunille — "aren't you coming"
            _Marker("ഇല്ലേടോ", 0.9),       # illedo   — tag question (masc)
            _Marker("ഇല്ലേടീ", 0.9),       # illedi   — tag question (fem)
            _Marker("ആടോ", 0.8),            # aado     — affirmative particle
            _Marker("ആടീ", 0.8),            # aadi     — affirmative particle (fem)
            _Marker("ആവോ", 0.7),            # aavo     — "maybe / I don't know"
            _Marker("കേക്കുന്നില്ലേ", 0.8),# kekkunnille — "can't you hear"
            _Marker("ങ്ഹാ", 0.7),           # ngha     — affirmative grunt
            # Thrissur-specific interjections
            _Marker("ഡോ", 0.5),             # do       — address particle
        ],
    ),
    _DialectDef(
        name="malabar",
        region="North Kerala (Malabar / Mappila)",
        formality="mixed",
        markers=[
            # Arabic / Urdu loanwords prevalent in Malabar Muslim speech
            _Marker("ബഹുത്", 1.5),          # bahuth       — "very" (Arabic: كثير)
            _Marker("ഇൻഷാഅല്ലാഹ്", 1.5),   # InshaAllah
            _Marker("അൽഹംദുലില്ലാഹ്", 1.5),# Alhamdulillah
            _Marker("ബരക്കത്ത്", 1.2),      # barakath     — "blessing"
            _Marker("ഖൈർ", 1.2),            # khair        — "good / it's fine"
            _Marker("മഷ്ടം", 1.0),          # mashdam      — affection/love
            _Marker("വാപ്പ", 1.0),          # vaappa       — "father"
            _Marker("ഉമ്മ", 1.0),           # umma         — "mother"
            _Marker("ഉസ്താദ്", 1.0),        # ustad        — "teacher/scholar"
            _Marker("അച്ഛാ", 0.8),          # achha        — "ok/alright" (Urdu)
            _Marker("ഹ്വോ", 0.8),           # hvo          — Malabar assent particle
        ],
    ),
    _DialectDef(
        name="palakkad",
        region="Eastern Kerala (Palakkad)",
        formality="informal",
        markers=[
            # Tamil words code-switched into Malayalam (Palakkad borders Tamil Nadu)
            _Marker("ஆமா", 1.5),            # aama  — "yes" (Tamil)
            _Marker("என்ன", 1.0),           # enna  — "what" (Tamil)
            _Marker("வாங்க", 1.0),          # vaanga — "come / buy" (Tamil)
            _Marker("சரி", 0.8),            # sari  — "ok" (Tamil)
            _Marker("பாரு", 0.9),           # paaru — "look/see" (Tamil)
            _Marker("நல்லா", 0.8),          # nalla — "good" (Tamil)
            _Marker("போ", 0.6),             # po    — "go" (Tamil, short)
            _Marker("வா", 0.5),             # va    — "come" (Tamil, short)
        ],
    ),
    _DialectDef(
        name="travancore",
        region="South Kerala (Travancore / Thiruvananthapuram)",
        formality="formal",
        markers=[
            # Literary / formal Malayalam forms
            _Marker("അങ്ങനെയാണ്", 1.5),    # anganeyan  — "that is so"
            _Marker("ആകുന്നു", 1.2),        # aakunnu    — formal present tense suffix
            _Marker("ആകട്ടെ", 1.0),         # aakadte    — "let it be / ok then"
            _Marker("ആണ്ടോ", 0.8),          # aando      — Travancore softening particle
            _Marker("ശരിയാണ്", 1.0),        # shariyaan  — "that's correct"
            _Marker("ചെയ്യുന്നു", 0.7),     # cheyyunnu  — formal verb form
            _Marker("ആകുമോ", 0.8),          # aakumo     — formal query
            _Marker("ആണോ", 0.6),            # aano       — formal question particle
        ],
    ),
    _DialectDef(
        name="kochi",
        region="Ernakulam / Urban Kochi",
        formality="informal",
        markers=[
            # Urban slang + heavy English code-switching
            _Marker("മച്ചാൻ", 1.5),         # machan     — "bro/dude" (from Tamil)
            _Marker("പൊളി", 1.2),           # poli       — "awesome/brilliant"
            _Marker("അടിപൊളി", 1.5),        # adipoli    — "fantastic"
            _Marker("ഫുൾ", 1.0),            # full       — "totally" (English)
            _Marker("ഇരിക്കുന്നോ", 0.8),    # irikkuno   — Kochi colloquial query
            _Marker("ദേ", 0.7),             # de         — "hey/look" (urban)
            _Marker("ടാ", 0.6),             # da         — address particle (urban)
            _Marker("ക്ലീൻ", 0.8),          # clean      — "clean/nice" (Kochi slang)
        ],
    ),
]


# ---------------------------------------------------------------------------
# Tamil dialect definitions
# ---------------------------------------------------------------------------

_TAMIL_DIALECTS: list[_DialectDef] = [
    _DialectDef(
        name="chennai",
        region="Chennai / North Tamil Nadu",
        formality="informal",
        markers=[
            _Marker("மச்சி", 1.5),           # machi      — "bro/friend"
            _Marker("டா", 1.2),              # da         — masculine address (informal)
            _Marker("டி", 1.0),              # di         — feminine address (informal)
            _Marker("என்னடா", 1.2),          # ennada     — "what man"
            _Marker("போடா", 1.0),            # poda       — "go man"
            _Marker("இருடா", 1.0),           # iruda      — "stay man / wait"
            _Marker("யாரு", 0.8),            # yaaru      — "who" (colloquial)
            _Marker("என்னது", 0.7),          # ennadu     — "what is it" (colloquial)
            _Marker("வேணும்", 0.7),          # venum      — "need/want" (Chennai form)
            _Marker("சூப்பர்", 0.9),         # super      — "great" (Chennai slang)
        ],
    ),
    _DialectDef(
        name="madurai",
        region="Madurai / South Tamil Nadu",
        formality="informal",
        markers=[
            _Marker("என்னாச்சு", 1.5),       # ennachchu  — "what happened"
            _Marker("பேசுற", 1.0),           # pesura     — "speaking" (dialectal -ura)
            _Marker("வாங்குற", 1.0),         # vaangura   — "buying" (dialectal -ura)
            _Marker("ஆத்தா", 1.2),           # aatha      — "mother" (South TN)
            _Marker("மாட்டோம்", 1.0),        # maatom     — "won't do it"
            _Marker("ஏய்", 0.6),             # ey         — address interjection
            _Marker("ஆமாப்பா", 1.2),         # aamaappa   — "yes indeed" (South TN)
            _Marker("பாத்துக்கோ", 1.0),      # paathukko  — "take care" (dialectal)
        ],
    ),
    _DialectDef(
        name="coimbatore",
        region="Coimbatore / Western Tamil Nadu",
        formality="mixed",
        markers=[
            # Western TN has Kannada/Malayalam influence and distinct politeness particles
            _Marker("ஏங்க", 1.5),            # enga       — polite plural address
            _Marker("ஆகும்ல", 1.2),          # aaguml     — "it will happen (right?)"
            _Marker("பண்றோம்", 1.0),         # panrom     — "we'll do it"
            _Marker("வாங்கிட்டு", 1.0),      # vaangittu  — "having bought" (CBE form)
            _Marker("சொல்லுங்க", 0.9),       # sollunnga  — "please tell" (polite)
            _Marker("பாருங்க", 0.9),         # paarunnga  — "please look" (polite)
            _Marker("ஆமாங்க", 1.2),          # aamaanga   — "yes (polite)"
        ],
    ),
]


# ---------------------------------------------------------------------------
# Telugu dialect definitions
# ---------------------------------------------------------------------------

_TELUGU_DIALECTS: list[_DialectDef] = [
    _DialectDef(
        name="telangana",
        region="Telangana (Warangal, Karimnagar, Nizamabad)",
        formality="informal",
        markers=[
            # Telangana-specific verb endings and particles
            _Marker("గావాలె", 1.5),          # gaavale    — "want/need" (Telangana form)
            _Marker("నువ్వేం", 1.2),          # nuvvem     — "what are you" (colloquial)
            _Marker("ఏందిరా", 1.2),          # endiraa    — "what is it man"
            _Marker("రారా", 1.0),            # raaraa     — "come come" (informal)
            _Marker("పోరా", 1.0),            # poraa      — "go man"
            _Marker("అయ్యిందా", 1.0),         # ayyindaa   — "is it done?" (Telangana past)
            _Marker("గిట్ల", 1.2),           # gitla      — "like this" (Telangana)
            _Marker("అట్ల", 1.0),            # atla       — "like that" (Telangana)
            _Marker("ఏందీ", 0.9),            # endii      — "what?" (Telangana form)
            _Marker("గని", 0.8),             # gani       — "but" (Telangana conjunction)
            _Marker("నడువు", 0.8),           # naduvu     — "walk/go" (colloquial imperative)
        ],
    ),
    _DialectDef(
        name="coastal_andhra",
        region="Coastal Andhra (Visakhapatnam, Vijayawada, Guntur)",
        formality="mixed",
        markers=[
            # Standard / coastal Andhra verb patterns
            _Marker("ఏమిటి", 1.0),           # emiti      — "what is it" (standard)
            _Marker("చెప్పండి", 1.0),         # cheppandi  — "please tell" (polite)
            _Marker("రండి", 0.9),            # randi      — "please come" (polite)
            _Marker("బాగుంది", 0.8),          # bagundi    — "it's good" (standard)
            _Marker("ఉంటుంది", 0.7),          # untundi    — "it will be there" (standard)
            _Marker("కదా", 0.8),             # kadaa      — "right?" (tag question)
            _Marker("అవునా", 0.7),           # avunaa     — "is that so?"
            _Marker("ఎంత", 0.6),             # enta       — "how much" (standard query)
            _Marker("చాలా", 0.6),            # chaalaa    — "very" (standard intensifier)
        ],
    ),
    _DialectDef(
        name="rayalaseema",
        region="Rayalaseema (Kurnool, Kadapa, Anantapur)",
        formality="informal",
        markers=[
            # Rayalaseema has distinct retroflex pronunciation and archaic forms
            _Marker("ఏంది", 1.2),            # endi       — "what" (Rayalaseema form)
            _Marker("రాయి", 1.0),            # raayi      — Rayalaseema particle
            _Marker("గింత", 1.2),            # ginta      — "this much" (Rayalaseema)
            _Marker("అంత", 0.7),             # anta       — "that much"
            _Marker("చెయ్యి", 0.9),           # cheyyi     — "do it" (Rayalaseema imperative)
            _Marker("పోతా", 0.8),            # potaa      — "I'll go" (dialectal future)
            _Marker("వస్తా", 0.8),            # vastaa     — "I'll come" (dialectal future)
            _Marker("లేదా", 0.7),            # ledaa      — "is it not?" (emphatic negation)
        ],
    ),
    _DialectDef(
        name="hyderabad_urban",
        region="Hyderabad Urban (Deccani-influenced)",
        formality="informal",
        markers=[
            # Deccani Urdu + Telugu fusion markers (Hyderabad city speech)
            _Marker("నక్కో", 1.5),           # nakko      — "don't" (Deccani: mat karo)
            _Marker("మేరేకో", 1.5),          # mereko     — "to me" (Deccani Hindi/Urdu)
            _Marker("కిద్దర్", 1.2),          # kiddar     — "where" (Deccani)
            _Marker("హౌ", 1.0),              # hau        — "yes" (Deccani affirmative)
            _Marker("బోల్తా", 1.0),          # boltaa     — "speaking" (Deccani)
            _Marker("హైదరాబాద్", 0.7),        # Hyderabad  — city name mention
            _Marker("బిర్యానీ", 0.5),         # biryani    — cultural marker
            _Marker("అచ్ఛా", 0.8),            # acchaa     — "okay" (Urdu)
            _Marker("కైకు", 1.2),            # kaiku      — "why" (Deccani)
        ],
    ),
]


# ---------------------------------------------------------------------------
# Kannada dialect definitions
# ---------------------------------------------------------------------------

_KANNADA_DIALECTS: list[_DialectDef] = [
    _DialectDef(
        name="bangalore",
        region="Bangalore / Bengaluru Urban",
        formality="informal",
        markers=[
            # Heavy English code-switching, urban slang
            _Marker("ಮಚ್ಚಿ", 1.5),           # machchi    — "bro" (from Tamil machi)
            _Marker("ಗುರು", 1.2),            # guru       — "dude/boss" (Bangalore slang)
            _Marker("ಹೋಗ್ಬೇಕು", 1.0),        # hogbeku    — "must go" (colloquial)
            _Marker("ಸೂಪರ್", 0.9),           # super      — "great" (English code-switch)
            _Marker("ಕೂಲ್", 0.8),            # cool       — English code-switch
            _Marker("ಬಿಡು", 0.8),            # bidu       — "leave it / forget it"
            _Marker("ಹೇಗಿದೆ", 0.7),          # hegide     — "how is it" (standard but frequent)
            _Marker("ಆಯ್ತಾ", 0.9),           # aytaa      — "is it done?" (Bangalore form)
            _Marker("ಹೌದಾ", 0.8),            # haudaa     — "is that so?" (urban)
        ],
    ),
    _DialectDef(
        name="mysore",
        region="Mysore / Old Mysore Region",
        formality="formal",
        markers=[
            # Classical Kannada forms, literary influence
            _Marker("ಹೌದು", 0.8),            # haudu      — "yes" (standard, more frequent in Mysore)
            _Marker("ಬನ್ನಿ", 1.0),           # banni      — "please come" (polite Mysore)
            _Marker("ಮಾಡಿ", 0.9),            # maadi      — "please do" (polite imperative)
            _Marker("ಇರಿ", 0.8),             # iri        — "please stay/wait" (polite)
            _Marker("ಅಲ್ವಾ", 1.2),           # alvaa      — "isn't it?" (Mysore tag question)
            _Marker("ಕಣ್ರೀ", 1.2),           # kanri      — "you see" (Mysore particle)
            _Marker("ಅಂತ", 0.7),             # anta       — "saying that" (quotative)
            _Marker("ಅಲ್ಲಿ", 0.5),           # alli       — "there" (more frequent in formal)
            _Marker("ಆಗಿದೆ", 0.6),           # aagide     — "has happened/become"
        ],
    ),
    _DialectDef(
        name="north_karnataka",
        region="North Karnataka (Dharwad, Hubballi, Belgaum)",
        formality="mixed",
        markers=[
            # Harder consonants, Marathi influence, archaic forms
            _Marker("ಏನ್ರಿ", 1.5),           # enri       — "what?" (North KA address)
            _Marker("ಬರ್ರಿ", 1.2),           # barri      — "come" (North KA imperative)
            _Marker("ಹೋಗ್ರಿ", 1.2),          # hogri      — "go" (North KA imperative)
            _Marker("ಹೇಳ್ರಿ", 1.0),          # helri      — "tell" (North KA imperative)
            _Marker("ಅದ್ಕೆ", 0.9),           # adke       — "for that" (contracted)
            _Marker("ಇಲ್ರಿ", 1.0),           # ilri       — "no" (polite North KA)
            _Marker("ಬಂದ್ರಿ", 1.0),          # bandri     — "came" (polite past)
            _Marker("ಮಾಡ್ರಿ", 1.0),          # maadri     — "please do" (North KA polite)
            _Marker("ಅಲ್ರಿ", 0.9),           # alri       — "isn't it?" (North KA tag)
        ],
    ),
    _DialectDef(
        name="coastal_karnataka",
        region="Coastal Karnataka (Mangalore, Udupi)",
        formality="mixed",
        markers=[
            # Tulu and Konkani influence, distinct vocabulary
            _Marker("ಉಂಡು", 1.2),            # undu       — "there is" (coastal form, Tulu influence)
            _Marker("ಇಜ್ಜಿ", 1.5),           # ijji       — "is not" (coastal negation, Tulu)
            _Marker("ಪೋಡಿ", 1.0),            # podi       — "girl" (coastal address, Tulu)
            _Marker("ಮಾರಾಯ", 1.2),           # maaraaya   — "man/dude" (coastal address)
            _Marker("ಎಂಚ", 1.2),             # encha      — "what" (coastal form)
            _Marker("ಯಾನ್", 1.0),            # yaan       — "I" (Tulu influence, vs ನಾನು)
            _Marker("ಎಂಚಿನ", 1.0),           # enchina    — "how" (coastal form)
            _Marker("ಬಲ್ಲೆ", 0.9),           # balle      — "I know" (coastal form)
        ],
    ),
]


_LANGUAGE_DIALECTS: dict[str, list[_DialectDef]] = {
    "ml": _MALAYALAM_DIALECTS,
    "ta": _TAMIL_DIALECTS,
    "te": _TELUGU_DIALECTS,
    "kn": _KANNADA_DIALECTS,
}

# How much raw weight equals "full" confidence (score = 1.0)
_FULL_CONFIDENCE_WEIGHT = 2.0
_MIN_CONFIDENCE = 0.3


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class DialectDetector:
    """
    Stateless dialect detector.  Thread-safe and safe to share across requests.
    """

    async def detect(self, text: str, language: str) -> DialectInfo | None:
        """
        Detect dialect from transcribed text.

        Args:
            text: Transcribed text (in native script or transliterated).
            language: ISO 639-1 language code (e.g. "ml", "ta", "te", "kn").

        Returns:
            DialectInfo if a dialect is detected with confidence >= 0.3,
            else None.
        """
        dialects = _LANGUAGE_DIALECTS.get(language)
        if not dialects:
            return None

        best_def: _DialectDef | None = None
        best_score = 0.0
        best_markers: list[str] = []

        for dialect_def in dialects:
            score, found = _score_dialect(text, dialect_def)
            if score > best_score:
                best_score = score
                best_def = dialect_def
                best_markers = found

        if best_def is None or best_score == 0.0:
            return None

        confidence = min(1.0, best_score / _FULL_CONFIDENCE_WEIGHT)
        if confidence < _MIN_CONFIDENCE:
            return None

        return DialectInfo(
            name=best_def.name,
            region=best_def.region,
            confidence=round(confidence, 4),
            markers_found=best_markers,
            formality=best_def.formality,
        )


# ---------------------------------------------------------------------------
# Scoring helper
# ---------------------------------------------------------------------------

def _score_dialect(text: str, dialect: _DialectDef) -> tuple[float, list[str]]:
    """Return (total_weight, matched_marker_patterns) for a dialect against text."""
    total = 0.0
    found: list[str] = []

    for marker in dialect.markers:
        matched = (
            bool(re.search(marker.pattern, text))
            if marker.is_regex
            else marker.pattern in text
        )
        if matched:
            found.append(marker.pattern)
            total += marker.weight

    return total, found
