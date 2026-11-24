"""Multilingual field vocabulary — ported from EuropeFinder's
src/lib/masters/fields.ts and hardened in v2.9.3 for artistic precision.

Positive terms are grouped by real subject fit (not generic word
overlap) and weighted. HARD_EXCLUSIONS apply when the posting itself
is engineering/STEM-led. SUSTAINABILITY_GENERIC terms only count when
an explicit artistic/fashion/textile context is present (never bare
"design" in chemistry/food-modelling postings).
"""
from __future__ import annotations

FIELD_GROUPS: dict[str, tuple[str, float, list[str]]] = {
    "fashion_and_dress": ("فشن و لباس", 1.25, [
        "fashion studies", "fashion history", "fashion design", "dress studies",
        "dress history", "fashion culture", "fashion theory", "fashion communication",
        "fashion styling", "fashion photography", "fashion film",
        "fashion promotion", "fashion media", "digital fashion",
        "visual merchandising", "textile design", "designer textile",
        "garment design", "woven textiles", "knitted textiles",
        "surface design", "print design", "fashion curation",
        "histoire de la mode", "études de la mode", "design de mode",
        "mode durable", "kleidungsgeschichte", "modegeschichte", "modedesign",
        "modewissenschaft", "storia della moda", "studi sulla moda",
        "design della moda", "moda sostenibile", "modegeschiedenis",
        "modeonderzoek", "modestudier", "motestudier", "motehistorie",
        "motedesign", "moda", "historia de la moda", "diseño de moda",
        "história da moda", "design de moda",
    ]),
    "art_and_visual_culture": ("هنر و فرهنگ بصری", 1.15, [
        "art history", "visual culture", "contemporary art", "art theory",
        "curatorial studies", "curating", "history of art", "histoire de l'art",
        "arts visuels", "bildende kunst", "kunstgeschichte", "visuelle kultur",
        "storia dell'arte", "arti visive", "cultura visuale", "kunstgeschiedenis",
        "beeldcultuur", "kunsthistorie", "visuell kultur", "historia del arte",
        "cultura visual", "história da arte",
        "fine art", "fine arts", "visual arts", "visual art",
        "art practice", "studio art", "art education", "beaux-arts",
        # v2.9.3: artistic studio & institutional terms
        "illustration", "character animation", "printmaking",
        "art and design", "arts and humanities", "kunsthistorisches",
        "academy of art", "school of arts", "creative writing",
        "arts and culture", "school of communication and arts",
        "art conservation",
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
        "design education", "design teaching",
        # v2.9.3: artistic spatial/exhibition & practice-based design terms
        "exhibition design", "spatial design", "narrative environments",
        "speculative design", "practice-based research", "practice based research",
        "practice-led research", "artistic practice", "digital spaces",
        "school of design", "design lab", "postdoctoral design researcher",
    ]),
    "costume_performance": ("کاستوم و اجرا", 1.15, [
        "costume studies", "costume design", "theatre design", "performance studies",
        "film costume", "scenography", "stage design", "costume history",
        "performing arts", "performance art", "set design",
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
        "memory studies", "critical bibliography", "material objects",
        "archival studies", "special collections", "klassik stiftung weimar",
        "culture matérielle", "études culturelles",
        "patrimoine culturel", "museologie", "materielle kultur",
        "kulturwissenschaft", "kulturerbe", "museumsstudien", "cultura materiale",
        "studi culturali", "patrimonio culturale", "studi museali",
        "materiële cultuur", "cultureel erfgoed", "kulturarv", "materiell kultur",
        "estudios culturales", "patrimonio cultural", "cultura material",
    ]),
    "sustainability_in_design": ("پایداری در طراحی", 1.0, [
        "sustainable fashion", "circular fashion", "circular design",
        "fashion sustainability", "sustainable design", "textile heritage",
        "sustainable costume", "mode durable", "design durable",
        "nachhaltige mode", "nachhaltiges design", "moda sostenibile",
        "design sostenibile", "duurzame mode", "hållbart mode",
        "moda sustentável",
        # Generic sustainability terms: gated by SUSTAINABILITY_CONTEXT in match.py
        "life cycle assessment", "lca", "circular economy",
        "économie circulaire", "kreislaufwirtschaft",
        "economia circolare", "circulaire economie", "cirkulär ekonomi",
        "economía circular", "economia circular",
    ]),
    "fashion_management_supply_chain": ("مدیریت فشن و زنجیره تأمین", 1.1, [
        "sustainable supply chain", "sustainable supply chains",
        "fashion supply chain", "textile supply chain",
        "apparel supply chain", "garment supply chain",
        "circular supply chain", "fashion value chain",
        "textile value chain", "supply chain transparency",
        "supply chain sustainability", "responsible sourcing",
        "ethical sourcing", "sustainable sourcing", "fashion sourcing",
        "apparel sourcing",
        "fashion management", "fashion business", "fashion marketing",
        "fashion merchandising", "fashion buying",
        "fashion retail management", "luxury brand management",
        "luxury management", "fashion entrepreneurship",
        "fashion industry management", "apparel management",
        "textile management", "fashion operations",
        "management de la mode", "gestion de la mode", "modemanagement",
        "textilmanagement", "nachhaltige lieferkette",
        # generic phrases: gated by SUPPLY_CHAIN_CONTEXT in match.py
        "supply chain", "supply chains", "value chain", "value chains",
    ]),
}

