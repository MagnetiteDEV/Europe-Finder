"""Multilingual field vocabulary — ported from EuropeFinder's
src/lib/masters/fields.ts.

Positive terms are grouped by real subject fit (not generic word
overlap) and weighted. HARD_EXCLUSIONS apply only when the posting
itself is engineering-led. CONTEXT_TERMS decide whether generic
sustainability language counts.
"""
from __future__ import annotations

# group_id -> (persian label, weight, terms)
FIELD_GROUPS: dict[str, tuple[str, float, list[str]]] = {    "fashion_and_dress": ("فشن و لباس", 1.25, [
        "fashion studies", "fashion history", "fashion design", "dress studies",
        "dress history", "fashion culture", "fashion theory", "fashion communication",
        "mode", "histoire de la mode", "études de la mode", "design de mode",
        "mode durable", "kleidungsgeschichte", "modegeschichte", "modedesign",
        "modewissenschaft", "storia della moda", "studi sulla moda",
        "design della moda", "moda sostenibile", "modegeschiedenis",
        "modeonderzoek", "modestudier", "motestudier", "motehistorie",
        "motedesign", "moda", "historia de la moda", "diseño de moda",
        "moda sostenible", "história da moda", "design de moda",
    ]),
    "art_and_visual_culture": ("هنر و فرهنگ بصری", 1.15, [
        "art history", "visual culture", "contemporary art", "art theory",
        "curatorial studies", "curating", "history of art", "histoire de l'art",
        "arts visuels", "bildende kunst", "kunstgeschichte", "visuelle kultur",
        "storia dell'arte", "arti visive", "cultura visuale", "kunstgeschiedenis",
        "beeldcultuur", "kunsthistorie", "visuell kultur", "historia del arte",
        "cultura visual", "história da arte",
    ]),
    "design_and_artistic_research": ("دیزاین و پژوهش هنری", 1.2, [
        "design studies", "design research", "artistic research", "design history",
        "critical design", "interaction design", "service design", "craft studies",
        "design social", "recherche en design", "recherche artistique",
        "designforschung", "künstlerische forschung", "designgeschichte",
        "ricerca sul design", "ricerca artistica", "ontwerponderzoek",
        "artistiek onderzoek", "designforskning", "kunstnerisk forskning",
        "investigación en diseño", "investigación artística", "pesquisa em design",
        "pesquisa artística",
    ]),
    "costume_performance": ("کاستوم و اجرا", 1.15, [
        "costume studies", "costume design", "theatre design", "performance studies",
        "film costume", "scenography", "stage design", "costume history",
        "études de costume", "costume de théâtre", "kostümdesign",
        "theaterwissenschaft", "storia del costume", "costume per lo spettacolo",
        "scenografia", "kostuumontwerp", "kostuumgeschiedenis", "kostymdesign",
        "scenografi", "diseño de vestuario", "historia del traje", "figurino",
        "cenografia",
    ]),
    "humanities_and_material_culture": ("علوم انسانی و فرهنگ مادی", 1.0, [
        "material culture", "cultural studies", "heritage studies",
        "cultural heritage", "museum studies", "museum curation",
        "fashion anthropology", "visual anthropology", "social history",
        "memory studies", "culture matérielle", "études culturelles",
        "patrimoine culturel", "museologie", "materielle kultur",
        "kulturwissenschaft", "kulturerbe", "museumsstudien", "cultura materiale",
        "studi culturali", "patrimonio culturale", "studi museali",
        "materiële cultuur", "cultureel erfgoed", "kulturarv", "materiell kultur",
        "estudios culturales", "patrimonio cultural", "cultura material",
    ]),
    "sustainability_in_design": ("پایداری در طراحی", 1.0, [
        "sustainable fashion", "circular fashion", "circular design",
        "fashion sustainability", "life cycle assessment", "lca",
        "circular economy", "sustainable design", "textile heritage",
        "sustainable costume", "mode durable", "économie circulaire",
        "design durable", "nachhaltige mode", "kreislaufwirtschaft",
        "nachhaltiges design", "moda sostenibile", "economia circolare",
        "design sostenibile", "duurzame mode", "circulaire economie",
        "hållbart mode", "cirkulär ekonomi", "moda sostenible",
        "economía circular", "moda sustentável", "economia circular",
    ]),
}

