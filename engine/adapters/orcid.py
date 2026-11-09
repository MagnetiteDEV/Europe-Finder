"""ORCID public API adapter (keyless).

Expanded search returns researchers with their institutions in one
call — no per-record fetch needed:
  GET https://pub.orcid.org/v3.0/expanded-search/?q=<kw>&rows=N
  Accept: application/json
"""
from __future__ import annotations

from ..http import SourceBlocked, polite_get
from ..professors import Professor

SEARCH_URL = "https://pub.orcid.org/v3.0/expanded-search/"
SOURCE = "orcid"


def search(session, cfg: dict) -> list[Professor]:
    out: list[Professor] = []
    rows = int(cfg.get("rows", 10))
    headers = {"Accept": "application/json"}
    for kw in cfg.get("keywords", []):
        try:
            r = polite_get(session, SEARCH_URL, headers=headers,
                           params={"q": kw, "rows": rows})
        except SourceBlocked:
            break
        data = r.json()
        for e in data.get("expanded-result") or []:
            orcid = (e.get("orcid-id") or "").strip()
            name = " ".join(x for x in [
                (e.get("given-names") or "").strip(),
                (e.get("family-names") or "").strip()] if x)
            if not name and not orcid:
                continue
            insts = [i for i in (e.get("institution-name") or []) if i]
            out.append(Professor(
                name=name,
                orcid=orcid,
                affiliation=insts[0] if insts else "",
                profile_url=f"https://orcid.org/{orcid}" if orcid else "",
                sources=[SOURCE],
            ))
    return out
