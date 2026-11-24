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

import feedparser

from ..http import SourceBlocked, polite_get
from ..match import contains_term, normalize_text
from ..vocab import ANCHORS, FIELD_GROUPS
from . import FoundPosting
from .ats import strip_html

DB_PAGE = ("https://www2.daad.de/deutschland/stipendium/datenbank/en/"
           "21148-scholarship-database/")
DB_HOST = "https://www2.daad.de"
PHD_FEED = "https://api.daad.de/api/feeds/rss/en/phd.xml"

_TAFFY_RE = re.compile(r"TAFFY\((.*)\)\s*;?\s*$", re.S)
_SCRIPT_RE = re.compile(r'src="([^"]+)"')
_DEADLINE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
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
    try:
        page = polite_get(session, DB_PAGE)
    except SourceBlocked:
        return out
    urls: dict[str, str] = {}
    for src in _SCRIPT_RE.findall(page.text):
        for key in ("scholarships", "deadlines", "origin"):
            if f"/{key}.js" in src:
                urls[key] = (DB_HOST + unescape(src) if src.startswith("/")
                             else unescape(src))
    if "scholarships" not in urls:
        return out
    data: dict[str, list] = {}
    for key in ("scholarships", "deadlines", "origin"):
        if key not in urls:
            continue
        try:
            time.sleep(delay)
            r = polite_get(session, urls[key])
            data[key] = _load_taffy(r.text)
        except SourceBlocked:
            break
    scholarships = data.get("scholarships", [])
    if not scholarships:
        return out
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
        return ""
    mon = _MONTHS.get(m.group(2).rstrip("."))
    if not mon:
        return ""
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


def search_phd(session, cfg: dict) -> list[FoundPosting]:
    out: list[FoundPosting] = []
    try:
        r = polite_get(session, PHD_FEED, timeout=30)
    except SourceBlocked:
        return out
    feed = feedparser.parse(r.content)
    for e in feed.entries:
        ext_id = str(e.get("id", "")).strip()
        if not ext_id:
            continue
        title = " ".join((e.get("title") or "").split())
        city = " ".join((e.get("location") or "").split())
        desc = strip_html(e.get("summary", ""))
        post = FoundPosting(
            source="phdgermany",
            external_id=ext_id,
            title=title,
            organization=_extract_phd_org(title, desc, city),
            country="DE",
            city=city,
            url=e.get("link", ""),
            description=desc,
            posted_date=_parse_phd_date(e.get("published", "")),
            deadline=_parse_phd_date(e.get("applicationdeadline", "")),
        )
        post.kind = "phd"
        post._kind_fixed = True
        out.append(post)
    return out
