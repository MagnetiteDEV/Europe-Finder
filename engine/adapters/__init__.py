"""Adapter contract. Every source implements search(session, cfg) and
returns FoundPosting items in the shared shape — the same adapter
pattern Dossier uses in src/lib/job-search/adapter.ts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class FoundPosting:
    source: str          # e.g. "nature", "adzuna", "ats:workday"
    external_id: str     # stable id within the source
    title: str
    organization: str = ""
    country: str = ""    # ISO-2, "" when unknown
    city: str = ""
    url: str = ""
    description: str = ""  # plain text
    posted_date: str = ""  # ISO date or ""
    deadline: str = ""     # ISO date or ""
    # filled by the matcher:
    groups: list = field(default_factory=list)
    subfields: list = field(default_factory=list)
    fit_score: int = 0
    fit_band: str = ""
    fit_reasons: list = field(default_factory=list)
    red_flags: list = field(default_factory=list)
    excluded: bool = False
    # filled by the policy engine (funding / eligibility / priority):
    funding_category: str = "funding_information_unavailable"
    funding_fa: str = ""
    funding_notes: list = field(default_factory=list)
    eligibility: str = "insufficient_information"
    eligibility_note: str = ""
    priority_country: bool = False
    kind: str = "job"  # phd | job | other | master | scholarship
    # curated funding routes (masters / government scholarships):
    curated: bool = False
    coverage_fa: str = ""
    deadline_note: str = ""
    curated_eligibility: str = ""
    level: str = ""  # master | phd | both

    def key(self) -> str:
        return f"{self.source}::{self.external_id}"

    def to_dict(self) -> dict:
        return asdict(self)
