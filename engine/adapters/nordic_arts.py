"""Swiss (myScience.ch) and Danish (University of Copenhagen PhD) adapters.

- myScience.ch: public Swiss academic job portal (salaried PhDs across
  Swiss universities and art/design academies). DISABLED in config since
  v2.9.4 (2026-11-24): the site sits behind a verify-wall and every
  request from a plain HTTP client times out (even /verify) — the adapter
  would burn ~90s per keyword in polite_get retries and return 0. Re-enable
  only with a browser/API route; the manual hub link stays.
- KU PhD (employment.ku.dk/all-vacancies/): University of Copenhagen
  vacancies table (priority country DK — all Danish PhDs are salaried
  3-year university employment contracts). The /phd/ page carries no job
  links in its HTML; the server-rendered all-vacancies table does
  (verified live 2026-11-25), so the adapter reads that page and keeps
  only genuine PhD titles.
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

MYSCIENCE_BASE = "https://www.myscience.ch"
MYSCIENCE_URL = MYSCIENCE_BASE + "/jobs"
KU_BASE = "https://employment.ku.dk"
KU_PHD_URL = KU_BASE + "/all-vacancies/"

_MYSCI_LINK_RE = re.compile(
    r'<a[^>]+href=["\'](/jobs/id(\d+)[^"\']*)["\'][^>]*>(.*?)</a>',
    re.S | re.I)
_KU_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']*?show=(\d+)[^"\']*)["\'][^>]*>(.*?)</a>',
    re.S | re.I)
_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)

DEFAULT_SWISS_KEYWORDS = [
    "PhD art", "PhD design", "PhD fashion", "PhD museum",
    "PhD visual culture", "PhD heritage", "PhD history of art",
]


def _parse_myscience(html_text: str) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    for m in _LD_RE.finditer(html_text):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        items = d if isinstance(d, list) else [d]
        for b in items:
            if not isinstance(b, dict) or b.get("@type") != "JobPosting":
                continue
            title = clean_plain_text(b.get("title") or "")
            url = str(b.get("url") or "")
            idm = re.search(r"id(\d+)", url)
            jid = idm.group(1) if idm else str(b.get("identifier") or "")
            if not jid or not title or jid in seen:
                continue
            seen.add(jid)
            hiring = b.get("hiringOrganization") or {}
            org = hiring.get("name", "") if isinstance(hiring, dict) else ""
            desc = strip_html(b.get("description") or "")
            p = FoundPosting(
                source="myscience",
                external_id=jid,
                title=title,
                organization=clean_plain_text(org),
                country="CH",
                url=urljoin(MYSCIENCE_BASE, url) if url.startswith("/") else url,
                description=desc,
                posted_date=str(b.get("datePosted") or "")[:10],
                deadline=str(b.get("validThrough") or "")[:10] or extract_deadline(desc),
            )
            if re.search(r"\b(ph\.?\s*d\.?|doctoral|doktorand)\b", title, re.I):
                p.kind = "phd"
                p._kind_fixed = True
            out.append(p)
    if out:
        return out
    for m in _MYSCI_LINK_RE.finditer(html_text):
        href, jid, raw_title = m.group(1), m.group(2), m.group(3)
        if jid in seen:
            continue
        title = clean_plain_text(strip_html(unescape(raw_title)))
        if len(title) < 6:
            continue
        seen.add(jid)
        p = FoundPosting(
            source="myscience",
            external_id=jid,
            title=title,
            organization="Swiss Academic Institution (myScience.ch)",
            country="CH",
            url=urljoin(MYSCIENCE_BASE, href),
            description=f"{title}. Swiss doctoral/research position (myScience.ch).",
        )
        if re.search(r"\b(ph\.?\s*d\.?|doctoral|doktorand)\b", title, re.I):
            p.kind = "phd"
            p._kind_fixed = True
        out.append(p)
    return out


def search_myscience(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    delay = float(cfg.get("delay_seconds", 2.0))
    for kw in cfg.get("keywords", DEFAULT_SWISS_KEYWORDS):
        try:
            r = polite_get(session, MYSCIENCE_URL, params={"q": kw}, timeout=20)
        except SourceBlocked:
            break
        except (Timeout, ConnectionError):
            time.sleep(delay)
            continue
        except Exception:
            time.sleep(delay)
            continue
        for p in _parse_myscience(r.text):
            if p.key() not in seen:
                seen.add(p.key())
                out.append(p)
        time.sleep(delay)
    return out


_KU_PHD_MARKER_RE = re.compile(r"\bph\.?\s*d\.?\b", re.I)
_KU_NON_PHD_RE = re.compile(
    r"\b(postdoc|postdoctoral|research assistants?|professors?)\b", re.I)
_KU_DATE_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")


def _parse_ku_phd(html_text: str) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    for m in _KU_LINK_RE.finditer(html_text):
        href, jid, raw_title = m.group(1), m.group(2), m.group(3)
        if jid in seen:
            continue
        title = clean_plain_text(strip_html(unescape(raw_title)))
        if len(title) < 6:
            continue
        # The all-vacancies table mixes every job type: keep only genuine
        # PhD titles. This drops e.g. "Research Assistant with opportunity
        # for PhD-fellowship continuation", which carries a PhD marker but
        # is not a PhD vacancy.
        if not _KU_PHD_MARKER_RE.search(title) or _KU_NON_PHD_RE.search(title):
            continue
        seen.add(jid)
        # Bound the snippet at the next row's anchor so the faculty /
        # location / deadline cells read belong to this row only.
        nxt = html_text.find("<a", m.end())
        raw_seg = html_text[m.end():nxt] if nxt != -1 else html_text[m.end():m.end() + 800]
        snippet = clean_plain_text(strip_html(raw_seg))
        dl = extract_deadline(snippet)
        if not dl:
            # Table cells carry a bare DD-MM-YYYY date with no deadline
            # keyword for extract_deadline to anchor on.
            dm = _KU_DATE_RE.search(snippet)
            if dm:
                dl = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
        p = FoundPosting(
            source="ku_phd",
            external_id=jid,
            title=title,
            organization="University of Copenhagen",
            country="DK",
            city="Copenhagen",
            url=urljoin(KU_BASE, href),
            description=f"{title}. Salaried PhD fellowship at University of Copenhagen, Denmark. {snippet[:300]}".strip(),
            deadline=dl,
        )
        p.kind = "phd"
        p._kind_fixed = True
        out.append(p)
    return out


def search_ku_phd(session, cfg: dict) -> list[FoundPosting]:
    try:
        r = polite_get(session, KU_PHD_URL, timeout=25)
    except SourceBlocked:
        return []
    except (Timeout, ConnectionError):
        return []
    except Exception:
        return []
    return _parse_ku_phd(r.text)
