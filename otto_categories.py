"""Conservative mapping of OTTO categories and product titles to broad groups."""

from __future__ import annotations

import re

UNKNOWN_CATEGORY = "Unbekannt"
PRICE_BANDS = (
    ("<10 €", 0, 10),
    ("10–<25 €", 10, 25),
    ("25–<50 €", 25, 50),
    ("50–<100 €", 50, 100),
    ("100–<250 €", 100, 250),
    ("250–<500 €", 250, 500),
    ("500–<1.000 €", 500, 1_000),
    ("1.000–<2.500 €", 1_000, 2_500),
    ("2.500–<5.000 €", 2_500, 5_000),
    ("5.000–<10.000 €", 5_000, 10_000),
    ("≥10.000 €", 10_000, None),
)
PRICE_BAND_COUNT = len(PRICE_BANDS)

_CATEGORY_RULES = (
    (
        "Elektronik & Technik",
        re.compile(
            r"\b(smartphone|iphone|handy|laptop|notebook|macbook|tablet|computer|"
            r"fernseher|tv|kopfhörer|headset|kamera|powerbank|projektor|"
            r"staubsaugerroboter|gaming|lautsprecher|drucker|wetterstation|"
            r"powerstation|boombox|audio-system)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Haushalt & Küche",
        re.compile(
            r"\b(kaffeemaschine|kaffeemühle|küche|küchenmaschine|mixer|"
            r"fondue|popcorn\w*|pizzaofen|grill|kochtopf|messer|geschirr|"
            r"schneidebrett|thermoskanne|kühlschrank|backofen|kaffeevollautomat|"
            r"kücheninsel|küchenzeile|eiswürfelform|bierzapfanlage|zapfanlage)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Möbel & Wohnen",
        re.compile(
            r"\b(teppich|sofa|sessel|stuhl|tisch|bett|matratze|"
            r"spannbettlaken|vorhang|lampe|leuchte|regal|schrank|"
            r"kissen|decke|gardine|wohnzimmer|wanduhr|tischleuchte|"
            r"zimmerbrunnen|massagesessel|wärmekissen|bilderrahmen|hängesessel)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Mode & Accessoires",
        re.compile(
            r"\b(jeans|hemd|shirt|t-?shirt|jacke|mantel|hose|kleid|"
            r"schuhe|socken|gürtel|rucksack|tasche|schal|handschuhe)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Sport & Outdoor",
        re.compile(
            r"\b(trampolin|slackline|balance board|kletter|camping|"
            r"wandern|fahrrad|zelt|schlafsack|yogamatte|fitness|"
            r"fernglas|teleskop|metalldetektor|sprossenwand|faltrad|"
            r"klapprad|longboard|skateboard|fahrradbeleuchtung|fitnesstrampolin)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Garten",
        re.compile(
            r"\b(garten|gewächshaus|nistkasten|insektenhotel|"
            r"gartenbrunnen|solarlampe|pflanzenbox|kräutergarten|"
            r"teichfigur|kräuterspirale|foliengewächshaus)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Spielzeug & Hobby",
        re.compile(
            r"\b(bausatz|roboterarm|modellbau|spielzeug|plüsch\w*|"
            r"einhorn|dinosaurier|dino|kostüm|bastel|malkasten|"
            r"aquarell|3d drucker|arcade|kuckucksuhr|actionfigur|"
            r"spielfigur|experimentierkasten|konzertgitarre|wärmetier|stofftier)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Haustier",
        re.compile(
            r"\b(katzen|katze|hund|hunde|hundesofa|hundemäntelchen|"
            r"haustier|tierbedarf|katzenspielzeug)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Büro & Schreibwaren",
        re.compile(
            r"\b(bleistift|kugelschreiber|federtasche|schreibmaschine|"
            r"schreibwaren|bürostuhl|bürobedarf|notizbuch|radiergummi|"
            r"fineliner|schneidelineal|lineal)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Schmuck & Uhren",
        re.compile(
            r"\b(anhänger|goldkette|halskette|armband|ohrring|"
            r"uhr|globus|trinkhorn|whisky-steine)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Lebensmittel & Genuss",
        re.compile(
            r"\b(kaugummi|wurst|schokolade|kaffee|tee|bierbrau|"
            r"whisky|sushi|pommes|donut)\b",
            re.IGNORECASE,
        ),
    ),
)


def classify_category(
    title: str,
    source_category: str | None = None,
) -> tuple[str, str, str]:
    """Return the broad category, original category text, and assignment source."""
    raw = (source_category or "").strip()
    if raw:
        category = _match_category(raw)
        if category:
            return category, raw, "otto"
        category = _match_category(title)
        if category:
            return category, raw, "rule"
        return UNKNOWN_CATEGORY, raw, "otto"

    category = _match_category(title)
    if category:
        return category, "", "rule"
    return UNKNOWN_CATEGORY, "", "unknown"


def price_band(price: float | None, currency: str = "EUR") -> str | None:
    if price is None or price <= 0 or currency != "EUR":
        return None
    for label, lower, upper in PRICE_BANDS:
        if price >= lower and (upper is None or price < upper):
            return label
    return None


def _match_category(text: str) -> str | None:
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return category
    return None
