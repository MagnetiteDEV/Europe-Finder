"""Subject matcher — ported from EuropeFinder's src/lib/masters/match.ts.

Word-boundary multilingual matching over weighted field groups, with
the two guardrails from the candidate's search constraints:
  1. engineering-led postings are excluded (title hit, or >=2 body
     hits without an arts/design/fashion context);
  2. generic sustainability language alone never scores above 25.
  3. the design jury: digital/tech design (UI/UX, web, software,
     games, industrial, graphic, interior...) is vetoed even when it
     matches the "interaction design" / "design research" phrases or
     the "designer" anchor — title hit vetoes outright, body hits
     need >=2 AND no fashion/art context.

Bands follow the profile doc: Strong / Moderate / Weak / Exclude.
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
)

STRONG_MIN = 70
MODERATE_MIN = 45


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
    """v2.8: remove jobs.ac.uk boilerplate and idioms before scoring, so
    neither "mode" nor "fashion" fires on them:
    - "Mode of study Full-time / Part-time" (vacancy-template boilerplate)
    - "in a ... fashion" (idiom, e.g. "in a highly symmetric fashion")
    Text is already normalized (lowercase, punctuation stripped, padded
    with spaces), so the patterns match on word boundaries."""
    text = text.replace(" mode of study ", " ")
    text = re.sub(r" in a (?:[a-z]+ ){1,3}fashion ", " ", text)
    return text


def score_posting(p) -> None:
    """Mutates the FoundPosting in place. Sets fit_score, fit_band
    (تناسب قوی/متوسط/ضعیف/حذف‌شده), fit_reasons, red_flags, groups
    (Persian labels), subfields (matched terms) and excluded."""
    title_n = _strip_false_friends(normalize_text(p.title))
    body_n = _strip_false_friends(normalize_text(p.description or ""))
    all_n = title_n + " " + body_n

    weighted = 0.0
    best_saturation = 0.0  # max over groups of points/2: how completely
    best_group = ""        # the posting covers its best-matching field
    title_hits: list[str] = []
    body_hits: list[str] = []
    matched_groups: list[str] = []
    matched_terms: list[str] = []

    for gid, (fa_label, weight, terms) in FIELD_GROUPS.items():
        uniq = list(dict.fromkeys(terms))
        hits = [t for t in uniq if contains_term(all_n, t)]
        # anchor layer: single high-signal words for short vacancy texts
        anchor_hits = [a for a in ANCHORS.get(gid, [])
                       if contains_term(all_n, a)]
        anchor_title = [a for a in anchor_hits if contains_term(title_n, a)]
        anchor_points = min(ANCHOR_GROUP_CAP,
                            len(anchor_hits) * ANCHOR_POINT
                            + len(anchor_title) * ANCHOR_TITLE_BONUS)
        if not hits and not anchor_hits:
            continue
        title_hit = any(contains_term(title_n, t) for t in hits)
        if hits:
            points = min(2.0, 0.75 + len(hits) * 0.35
                         + (0.65 if title_hit else 0.0) + anchor_points)
        else:
            # anchors alone: capped contribution — can reach Moderate,
            # never Strong, by themselves
            points = anchor_points
        saturation = points / 2.0
        if saturation > best_saturation:
            best_saturation = saturation
            best_group = fa_label
        weighted += points * weight  # tie-breaker for ranking
        matched_groups.append(fa_label)
        matched_terms.extend(hits[:3] + anchor_hits[:2])
        shown = hits[:3] + [a for a in anchor_hits if a not in hits][:2]
        entry = f"{fa_label}: {', '.join(shown[:4])}"
        (title_hits if (title_hit or anchor_title) else body_hits).append(entry)

    title_excl = [t for t in HARD_EXCLUSIONS if contains_term(title_n, t)]
    body_excl = [t for t in HARD_EXCLUSIONS if contains_term(body_n, t)]
    excl_terms = list(dict.fromkeys(title_excl + body_excl))
    contextual = any(contains_term(all_n, t) for t in CONTEXT_TERMS)
    engineering_led = bool(title_excl) or (len(body_excl) >= 2 and not contextual)

    generic_sust = (any(contains_term(all_n, t) for t in GENERIC_SUSTAINABILITY)
                    and not contextual)

    # Design jury: a posting about digital/tech design (UI/UX, web,
    # software, games, industrial, graphic, interior...) is not artistic
    # / fashion design, even when it matches the "interaction design" /
    # "design research" phrases or the "designer" anchor. Title hit
    # vetoes outright; body hits need >=2 AND no fashion/art context.
    design_title = [t for t in DESIGN_VETO if contains_term(title_n, t)]
    design_body = [t for t in DESIGN_VETO if contains_term(body_n, t)]
    design_terms = list(dict.fromkeys(design_title + design_body))
    fashion_art = any(contains_term(all_n, t) for t in FASHION_ART_CONTEXT)
    design_led = bool(design_title) or (len(design_body) >= 2 and not fashion_art)

    score = round(best_saturation * 100)
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
        reasons.append("حذف مهندسی‌محور: " + ", ".join(excl_terms[:3]))
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
