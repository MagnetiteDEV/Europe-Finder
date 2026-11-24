"""Subject matcher — word-boundary multilingual matching with artistic lens.

Guardrails enforced:
  1. Engineering/STEM-led postings are excluded (title hit, or >=2 body
     hits without an explicit arts/fashion context, or full-stack dev role
     stating fashion/textile experience is not essential).
  2. Generic sustainability language (LCA, circular economy, circular)
     ONLY counts with fashion/art/textile context; without context it
     never scores above 25 (and never lifts chemistry/food postings).
  3. Design jury: digital/tech design (UI/UX, web, software, games,
     industrial, graphic, interior...) is vetoed unless saved by
     explicit fashion/art context.
  4. False-friends stripped: "mode of study", "in a ... fashion",
     "no prior knowledge of textiles", "tailoring messages/services/...",
     "craft practices" (groundskeeping), and retail/legal titles.
  5. Art & design school rescue: core Design faculty/PhD/research roles
     at art/design schools (Cumulus, School of Design, Faculty of Art and
     Design) are not dropped to score 0 when title carries "design".
"""
from __future__ import annotations

import re
import unicodedata

from .vocab import (
    ANCHOR_GROUP_CAP,
    ANCHOR_POINT,
    ANCHOR_TITLE_BONUS,
    ANCHORS,
    CONTEXT_TERMS,
    DESIGN_VETO,
    FASHION_ART_CONTEXT,
    FIELD_GROUPS,
    GENERIC_SUSTAINABILITY,
    HARD_EXCLUSIONS,
    RETAIL_LEGAL_TITLES,
    SUPPLY_CHAIN_CONTEXT,
    SUPPLY_CHAIN_GENERIC,
    SUSTAINABILITY_CONTEXT,
    SUSTAINABILITY_GATED,
)

STRONG_MIN = 70
MODERATE_MIN = 45

_DESIGN_SCHOOL_RE = re.compile(
    r"\b(school of design|faculty of art and design|art and design|"
    r"college of art|academy of art and design|school of arts design|"
    r"school of communication and creative arts)\b"
)
_CORE_DESIGN_ROLE_RE = re.compile(
    r"\b(associate professor|professor|senior lecturer|lecturer|"
    r"postdoctoral design|design projects lead|phd|doctoral|researcher)\b"
)


def normalize_text(value: str) -> str:
    s = unicodedata.normalize("NFD", value or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)
    return f" {s.strip()} "


def contains_term(text: str, term: str) -> bool:
    needle = normalize_text(term).strip()
    if not needle:
        return False
    return f" {needle} " in text


def _strip_false_friends(text: str) -> str:
    """Remove boilerplate, idioms and negative mentions before scoring."""
    text = text.replace(" mode of study ", " ")
    text = re.sub(r" in a (?:[a-z]+ ){1,3}fashion ", " ", text)
    text = re.sub(r" no prior knowledge of textiles? ", " ", text)
    text = re.sub(
        r" tailoring (?:messages|services|support|training|approach|content|"
        r"communications|solutions|programmes|programs|policies) ",
        " ", text)
    text = text.replace(" craft practices ", " ")
    text = text.replace(" state of the art ", " ")
    text = text.replace(" prior art ", " ")
    return text


def _is_fullstack_non_art(body_n: str) -> bool:
    return (
        (" typescript " in body_n or " postgresql " in body_n)
        and " experience in fashion textiles " in body_n
        and " not essential " in body_n
    )


