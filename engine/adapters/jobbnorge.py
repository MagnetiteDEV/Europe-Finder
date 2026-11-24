"""Jobbnorge adapter (Norway — salaried PhD Research Fellowships).

Covers Norwegian universities and art academies (KHiO Oslo, KMD Bergen,
AHO, NTNU, UiO, UiB). All Norwegian PhD Research Fellow (Stipendiat)
positions are 3-4 year salaried public-sector employment contracts.
"""
from __future__ import annotations

import json
import re
import time
from html import unescape
from urllib.parse import urljoin

from requests.exceptions import ConnectionError, Timeout

from ..extract import clean_plain_text, extract_deadline
from ..http import SourceBlocked, polite_get
from . import FoundPosting
from .ats import strip_html

BASE = "https://www.jobbnorge.no"
SEARCH_URL = BASE + "/en/available-jobs"
SOURCE = "jobbnorge"

_JOB_LINK_RE = re.compile(
    r'<a[^>]+href=["\'](/en/available-jobs/job/(\d+)/[^"\']*)["\'][^>]*>(.*?)</a>',
    re.S | re.I)
_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)
_PHD_RE = re.compile(r"\b(ph\.?\s*d\.?|doctoral|stipendiat|research\s+fellow)\b", re.I)

DEFAULT_KEYWORDS = [
    "PhD art", "PhD design", "PhD fashion", "PhD museum",
    "PhD heritage", "PhD visual", "PhD costume", "artistic research",
]


def _parse_listing(html_text: str) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    for m in _LD_RE.finditer(html_text):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        blocks = d if isinstance(d, list) else [d]
        for b in blocks:
            if not isinstance(b, dict) or b.get("@type") != "JobPosting":
                continue
            title = clean_plain_text(b.get("title") or "")
            url = str(b.get("url") or "")
            idm = re.search(r"/job/(\d+)/", url)
            jid = idm.group(1) if idm else str(b.get("identifier") or "")
            if not jid or not title or jid in seen:
                continue
            seen.add(jid)
            hiring = b.get("hiringOrganization") or {}
            org = hiring.get("name", "") if isinstance(hiring, dict) else ""
            desc = strip_html(b.get("description") or "")
            p = FoundPosting(
                source=SOURCE,
                external_id=jid,
                title=title,
                organization=clean_plain_text(org),
                country="NO",
                url=urljoin(BASE, url) if url.startswith("/") else url,
                description=desc,
                posted_date=str(b.get("datePosted") or "")[:10],
                deadline=str(b.get("validThrough") or "")[:10] or extract_deadline(desc),
            )
            if _PHD_RE.search(title):
                p.kind = "phd"
                p._kind_fixed = True
            out.append(p)
    if out:
        return out
    for m in _JOB_LINK_RE.finditer(html_text):
        href, jid, raw_title = m.group(1), m.group(2), m.group(3)
        if jid in seen:
            continue
        title = clean_plain_text(strip_html(unescape(raw_title)))
        if len(title) < 6 or not _PHD_RE.search(title):
            continue
        seen.add(jid)
        p = FoundPosting(
            source=SOURCE,
            external_id=jid,
            title=title,
            organization="Norwegian Institution (Jobbnorge)",
            country="NO",
            url=urljoin(BASE, href),
            description=f"{title}. Salaried PhD Research Fellowship in Norway (Jobbnorge).",
        )
        p.kind = "phd"
        p._kind_fixed = True
        out.append(p)
    return out


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    delay = float(cfg.get("delay_seconds", 1.5))
    for kw in cfg.get("keywords", DEFAULT_KEYWORDS):
        try:
            r = polite_get(session, SEARCH_URL, params={"q": kw}, timeout=20)
        except SourceBlocked:
            break
        except (Timeout, ConnectionError):
            time.sleep(delay)
            continue
        except Exception:
            time.sleep(delay)
            continue
        for p in _parse_listing(r.text):
            if p.key() not in seen:
                seen.add(p.key())
                out.append(p)
        time.sleep(delay)
    return out
