"""Curated funding routes (masters + government/regional scholarships).

These are NOT scraped: each entry is a verified official funding route
(URL checked live, see last_checked). They go through the same
subject matcher so bands stay comparable, but carry their verified
funding classification and a `curated` flag.
"""
from __future__ import annotations

import json
from pathlib import Path

from .adapters import FoundPosting
from .funding import FA_LABEL

ROOT = Path(__file__).resolve().parent.parent


def _load(kind: str) -> list[FoundPosting]:
    path = ROOT / "data" / ("masters.json" if kind == "master"
                            else "scholarships.json")
    entries = json.loads(path.read_text(encoding="utf-8"))
    out: list[FoundPosting] = []
    for e in entries:
        desc = " ".join([e.get("description_fa", ""), e.get("name_en", ""),
                         e.get("coverage_fa", "")])
        p = FoundPosting(
            source=f"curated:{kind}",
            external_id=e["id"],
            title=e["name_en"],
            organization=e.get("name_fa", ""),
            country=e.get("country", ""),
            city="",
            url=e.get("url", ""),
            description=desc,
            posted_date=e.get("last_checked", ""),
            deadline="",
        )
        p.kind = kind
        p.curated = True
        cat = e.get("funding_category", "funding_unconfirmed")
        p._funding_preset = (cat, FA_LABEL.get(cat, cat), [])
        p.coverage_fa = e.get("coverage_fa", "")
        p.deadline_note = e.get("deadline_fa", "")
        p.curated_eligibility = e.get("eligibility_fa", "")
        p.level = e.get("level", "")
        out.append(p)
    return out


def load_all() -> list[FoundPosting]:
    return _load("master") + _load("scholarship")