HARD_EXCLUSIONS = [
    "textile engineering", "textile chemistry", "textile chemical engineering",
    "polymer engineering", "mechanical engineering", "chemical engineering",
    "industrial engineering", "manufacturing engineering", "robotics",
    "software engineering", "materials science", "material science",
    "fiber engineering", "fibre engineering", "technical textiles",
    "textiltechnik", "textilchemie", "maschinenbau", "verfahrenstechnik",
    "ingegneria tessile", "ingegneria meccanica", "ingegneria chimica",
    "ingenieria textil", "ingeniería química", "ingeniería mecánica",
    "génie textile", "génie mécanique",
]

CONTEXT_TERMS = [
    "fashion", "dress", "garment", "costume", "design", "art", "visual",
    "culture", "heritage", "craft", "museum", "textile history", "mode",
    "vêtement", "kunst", "kleidung", "moda", "abito", "ontwerp",
]

# Design jury: terms that mean the posting is about digital/tech design
# (UI/UX, web, software, games, industrial, graphic, interior...), not
# artistic / fashion / costume design. Mirrors HARD_EXCLUSIONS: a title
# hit vetoes outright; body hits need >=2 AND no fashion/art context,
# so a fashion posting that merely mentions "user experience" once
# (e.g. Design for Recycling) survives.
DESIGN_VETO = [
    "ux", "ui", "user interface", "user experience", "user centred design",
    "user-centered design", "human computer interaction",
    "human-computer interaction", "web designer", "web design",
    "software designer", "app designer", "mobile app", "game designer",
    "game design", "video game", "industrial design", "industrial designer",
    "product designer", "graphic designer", "graphic design",
    "interior designer", "interior design", "automotive design",
    "mechanical design", "usability", "figma", "wireframe", "wireframes",
    "user research", "ux research", "ui designer", "ux designer",
]

# Fashion/art context that saves a posting from the design veto.
# Deliberately specific: bare "design"/"art"/"visual"/"culture" are too
# broad ("state of the art", "visual" in tech copy).
FASHION_ART_CONTEXT = [
    "fashion", "dress", "garment", "costume", "couture", "textile",
    "art history", "history of art", "curatorial", "curator", "museum",
    "heritage", "craft", "visual culture", "contemporary art",
    "fashion design", "mode", "kunst", "moda", "vêtement",
    "costume design", "textile design", "artistic research",
    "design studies",
]

# generic sustainability language that only counts WITH context
GENERIC_SUSTAINABILITY = [
    "sustainability", "sustainable", "circular economy", "climate transition",
]

# Single-word anchors per group: high-signal words for short vacancy
# texts where full phrases rarely appear verbatim. Each distinct anchor
# hit adds a small fraction of group points (capped), so anchors alone
# can lift a posting to Moderate but never to Strong by themselves.
# Deliberately NOT included: "design", "art", "culture" (too generic).
ANCHORS: dict[str, list[str]] = {
    "fashion_and_dress": [
        "fashion", "textile", "textiles", "garment", "garments", "dress",
        "couture", "tailoring", "pattern cutting",
    ],
    "art_and_visual_culture": [
        "curatorial", "curator", "museology", "biennale", "arthistory",
        "history", "histoire", "geschichte", "historia",
    ],
    "design_and_artistic_research": [
        "designer", "craft", "crafts",
    ],
    "costume_performance": [
        "costume", "costumes", "theatre", "theater", "scenography",
        "dramaturgy", "opera", "choreography",
    ],
    "humanities_and_material_culture": [
        "museum", "museums", "archive", "archives", "heritage",
        "ethnography", "ethnographic",
    ],
    "sustainability_in_design": [
        "upcycling", "upcycle", "circular",
    ],
}
ANCHOR_POINT = 0.30
ANCHOR_TITLE_BONUS = 0.20
ANCHOR_GROUP_CAP = 1.20
