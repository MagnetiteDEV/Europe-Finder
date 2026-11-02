"""Nature Careers RSS adapter (keyless, public feed).

Feed: https://www.nature.com/naturecareers/jobsrss/?q=<keyword>
One query per keyword from config. Location arrives as trailing
"City, Region (CC)" inside <description>.
"""
from __future__ import annotations

import re

import feedparser

from .. import extract as _extract
from ..http import SourceBlocked, polite_get
from . import FoundPosting

FEED_URL = "https://www.nature.com/naturecareers/jobsrss/"
SOURCE = "nature"

_ID_RE = re.compile(r"/job/(\d+)/")
_LOC_RE = re.compile(r"([A-Za-z][A-Za-z .'-]*?)\s*\(([A-Z]{2})\)\s*$")


def _parse_item(e) -> FoundPosting | None:
    link = (e.get("link") or "").split("?")[0]
    m = _ID_RE.search(link or e.get("id", ""))
    if not m:
        return None
    desc = e.get("description", "") or e.get("summary", "")
    country, city = "", ""
    lm = _LOC_RE.search(desc.strip())
    if lm:
        city = lm.group(1).strip().rstrip(",")
        country = _extract._valid_cc(lm.group(2))
    posted = ""
    if e.get("published_parsed"):
        t = e.published_parsed
        posted = f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
    return FoundPosting(
        source=SOURCE,
        external_id=m.group(1),
        title=(e.get("title") or "").strip(),
        organization="",
        country=country,
        city=city,
        url=link,
        description=desc.strip(),
        posted_date=posted,
    )


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    for kw in cfg.get("keywords", []):
        try:
            r = polite_get(session, FEED_URL, params={"q": kw})
        except SourceBlocked:
            break
        feed = feedparser.parse(r.content)
        for e in feed.entries:
            p = _parse_item(e)
            if p and p.key() not in seen:
                seen.add(p.key())
                out.append(p)
    return out
