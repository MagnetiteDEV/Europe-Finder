"""Adzuna API adapter (free tier: ~250 calls/day after signup).

Signup: https://developer.adzuna.com/signup — put app_id/app_key in
config.json. Disabled until both are set. Adzuna is a generalist
board, so it is a breadth layer; the academic sources carry the
precision for this user's fields.
"""
from __future__ import annotations

from ..http import SourceBlocked, polite_get
from . import FoundPosting

SOURCE = "adzuna"
_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


def search(session, cfg: dict) -> list[FoundPosting]:
    app_id = cfg.get("app_id", "")
    app_key = cfg.get("app_key", "")
    if not app_id or not app_key:
        return []
    out: list[FoundPosting] = []
    for country in cfg.get("countries", ["gb"]):
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": cfg.get("what", "phd"),
            "results_per_page": 50,
            "content-type": "application/json",
        }
        try:
            r = polite_get(session, _API.format(country=country), params=params)
        except SourceBlocked:
            break
        data = r.json()
        for j in data.get("results", []):
            loc = j.get("location", {}) or {}
            out.append(
                FoundPosting(
                    source=SOURCE,
                    external_id=str(j.get("id", "")),
                    title=j.get("title", ""),
                    organization=(j.get("company", {}) or {}).get("display_name", ""),
                    country=country.upper(),
                    city=", ".join(loc.get("area", [])[1:]) if loc.get("area") else "",
                    url=j.get("redirect_url", ""),
                    description=j.get("description", ""),
                    posted_date=(j.get("created", "") or "")[:10],
                )
            )
    return out