SUPPLY_CHAIN_GENERIC = [
    "supply chain", "supply chains", "value chain", "value chains",
]

SUPPLY_CHAIN_CONTEXT = [
    "fashion", "textile", "textiles", "garment", "garments", "apparel",
    "couture", "circular", "circularity", "cotton", "leather",
    "footwear", "luxury", "upcycling", "upcycle", "denim",
    "moda", "kleidung", "vêtement", "dress",
]

# Generic sustainability terms that ONLY count in fashion/art/design context
# (prevents chemistry photocatalysts or food-process LCA from scoring Strong!)
SUSTAINABILITY_GATED = {
    "life cycle assessment", "lca", "circular economy",
    "économie circulaire", "kreislaufwirtschaft",
    "economia circolare", "circulaire economie", "cirkulär ekonomi",
    "economía circular", "economia circular",
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
    # v2.9.3: French engineering degrees + STEM hard-science exclusions
    "diplome d ingenieur", "ingenierie textile", "ecole d ingenieurs",
    "ecole nationale superieure d ingenieurs",
    "photocatalyst", "photocatalysts", "photocatalytic",
    "aeronautics", "food process modelling", "protein biochemistry",
    "enzymatic recycling of polyester plastics", "heated garments for patients",
    "protein nanocages", "dna amplification", "brushless doubly fed",
    "bayesian experimental design", "computational chemistry",
    "synthetic proteins", "plant gene expression", "semiconductor",
    "wireless communications", "electric composites", "spatial multi-omics",
    "spatial biology", "protein biofilm", "molecular genetics",
    "nanofiltration", "electrodialysis", "bioinformatics",
    "quantum materials", "nuclear physics", "solid state physics",
    "experimental physics", "fluid mechanics", "automatic control",
    "biophysics", "biotechnology", "neuroscience", "immunology",
    "virology", "parasitology", "zinc-ion batteries", "battery recycling",
    "laser ablation", "hormone sensing",
]

CONTEXT_TERMS = [
    "fashion", "dress", "garment", "costume", "art history", "history of art",
    "fine art", "visual culture", "material culture", "heritage", "craft",
    "museum", "textile history", "textile design", "school of design",
    "art and design", "artistic research", "curatorial", "curator",
    "vêtement", "kunst", "kleidung", "moda", "abito", "ontwerp",
]

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

FASHION_ART_CONTEXT = [
    "fashion", "dress", "garment", "costume", "couture", "textile",
    "art history", "history of art", "curatorial", "curator", "museum",
    "heritage", "craft", "visual culture", "contemporary art",
    "fashion design", "kunst", "moda", "vêtement",
    "costume design", "textile design", "artistic research",
    "design studies", "fine art", "illustration", "school of design",
    "art and design", "performing arts", "narrative environments",
]

# Strict artistic/fashion/textile context required for LCA / circular economy
SUSTAINABILITY_CONTEXT = FASHION_ART_CONTEXT + [
    "textiles", "apparel", "garments", "fashion design", "circular fashion",
    "sustainable fashion", "design school",
]

GENERIC_SUSTAINABILITY = [
    "sustainability", "sustainable", "circular economy", "climate transition",
    "lca", "life cycle assessment",
]

# Retail / legal / groundskeeping titles that must not score via generic anchors
RETAIL_LEGAL_TITLES = [
    "sales associate", "sales assistant", "seasonal sales", "senior sales",
    "distribution centre operative", "grounds operative", "counsel",
    "accountant", "impact officer", "sales team member",
]

ANCHORS: dict[str, list[str]] = {
    "fashion_and_dress": [
        "fashion", "textile", "textiles", "garment", "garments", "dress",
        "couture", "tailoring", "pattern cutting",
    ],
    "art_and_visual_culture": [
        "curatorial", "curator", "museology", "biennale", "arthistory",
        "history", "histoire", "geschichte", "historia", "animation",
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
