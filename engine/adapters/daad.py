"""DAAD adapters: the Scholarship Database (Germany) + PhDGermany RSS.

Scholarship Database
(https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/):
147 funding programmes. There is no public API; the frontend loads
static TaffyDB data files (scholarships.js, deadlines.js, origin.js)
whose URLs are re-discovered from the database page's <script> tags
on every run (with the ?cb= cache-buster), so a file move does not
silently break the adapter. robots.txt on www.daad.de does not
disallow the database path (Crawl-delay: 2, honoured between
requests); www2.daad.de has no robots file.

Two findings from the live data shape the adapter:
- subjectGrps is NOT discriminating (most programmes list all seven
  groups), so relevance is pre-filtered on the programme name +
  introduction text with the engine vocabulary instead.
- Deadlines are per origin country (dict keyed by origin id; Iran =
  192, resolved from origin.js, never assumed). The deadline shown
  is Iran's when it is in the future, else the latest future date
  across countries, else none — a past deadline never hides a
  recurring programme, and the description always notes that
  deadlines vary by country of origin. Eligibility is never inferred
  from the origin list.
Detail links use the frontend's own pattern (?detail=<sapProgid>),
verified to return 200 and keep the detail parameter.

PhDGermany (https://api.daad.de/api/feeds/rss/en/phd.xml): public RSS
of doctoral offers in Germany (27 latest items). Item dates use the
non-RFC form "17. Nov 2026" (custom parse). All items are kept; the
engine matcher scores them (expect ~0 in-field hits most months —
a cheap net for rare humanities doctorates).
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from html import unescape
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser

from ..http import SourceBlocked, polite_get
from ..match import contains_term, normalize_text
from ..vocab import ANCHORS, FIELD_GROUPS
from . import FoundPosting
from .ats import strip_html

DB_PAGE = ("https://www2.daad.de/deutschland/stipendium/datenbank/en/"
           "21148-scholarship-database/")
DB_PAGES = (
    DB_PAGE,
    "https://www.daad.de/deutschland/stipendium/datenbank/en/"
    "21148-scholarship-database/",
)
DB_HOST = "https://www2.daad.de"
PHD_FEED = "https://api.daad.de/api/feeds/rss/en/phd.xml"
PHD_PAGE = "https://www.daad.de/en/studying-in-germany/phd-studies-research/phd-germany/"

_TAFFY_RE = re.compile(r"TAFFY\((.*)\)\s*;?\s*$", re.S)
_SCRIPT_RE = re.compile(r'src="([^"]+)"')
_DEADLINE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")
_PHD_DATE_RE = re.compile(r"(\d{1,2})\.\s*([A-Za-z]+)\.?\s+(\d{4})")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
_MONTHS.update({m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
     "Aug", "Sep", "Oct", "Nov", "Dec"])})

# pre-filter vocabulary: engine phrases/anchors + programme-name words
_PREFILTER: set[str] = set()
for _terms in ANCHORS.values():
    _PREFILTER.update(_terms)
for _fa, _w, _terms in FIELD_GROUPS.values():
    _PREFILTER.update(_terms)
_PREFILTER.update(["art", "film", "music", "architecture", "media",
                   "heritage", "museum", "visual",
                   "performing arts", "applied arts", "craft"])
# NOTE: bare "culture" and "performing" are deliberately NOT here —
# they admitted a general state ministry grant ("Ministry for ...
# Culture ...") and the all-discipline DFG Heisenberg Programme
# ("performing research"). The specific phrases "cultural heritage",
# "cultural studies" (FIELD_GROUPS) and "performing arts" (above)
# keep the genuinely relevant programmes.


def _load_taffy(text: str) -> list:
    m = _TAFFY_RE.search(text.strip())
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _alternate_daad_host_url(url: str) -> str:
    """Same DAAD path on the sibling host (www2 <-> www), else ''."""
    p = urlparse(url)
    if p.netloc == "www2.daad.de":
        return urlunparse(p._replace(netloc="www.daad.de"))
    if p.netloc == "www.daad.de":
        return urlunparse(p._replace(netloc="www2.daad.de"))
    return ""


def _get_with_daad_host_fallback(session, url: str, **kwargs):
    try:
        return polite_get(session, url, **kwargs)
    except SourceBlocked:
        alt = _alternate_daad_host_url(url)
        if not alt:
            raise
        return polite_get(session, alt, **kwargs)


def _discover_taffy_urls(session) -> dict[str, str]:
    errors: list[str] = []
    for page_url in DB_PAGES:
        try:
            page = polite_get(session, page_url)
        except SourceBlocked as e:
            errors.append(str(e))
            continue
        urls: dict[str, str] = {}
        for src in _SCRIPT_RE.findall(page.text):
            clean_src = unescape(src)
            for key in ("scholarships", "deadlines", "origin"):
                if f"/{key}.js" in clean_src:
                    urls[key] = urljoin(page_url, clean_src)
        if "scholarships" in urls:
            return urls
        errors.append(f"scholarships.js script not found on {page_url}")
    raise SourceBlocked("; ".join(errors)[:300] or
                        "scholarships.js script not found on DAAD database page")


def _relevant(name: str, intro: str) -> bool:
    t = normalize_text(f"{name} {intro}")
    return any(contains_term(t, w) for w in _PREFILTER)


def _parse_deadline_text(text: str) -> str:
    """Leading DD.MM.YYYY in a deadline note, else ''."""
    clean = strip_html(text or "")
    m = _DEADLINE_RE.search(clean)
    if not m:
        return ""
    try:
        return date(int(m.group(3)), int(m.group(2)),
                    int(m.group(1))).isoformat()
    except ValueError:
        return ""


def _resolve_deadline(rec: dict, iran_id: int) -> str:
    """Iran's future deadline if listed, else the latest future date
    across countries, else '' (never a past date)."""
    countries = rec.get("countries") or {}
    if not isinstance(countries, dict):
        return ""
    today = date.today().isoformat()
    dates: dict[str, str] = {}
    for origin_id, notes in countries.items():
        for note in notes or []:
            iso = _parse_deadline_text((note or {}).get("en", ""))
            if iso and iso >= today:
                dates[str(origin_id)] = iso
                break
    if not dates:
        return ""
    if str(iran_id) in dates:
        return dates[str(iran_id)]
    return max(dates.values())


def search(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    delay = float(cfg.get("delay_seconds", 2))
    # SourceBlocked propagates to ingest, which records the reason in
    # the bundle health warning — swallowing it here made DAAD's
    # 26-27 Nov zeros in the GitHub run environment undiagnosable
    # from outside (the bundle only said "returned 0"). The database
    # is served from both www2.daad.de and www.daad.de; if one host
    # blocks the runner, the sibling host is tried before giving up.
    urls = _discover_taffy_urls(session)
    data: dict[str, list] = {}
    for key in ("scholarships", "deadlines", "origin"):
        if key not in urls:
            continue
        try:
            time.sleep(delay)
            r = _get_with_daad_host_fallback(session, urls[key])
            data[key] = _load_taffy(r.text)
        except SourceBlocked:
            if key == "scholarships":
                raise
            continue
    scholarships = data.get("scholarships", [])
    if not scholarships:
        raise SourceBlocked(
            "scholarships.js parsed empty (0 programmes)")
    iran_id = 192
    for o in data.get("origin", []):
        if (o.get("nameEn") or "").strip().lower() == "iran":
            iran_id = o.get("id", 192)
            break
    deadlines = {d.get("id"): d for d in data.get("deadlines", [])
                 if isinstance(d, dict)}
    for rec in scholarships:
        name = (rec.get("programmnameEn") or rec.get("nameEn") or "").strip()
        intro = strip_html((rec.get("introduction") or {}).get("en") or "")
        if not name or not _relevant(name, intro):
            continue
        dl_rec = deadlines.get(rec.get("sapProgid"), {})
        deadline = _resolve_deadline(dl_rec, iran_id)
        desc = name
        if intro:
            desc += ". " + intro
        desc += (" Deadlines vary by country of origin; see the "
                 "programme page for the date applying to you.")
        post = FoundPosting(
            source="daad",
            external_id=str(rec.get("id", "")),
            title=" ".join(name.split()),
            organization="DAAD",
            country="DE",
            url=(DB_PAGE + f"?detail={rec.get('sapProgid')}"
                 if rec.get("sapProgid") else DB_PAGE),
            description=" ".join(desc.split()),
            deadline=deadline,
        )
        post.kind = "scholarship"
        post._kind_fixed = True
        out.append(post)
    return out


def _parse_phd_date(text: str) -> str:
    m = _PHD_DATE_RE.search(text or "")
    if not m:
        return _parse_deadline_text(text or "")
    mon = _MONTHS.get(m.group(2).rstrip("."))
    if not mon:
        return _parse_deadline_text(text or "")
    try:
        return date(int(m.group(3)), mon, int(m.group(1))).isoformat()
    except ValueError:
        return ""


_PHD_ORG_PATTERNS = [
    re.compile(r"(Universität\s+[A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+)?)"),
    re.compile(r"(Technische\s+Universität\s+[A-ZÄÖÜ][a-zäöüß\-]+)"),
    re.compile(r"(TUD\s+Dresden\s+University\s+of\s+Technology)"),
    re.compile(r"(Clausthal\s+University\s+of\s+Technology)"),
    re.compile(r"(University\s+of\s+[A-ZÄÖÜ][a-zäöüß\-]+)"),
    re.compile(r"(Karlsruhe\s+Institute\s+of\s+Technology(?:\s*\(KIT\))?)"),
    re.compile(r"(Friedrich-Alexander-Universität\s+Erlangen[–\-]Nürnberg(?:\s*\(FAU\))?)"),
    re.compile(r"(Max\s+Planck\s+(?:Institute|School)\s+(?:for|of)\s+[A-Za-z\s&\-]+?)(?=\s+(?:is|in|and|offers|\(|,|—|\.))"),
    re.compile(r"(International\s+Max\s+Planck\s+Research\s+School\s+(?:for|of)\s+[A-Za-z\s&\-]+?)(?=\s+(?:is|invites|\(|,|\.))"),
    re.compile(r"(Center\s+for\s+the\s+Transformation\s+of\s+Chemistry\s*\(CTC\))"),
    re.compile(r"(LMU\s+Munich)"),
    re.compile(r"(Helmholtz[A-Za-z\-\s]+?(?:Dresden|Munich|Berlin|Center|Zentrum)[A-Za-z\-\s]*)"),
]


def _extract_phd_org(title: str, desc: str, city: str) -> str:
    text = f"{title} {desc}"
    for pat in _PHD_ORG_PATTERNS:
        m = pat.search(text)
        if m:
            org = m.group(1).strip(" ,.-—")
            if 3 <= len(org) <= 80:
                return org
    return f"PhD Germany ({city})" if city else "PhD Germany (DAAD)"


def _phd_external_id(entry) -> str:
    for key in ("id", "guid"):
        val = str(entry.get(key, "") or "").strip()
        if val:
            m = re.search(r"[?&]phd-id=(\d+)", val)
            return m.group(1) if m else val
    link = str(entry.get("link", "") or "").strip()
    m = re.search(r"[?&]phd-id=(\d+)", link)
    if m:
        return m.group(1)
    m = re.search(r"/detail/[^/]*-(\d+)/?$", link)
    if m:
        return m.group(1)
    return link


def _phd_post_from_fields(ext_id: str, title: str, link: str, desc: str,
                          city: str, published: str, deadline: str) -> FoundPosting:
    title = " ".join((title or "").split())
    city = " ".join((city or "").split())
    desc = strip_html(desc or "")
    post = FoundPosting(
        source="phdgermany",
        external_id=ext_id,
        title=title,
        organization=_extract_phd_org(title, desc, city),
        country="DE",
        city=city,
        url=link,
        description=desc,
        posted_date=_parse_phd_date(published),
        deadline=_parse_phd_date(deadline),
    )
    post.kind = "phd"
    post._kind_fixed = True
    return post


def _parse_phd_feed_bytes(content: bytes) -> list[FoundPosting]:
    feed = feedparser.parse(content)
    out: list[FoundPosting] = []
    for e in getattr(feed, "entries", []) or []:
        ext_id = _phd_external_id(e)
        if not ext_id:
            continue
        out.append(_phd_post_from_fields(
            ext_id,
            e.get("title", ""),
            e.get("link", ""),
            e.get("summary", ""),
            e.get("location", ""),
            e.get("published", ""),
            e.get("applicationdeadline", ""),
        ))
    if out:
        return out
    # feedparser can return no entries for a valid feed when a custom
    # element confuses it; fall back to a namespace-agnostic XML walk.
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(content)
    except Exception:
        return out
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1].lower() != "item":
            continue
        fields: dict[str, str] = {}
        for child in item:
            key = child.tag.rsplit("}", 1)[-1].lower()
            fields[key] = "".join(child.itertext()).strip()
        link = fields.get("link", "")
        ext_id = fields.get("guid") or fields.get("id") or link
        m = re.search(r"[?&]phd-id=(\d+)", ext_id or link)
        if m:
            ext_id = m.group(1)
        if not ext_id:
            continue
        out.append(_phd_post_from_fields(
            ext_id,
            fields.get("title", ""),
            link,
            fields.get("description", ""),
            fields.get("location", ""),
            fields.get("pubdate", "") or fields.get("published", ""),
            fields.get("applicationdeadline", ""),
        ))
    return out


def _parse_phd_html(html: str) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    seen: set[str] = set()
    anchor_re = re.compile(
        r'<a[^>]+href="([^"]*/phd-germany/detail/[^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S)
    matches = list(anchor_re.finditer(html or ""))
    prev_end = 0
    for m in matches:
        link = urljoin(PHD_PAGE, unescape(m.group(1)))
        ext_m = re.search(r"[?&]phd-id=(\d+)", link) or re.search(
            r"/detail/[^/]*-(\d+)/?$", link)
        ext_id = ext_m.group(1) if ext_m else link
        # The detail anchor sits at the END of each article ("More
        # about {institution}"); the institution, <h3> title, deadline
        # and location are in the block before it.
        segment = html[prev_end:m.end()]
        prev_end = m.end()
        if ext_id in seen:
            continue
        seen.add(ext_id)
        block = strip_html(segment)
        h3 = re.search(r"<h3[^>]*>(.*?)</h3>", segment, re.I | re.S)
        title = " ".join(strip_html(h3.group(1)).split()) if h3 else ""
        if not title:
            anchor_text = " ".join(strip_html(m.group(2)).split())
            if anchor_text and not anchor_text.lower().startswith("more about"):
                title = anchor_text
        if not title:
            title = block.split("Deadline:")[0].strip()
        deadline_m = re.search(
            r"(?:Application deadline|Deadline):\s*(\d{1,2}[./]\d{1,2}[./]\d{4})",
            block)
        location_m = re.search(
            r"Location:\s*(.+?)(?:Last changed:|More about|$)", block)
        posted_m = re.search(
            r"Last changed:\s*(\d{1,2}[./]\d{1,2}[./]\d{4})", block)
        out.append(_phd_post_from_fields(
            ext_id,
            title,
            link,
            block,
            location_m.group(1).strip() if location_m else "",
            posted_m.group(1) if posted_m else "",
            deadline_m.group(1) if deadline_m else "",
        ))
    return out


def search_phd(session, cfg: dict) -> list[FoundPosting]:
    errors: list[str] = []
    try:
        r = polite_get(session, PHD_FEED, timeout=30)
        posts = _parse_phd_feed_bytes(r.content)
        if posts:
            return posts
        errors.append("PhDGermany RSS parsed empty (0 entries)")
    except SourceBlocked as e:
        errors.append(str(e))
    # RSS is the primary route; the public listing page is the safety
    # net when api.daad.de blocks the runner or the feed shape changes.
    page = polite_get(session, PHD_PAGE, timeout=30)
    posts = _parse_phd_html(page.text)
    if posts:
        return posts
    errors.append("PhDGermany listing page parsed empty (0 entries)")
    raise SourceBlocked("; ".join(errors)[:300])
