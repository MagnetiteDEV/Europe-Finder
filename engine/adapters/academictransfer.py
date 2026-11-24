"""AcademicTransfer adapter (Netherlands — all Dutch research universities).

All PhD positions in the Netherlands (function_types=1) are 4-year salaried
employment contracts under the Dutch university collective labour agreement (CAO NU).

Tries the public JSON endpoint first, with a graceful HTML listing fallback
(parses /en/jobs/<id>/... links and JSON-LD blocks). Strictly polite:
honours delay_seconds and stops immediately on 429/403 (SourceBlocked).
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

BASE = "https://www.academictransfer.com"
API_URL = BASE + "/api/v1/vacancies/"
HTML_URL = BASE + "/en/jobs/"
SOURCE = "academictransfer"

_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)
_JOB_LINK_RE = re.compile(
    r'<a[^>]+href=["\'](/en/jobs/(\d+)/[^"\']*)["\'][^>]*>(.*?)</a>',
    re.S | re.I)

DEFAULT_KEYWORDS = [
    "fashion", "art history", "visual culture", "design",
    "museum", "cultural heritage", "material culture", "curatorial",
    "textile", "costume", "artistic research",
]


def _from_api_item(it: dict) -> FoundPosting | None:
    vid = str(it.get("id") or it.get("vacancy_id") or "").strip()
    title = clean_plain_text(it.get("title") or it.get("title_en") or "")
    if not vid or not title:
        return None
    org_obj = it.get("organisation") or it.get("organization") or {}
    org = (org_obj.get("name") if isinstance(org_obj, dict) else str(org_obj or "")).strip()
    city = str(it.get("city") or it.get("location") or "").strip()
    url = it.get("url") or it.get("absolute_url") or f"{BASE}/en/jobs/{vid}/"
    if url.startswith("/"):
        url = urljoin(BASE, url)
    desc = strip_html(it.get("description") or it.get("summary") or "")
    if "cao nu" not in desc.lower() and "salaried" not in desc.lower():
        desc = (desc + " Salaried PhD employment contract (CAO NU, Netherlands).").strip()
    post = FoundPosting(
        source=SOURCE,
        external_id=vid,
        title=title,
        organization=org,
        country="NL",
        city=city,
        url=url,
        description=desc,
        posted_date=str(it.get("created") or it.get("published_at") or "")[:10],
        deadline=str(it.get("end_date") or it.get("deadline") or "")[:10] or extract_deadline(desc),
    )
    post.kind = "phd"
    post._kind_fixed = True
    return post


def _parse_html_page(html_text: str) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    # 1) Try embedded JSON-LD JobPosting blocks first
    for m in _LD_RE.finditer(html_text):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        items = d if isinstance(d, list) else (d.get("itemListElement") or [d])
        for obj in items:
            if not isinstance(obj, dict):
                continue
            jp = obj.get("item") if isinstance(obj.get("item"), dict) else obj
            if jp.get("@type") != "JobPosting" or not jp.get("title"):
                continue
            url = str(jp.get("url") or "")
            idm = re.search(r"/jobs/(\d+)/", url)
            vid = idm.group(1) if idm else str(jp.get("identifier") or "")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            hiring = jp.get("hiringOrganization") or {}
            org = hiring.get("name", "") if isinstance(hiring, dict) else ""
            desc = strip_html(jp.get("description") or "")
            post = FoundPosting(
                source=SOURCE,
                external_id=vid,
                title=clean_plain_text(jp["title"]),
                organization=clean_plain_text(org),
                country="NL",
                url=urljoin(BASE, url) if url.startswith("/") else url,
                description=desc,
                posted_date=str(jp.get("datePosted") or "")[:10],
                deadline=str(jp.get("validThrough") or "")[:10] or extract_deadline(desc),
            )
            post.kind = "phd"
            post._kind_fixed = True
            out.append(post)
    if out:
        return out
    # 2) Fallback: parse vacancy links on /en/jobs/?function_types=1
    for m in _JOB_LINK_RE.finditer(html_text):
        href, vid, raw_title = m.group(1), m.group(2), m.group(3)
        if vid in seen:
            continue
        title = clean_plain_text(strip_html(unescape(raw_title)))
        if len(title) < 6:
            continue
        seen.add(vid)
        post = FoundPosting(
            source=SOURCE,
            external_id=vid,
            title=title,
            organization="Dutch Research University (AcademicTransfer)",
            country="NL",
            url=urljoin(BASE, href),
            description=f"{title}. AcademicTransfer Netherlands PhD vacancy (CAO NU salaried doctoral employment).",
        )
        post.kind = "phd"
        post._kind_fixed = True
        out.append(post)
    return out


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    delay = float(cfg.get("delay_seconds", 1.5))
    keywords = cfg.get("keywords", DEFAULT_KEYWORDS)
    use_api = True

    for kw in keywords:
        items: list[FoundPosting] = []
        if use_api:
            try:
                r = polite_get(
                    session, API_URL,
                    params={"function_types": "1", "q": kw, "ordering": "-created"},
                    headers={"Accept": "application/json"},
                    timeout=20,
                )
                payload = r.json()
                raw_list = (payload.get("results") if isinstance(payload, dict)
                            else (payload if isinstance(payload, list) else []))
                for it in raw_list:
                    if isinstance(it, dict):
                        p = _from_api_item(it)
                        if p:
                            items.append(p)
            except SourceBlocked:
                return out
            except Exception:
                use_api = False

        if not use_api:
            try:
                r = polite_get(
                    session, HTML_URL,
                    params={"function_types": "1", "q": kw},
                    timeout=20,
                )
                items = _parse_html_page(r.text)
            except SourceBlocked:
                return out
            except (Timeout, ConnectionError):
                time.sleep(delay)
                continue
            except Exception:
                time.sleep(delay)
                continue

        for p in items:
            if p.key() not in seen:
                seen.add(p.key())
                out.append(p)
        time.sleep(delay)
    return out
