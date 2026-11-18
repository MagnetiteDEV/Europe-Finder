"""FashionUnited UK adapter (fashion industry jobs, JSON-LD).

Source: https://fashionunited.uk/fashion-jobs
- robots.txt: empty Disallow (+ Allow /graphql/), so a polite read
  of the public listing is allowed.
- The listing page carries a CollectionPage LD+JSON block with the
  25 newest jobs (url + name; numberOfItems ~1000). ?page=N is
  ignored by the site (byte-identical results), so only page 1 is
  fetched; deeper history would need the undocumented GraphQL API
  (phase 2, schema unverified).
- Each detail page carries a JobPosting LD+JSON block (title,
  description, datePosted, validThrough, hiringOrganization,
  jobLocation). The script tag carries extra attributes
  (<script data-rr-meta="" type="application/ld+json">), so the
  block regex must not assume an exact tag shape.
- ~60% of page 1 is retail/sales; the engine matcher filters.
"""
from __future__ import annotations

import json
import re
import time

from requests.exceptions import ConnectionError, Timeout

from ..extract import extract_country
from ..http import SourceBlocked, polite_get
from . import FoundPosting
from .ats import strip_html

BASE = "https://fashionunited.uk"
LIST_URL = BASE + "/fashion-jobs"
SOURCE = "fashionunited"

_LD_RE = re.compile(
    r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_ID_RE = re.compile(r"-(\d+)$")
_COUNTRY = {
    "United Kingdom": "GB", "UK": "GB", "England": "GB",
    "Scotland": "GB", "Wales": "GB", "Ireland": "IE",
    "Denmark": "DK", "Norway": "NO", "Netherlands": "NL",
    "France": "FR", "Germany": "DE", "Italy": "IT", "Spain": "ES",
    "Belgium": "BE", "Sweden": "SE", "Portugal": "PT",
    "Switzerland": "CH", "Austria": "AT", "Poland": "PL",
}


def _ld_blocks(html_text: str) -> list[dict]:
    blocks = []
    for m in _LD_RE.finditer(html_text):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(d, dict):
            blocks.append(d)
    return blocks


def _from_detail(url: str, ext_id: str, d: dict) -> FoundPosting | None:
    title = (d.get("title") or "").strip()
    if not title:
        return None
    addr = ((d.get("jobLocation") or {}).get("address") or {})
    if isinstance(d.get("jobLocation"), list) and d["jobLocation"]:
        addr = (d["jobLocation"][0] or {}).get("address") or {}
    city = (addr.get("addressLocality") or "").strip()
    country = _COUNTRY.get((addr.get("addressCountry") or "").strip(), "")
    hiring = d.get("hiringOrganization") or {}
    org = hiring.get("name", "") if isinstance(hiring, dict) else ""
    desc = strip_html(d.get("description") or "")
    if not country:
        country = extract_country(f"{city} {desc}", "")
    return FoundPosting(
        source=SOURCE,
        external_id=ext_id,
        title=" ".join(title.split()),
        organization=" ".join(str(org).split()),
        country=country,
        city=" ".join(city.split()),
        url=url,
        description=desc,
        posted_date=(d.get("datePosted") or "")[:10],
        deadline=(d.get("validThrough") or "")[:10],
    )


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    delay = float(cfg.get("delay_seconds", 1.5))
    cap = int(cfg.get("max_details", 25))
    try:
        r = polite_get(session, LIST_URL)
    except SourceBlocked:
        return out
    items = []
    for block in _ld_blocks(r.text):
        if block.get("@type") != "CollectionPage":
            continue
        me = block.get("mainEntity") or {}
        items = me.get("itemListElement") or []
        break
    seen: set[str] = set()
    details = 0
    for it in items:
        url = (it.get("url") or "").strip()
        m = _ID_RE.search(url.split("?")[0].rstrip("/"))
        if not url or not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        if details >= cap:
            break
        try:
            time.sleep(delay)
            dr = polite_get(session, url)
        except SourceBlocked:
            break
        except (Timeout, ConnectionError):
            continue
        details += 1
        for block in _ld_blocks(dr.text):
            if block.get("@type") == "JobPosting":
                post = _from_detail(url, m.group(1), block)
                if post:
                    out.append(post)
                break
    return out
