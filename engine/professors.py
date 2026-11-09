"""Professor discovery layer — ORCID + Crossref (both keyless public APIs).

Unlike postings, professors are *people*: the record is a researcher
whose recent works or profile match the candidate's fields. The
layer feeds a separate "اساتید" tab in the app, so a candidate can
find supervisors to contact — the same angle ApplyKite uses, but
built only from open scholarly APIs.

Scoring reuses the multilingual field vocabulary (FIELD_GROUPS) via
the matcher's word-boundary helpers. No engineering exclusion here:
a professor is not a posting, so only positive matching applies.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .match import contains_term, normalize_text
from .vocab import ANCHORS, FIELD_GROUPS

STRONG_MIN = 70
MODERATE_MIN = 45
# professors are discovery results (already keyword-filtered by the
# API query), so phrase hits count more than in posting scoring.
PHRASE_POINTS = 30.0
ANCHOR_POINTS = 10.0
ANCHOR_GROUP_CAP = 20.0
WORK_POINTS = 5.0
WORK_CAP = 25.0


@dataclass
class Professor:
    name: str
    orcid: str = ""            # ORCID iD or ""
    affiliation: str = ""      # primary institution
    country: str = ""          # ISO-2 or ""
    profile_url: str = ""      # ORCID profile or Crossref search link
    works: list = field(default_factory=list)   # [{title, year, doi}]
    sources: list = field(default_factory=list)  # ["orcid", "crossref"]
    # filled by score_professor:
    groups: list = field(default_factory=list)
    subfields: list = field(default_factory=list)
    fit_score: int = 0
    fit_band: str = ""

    def key(self) -> str:
        if self.orcid:
            return "orcid::" + self.orcid
        return "name::" + normalize_text(
            self.name + " " + self.affiliation).strip()

    def to_dict(self) -> dict:
        return asdict(self)


def score_professor(p: Professor) -> None:
    """Weighted vocab match over affiliation + work titles, using
    both multi-word phrase terms and single-word anchors."""
    text = normalize_text(
        (p.affiliation or "") + " " +
        " ".join(w.get("title", "") for w in p.works))
    total = 0.0
    groups: list[str] = []
    subs: list[str] = []
    for gid, (fa, weight, terms) in FIELD_GROUPS.items():
        hits = [t for t in terms if contains_term(text, t)]
        anchors = [t for t in ANCHORS.get(gid, [])
                   if contains_term(text, t)]
        if hits or anchors:
            groups.append(fa)
            subs.extend(hits[:4])
            subs.extend(anchors[:2])
            total += weight * PHRASE_POINTS * len(hits)
            total += min(len(anchors) * ANCHOR_POINTS,
                         ANCHOR_GROUP_CAP)
    # recent works count as evidence too
    total += min(len(p.works) * WORK_POINTS, WORK_CAP)
    p.groups = groups
    p.subfields = sorted(set(subs))[:8]
    p.fit_score = max(0, min(100, int(total)))
    p.fit_band = ("تناسب قوی" if p.fit_score >= STRONG_MIN else
                  "تناسب متوسط" if p.fit_score >= MODERATE_MIN else
                  "تناسب ضعیف")


def merge_professors(cands: list[Professor]) -> list[Professor]:
    """Dedupe by ORCID (or name+affiliation), merging works/sources."""
    best: dict[str, Professor] = {}
    for p in cands:
        k = p.key()
        if k not in best:
            best[k] = p
            continue
        old = best[k]
        if not old.orcid and p.orcid:
            old.orcid = p.orcid
        if not old.affiliation and p.affiliation:
            old.affiliation = p.affiliation
        if not old.profile_url and p.profile_url:
            old.profile_url = p.profile_url
        seen = {(w.get("doi") or w.get("title")) for w in old.works}
        for w in p.works:
            if (w.get("doi") or w.get("title")) not in seen:
                old.works.append(w)
                seen.add(w.get("doi") or w.get("title"))
        old.sources = sorted(set(old.sources) | set(p.sources))
    out = list(best.values())
    for p in out:
        p.works = sorted(p.works, key=lambda w: w.get("year") or "",
                         reverse=True)[:5]
        score_professor(p)
    return sorted(out, key=lambda p: (-p.fit_score, p.name))