def score_posting(p) -> None:
    """Mutates FoundPosting in place."""
    title_n = _strip_false_friends(normalize_text(p.title))
    org_n = normalize_text(getattr(p, "organization", "") or "")
    body_n = _strip_false_friends(normalize_text(p.description or ""))
    all_n = title_n + " " + org_n + " " + body_n

    is_retail_legal = any(contains_term(title_n, rt) for rt in RETAIL_LEGAL_TITLES)
    sust_contextual = any(contains_term(all_n, t) for t in SUSTAINABILITY_CONTEXT)

    weighted = 0.0
    best_saturation = 0.0
    title_hits: list[str] = []
    body_hits: list[str] = []
    matched_groups: list[str] = []
    matched_terms: list[str] = []

    for gid, (fa_label, weight, terms) in FIELD_GROUPS.items():
        uniq = list(dict.fromkeys(terms))
        hits = [t for t in uniq if contains_term(all_n, t)]
        if gid == "fashion_management_supply_chain":
            sc_context = any(contains_term(all_n, c)
                             for c in SUPPLY_CHAIN_CONTEXT)
            if not sc_context or is_retail_legal:
                hits = [t for t in hits if t not in SUPPLY_CHAIN_GENERIC]
        if gid == "sustainability_in_design" and not sust_contextual:
            hits = [t for t in hits if t not in SUSTAINABILITY_GATED]

        anchor_hits = [a for a in ANCHORS.get(gid, [])
                       if contains_term(all_n, a)]
        if gid == "sustainability_in_design" and not sust_contextual:
            anchor_hits = [a for a in anchor_hits if a != "circular"]
        if is_retail_legal:
            anchor_hits = [
                a for a in anchor_hits
                if a not in ("craft", "crafts", "archive", "heritage", "tailoring")
            ]

        anchor_title = [a for a in anchor_hits if contains_term(title_n, a)]
        anchor_points = min(
            ANCHOR_GROUP_CAP,
            len(anchor_hits) * ANCHOR_POINT
            + len(anchor_title) * ANCHOR_TITLE_BONUS,
        )
        if not hits and not anchor_hits:
            continue
        title_hit = any(contains_term(title_n, t) for t in hits)
        if hits:
            points = min(2.0, 0.75 + len(hits) * 0.35
                         + (0.65 if title_hit else 0.0) + anchor_points)
        else:
            points = anchor_points
        saturation = points / 2.0
        if saturation > best_saturation:
            best_saturation = saturation
        weighted += points * weight
        matched_groups.append(fa_label)
        matched_terms.extend(hits[:3] + anchor_hits[:2])
        shown = hits[:3] + [a for a in anchor_hits if a not in hits][:2]
        entry = f"{fa_label}: {', '.join(shown[:4])}"
        (title_hits if (title_hit or anchor_title) else body_hits).append(entry)

    # Art & Design school boost for core Design titles (e.g. "Associate Professor in Design"
    # at a School of Design / Cumulus member) where body text is short.
    if best_saturation < 0.70 and not is_retail_legal:
        is_art_school = (
            getattr(p, "source", "") == "cumulus"
            or bool(_DESIGN_SCHOOL_RE.search(all_n))
        )
        if is_art_school and contains_term(title_n, "design") and " lms " not in all_n:
            is_core = bool(_CORE_DESIGN_ROLE_RE.search(title_n))
            is_tech = any(contains_term(title_n, x) for x in (
                "digital design", "emerging technologies", "computation", "interactive"
            ))
            boost = 0.55 if is_tech else (0.70 if is_core else 0.55)
            if boost > best_saturation:
                best_saturation = boost
                if "دیزاین و پژوهش هنری" not in matched_groups:
                    matched_groups.append("دیزاین و پژوهش هنری")
                if "design" not in matched_terms:
                    matched_terms.append("design")
                title_hits.append("دیزاین و پژوهش هنری: design (دانشکده هنر و دیزاین)")

    title_excl = [t for t in HARD_EXCLUSIONS if contains_term(title_n, t)]
    body_excl = [t for t in HARD_EXCLUSIONS if contains_term(body_n, t)]
    excl_terms = list(dict.fromkeys(title_excl + body_excl))
    contextual = any(contains_term(all_n, t) for t in CONTEXT_TERMS)
    engineering_led = (
        bool(title_excl)
        or (len(body_excl) >= 2 and not contextual)
        or _is_fullstack_non_art(body_n)
    )

    generic_sust = (
        any(contains_term(all_n, t) for t in GENERIC_SUSTAINABILITY)
        and not sust_contextual
    )

    design_title = [t for t in DESIGN_VETO if contains_term(title_n, t)]
    design_body = [t for t in DESIGN_VETO if contains_term(body_n, t)]
    design_terms = list(dict.fromkeys(design_title + design_body))
    fashion_art = any(contains_term(all_n, t) for t in FASHION_ART_CONTEXT)
    design_led = bool(design_title) or (len(design_body) >= 2 and not fashion_art)

    score = round(best_saturation * 100)
    if is_retail_legal and not any(contains_term(title_n, w) for w in (
            "fashion", "visual merchandising", "costume", "curator", "art")):
        score = min(score, 15)
    if generic_sust:
        score = min(score, 25)
    if engineering_led:
        score = min(score, 15)
    if design_led:
        score = min(score, 15)

    p.excluded = engineering_led or design_led
    p.fit_score = int(score)
    if engineering_led or design_led:
        p.fit_band = "حذف‌شده"
    elif score >= STRONG_MIN:
        p.fit_band = "تناسب قوی"
    elif score >= MODERATE_MIN:
        p.fit_band = "تناسب متوسط"
    else:
        p.fit_band = "تناسب ضعیف"

    reasons: list[str] = []
    if engineering_led:
        reasons.append("حذف مهندسی‌محور: " + (", ".join(excl_terms[:3]) or "نقش فنی/نرم‌افزاری"))
    if design_led:
        reasons.append("حذف دیزاین دیجیتال/فناورانه: " + ", ".join(design_terms[:3]))
    reasons.extend((title_hits + body_hits)[:5])
    if not reasons:
        reasons.append("تطابق قوی با واژگان فشن، هنر، دیزاین یا علوم انسانی پیدا نشد.")
    p.fit_reasons = reasons
    p.groups = matched_groups
    seen: set[str] = set()
    p.subfields = [t for t in matched_terms
                   if not (t in seen or seen.add(t))][:12]
    if not getattr(p, "red_flags", None):
        p.red_flags = []
