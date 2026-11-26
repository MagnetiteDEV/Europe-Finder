"""Campus France Doctoral Offers adapter (France — priority country FR).

Source: https://doctorat.campusfrance.org/phd/offers
Official French doctoral portal listing funded PhD offers (Contrat Doctoral,
CIFRE, MSCA) across French Écoles Doctorales in art, mode, design,
histoire de l'art, patrimoine, and humanities.

DISABLED in config (2026-11-25): the listing is a JavaScript-updated,
session-driven grid with no discoverable public JSON/API endpoint (plain
GETs to the usual API candidates return HTML), so this adapter returns 0
and only burns keyword requests. Re-enable only with a session-based or
browser route; the manual hub link stays.
"""
from __future__ import annotations

import re
import time
from html import unescape
from urllib.parse import urljoin

from requests.exceptions import ConnectionError, Timeout

from ..extract import clean_plain_text, extract_deadline
from ..http import SourceBlocked, polite_get
from . import FoundPosting
from .ats import strip_html

BASE = "https://doctorat.campusfrance.org"
OFFERS_URL = BASE + "/phd/offers"
SOURCE = "campusfrance_phd"

_OFFER_LINK_RE = re.compile(
    r'<a[^>]+href=["\'](/phd/offers/(\d+)[^"\']*)["\'][^>]*>(.*?)</a>',
    re.S | re.I)

DEFAULT_KEYWORDS = [
    "fashion", "mode", "art", "design", "histoire de l'art",
    "textile", "costume", "patrimoine", "culture visuelle",
]


def _parse_offers(html_text: str) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    for m in _OFFER_LINK_RE.finditer(html_text):
        href, oid, raw_title = m.group(1), m.group(2), m.group(3)
        if oid in seen:
            continue
        title = clean_plain_text(strip_html(unescape(raw_title)))
        if len(title) < 6:
            continue
        seen.add(oid)
        # Capture nearby card text for organization / funding / deadline hints
        snippet = clean_plain_text(strip_html(html_text[m.end():m.end() + 700]))
        dl = extract_deadline(snippet)
        p = FoundPosting(
            source=SOURCE,
            external_id=oid,
            title=title,
            organization="École Doctorale (Campus France)",
            country="FR",
            url=urljoin(BASE, href),
            description=f"{title}. {snippet[:450]}".strip(),
            deadline=dl,
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
            r = polite_get(session, OFFERS_URL, params={"q": kw}, timeout=25)
        except SourceBlocked:
            break
        except (Timeout, ConnectionError):
            time.sleep(delay)
            continue
        except Exception:
            time.sleep(delay)
            continue
        for p in _parse_offers(r.text):
            if p.key() not in seen:
                seen.add(p.key())
                out.append(p)
        time.sleep(delay)
    return out
