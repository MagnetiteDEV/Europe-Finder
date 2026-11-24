"""Lightweight extraction: deadlines, countries, funding signals, kind."""
from __future__ import annotations

import html
import re
from datetime import date

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # German months (ArtHist.net announcements, DAAD texts)
    "januar": 1, "februar": 2, "märz": 3, "marz": 3, "mai": 5,
    "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    # French months (Campus France Doctorat / ADUM)
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

_DEADLINE_HINT = re.compile(
    r"(deadline|closing date|apply by|applications? (?:close|due)|"
    r"deadline for application|submission deadline|application deadline|"
    r"date limite|clôture|bewerbungsschluss|bewerbungsfrist|einsendeschluss)",
    re.I)
_DATE1 = re.compile(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})")
_DATE1B = re.compile(r"(\d{1,2})\.\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})")
_DATE2 = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATE3 = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")
_DOC_WRITE_RE = re.compile(
    r"\s*document\.write\s*\(\s*String\.fromCharCode\s*\([^)]*\)\s*\)\s*(?:\[at\]\s*)?",
    re.I)


def clean_plain_text(text: str) -> str:
    """Clean residual HTML tags/entities and ArtHist obfuscated JS emails."""
    if not text:
        return ""
    s = _DOC_WRITE_RE.sub("@", text)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?(?:p|div|li|ul|ol|span|strong|em|b|i|a|h[1-6])\b[^>]*>",
               " ", s, flags=re.I)
    s = html.unescape(html.unescape(s))
    s = s.replace("\xa0", " ")
    return " ".join(s.split())


def _valid(y: int, m: int, d: int) -> str:
    try:
        dt = date(y, m, d)
    except ValueError:
        return ""
    if dt < date(2000, 1, 1) or dt > date(2100, 1, 1):
        return ""
    return dt.isoformat()


def extract_deadline(text: str) -> str:
    """First plausible deadline date near a deadline keyword, else ''."""
    if not text:
        return ""
    for m in _DEADLINE_HINT.finditer(text):
        window = text[m.end():m.end() + 80]
        d1 = _DATE1.search(window)
        if d1:
            mon = _MONTHS.get(d1.group(2).lower().rstrip("."))
            if mon:
                iso = _valid(int(d1.group(3)), mon, int(d1.group(1)))
                if iso:
                    return iso
        d1b = _DATE1B.search(window)
        if d1b:
            mon = _MONTHS.get(d1b.group(2).lower().rstrip("."))
            if mon:
                iso = _valid(int(d1b.group(3)), mon, int(d1b.group(1)))
                if iso:
                    return iso
        d2 = _DATE2.search(window)
        if d2:
            iso = _valid(int(d2.group(1)), int(d2.group(2)), int(d2.group(3)))
            if iso:
                return iso
        d3 = _DATE3.search(window)
        if d3:
            y = int(d3.group(3))
            y += 2000 if y < 100 else 0
            iso = _valid(y, int(d3.group(2)), int(d3.group(1)))
            if iso:
                return iso
    return ""


_COUNTRIES = {
    # name variants -> ISO-2 (Europe-focused)
    "united kingdom": "GB", "uk": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "london": "GB", "ireland": "IE", "france": "FR", "paris": "FR",
    "germany": "DE", "deutschland": "DE", "berlin": "DE", "netherlands": "NL",
    "holland": "NL", "dutch": "NL", "amsterdam": "NL", "belgium": "BE",
    "spain": "ES", "españa": "ES", "italy": "IT", "italia": "IT", "milan": "IT",
    "milano": "IT", "venice": "IT", "venezia": "IT", "bologna": "IT",
    "portugal": "PT", "lisbon": "PT", "lisboa": "PT", "sweden": "SE",
    "sverige": "SE", "stockholm": "SE", "norway": "NO", "norge": "NO",
    "denmark": "DK", "danmark": "DK", "copenhagen": "DK", "københavn": "DK",
    "finland": "FI", "suomi": "FI", "helsinki": "FI", "austria": "AT",
    "österreich": "AT", "vienna": "AT", "wien": "AT", "switzerland": "CH",
    "schweiz": "CH", "zurich": "CH", "zürich": "CH", "poland": "PL",
    "polska": "PL", "czech": "CZ", "czechia": "CZ", "prague": "CZ",
    "praha": "CZ", "hungary": "HU", "budapest": "HU", "greece": "GR",
    "athens": "GR", "croatia": "HR", "romania": "RO", "bulgaria": "BG",
    "estonia": "EE", "latvia": "LV", "lithuania": "LT", "slovenia": "SI",
    "slovakia": "SK", "luxembourg": "LU",
    # Australia (Workday/PageUp tenants) + UK & European art-school cities
    "australia": "AU", "melbourne": "AU", "sydney": "AU", "brisbane": "AU",
    "perth": "AU", "adelaide": "AU", "canberra": "AU", "hobart": "AU",
    "geelong": "AU", "wollongong": "AU", "gold coast": "AU",
    "queensland": "AU", "new south wales": "AU", "nsw": "AU",
    "western australia": "AU", "south australia": "AU", "tasmania": "AU",
    "australian capital territory": "AU", "newcastle nsw": "AU",
    "clayton": "AU", "caulfield": "AU", "parkville": "AU",
    "burwood": "AU", "waurn ponds": "AU", "warrnambool": "AU",
    "st lucia campus": "AU", "st lucia": "AU", "camperdown campus": "AU",
    "camperdown": "AU", "st kilda road": "AU", "peninsula campus": "AU",
    "espoo": "FI", "otaniemi": "FI", "rovaniemi": "FI",
    "hanoi": "VN", "ho chi minh": "VN", "singapore": "SG",
    "glasgow": "GB", "edinburgh": "GB", "birmingham": "GB", "manchester": "GB",
    "leeds": "GB", "york": "GB", "gateshead": "GB", "braintree": "GB",
    "hull": "GB", "coventry": "GB", "derby": "GB", "epsom": "GB",
    "exeter": "GB", "gloucester": "GB", "southampton": "GB", "oxford": "GB",
    "cambridge": "GB", "shrewsbury": "GB", "bristol": "GB", "liverpool": "GB",
    "sheffield": "GB", "nottingham": "GB", "cardiff": "GB", "belfast": "GB",
    "brighton": "GB", "bath": "GB", "dublin": "IE",
    "florence": "IT", "florenz": "IT", "firenze": "IT", "rome": "IT",
    "roma": "IT", "turin": "IT", "torino": "IT", "naples": "IT", "napoli": "IT",
    "rotterdam": "NL", "eindhoven": "NL", "utrecht": "NL", "leiden": "NL",
    "delft": "NL", "groningen": "NL", "nijmegen": "NL", "maastricht": "NL",
    "ghent": "BE", "gent": "BE", "antwerp": "BE", "antwerpen": "BE",
    "leuven": "BE", "brussels": "BE", "bruxelles": "BE",
    "oslo": "NO", "bergen": "NO", "trondheim": "NO", "stavanger": "NO",
    "tromsø": "NO", "tromso": "NO",
    "gothenburg": "SE", "göteborg": "SE", "lund": "SE", "uppsala": "SE",
    "malmö": "SE", "malmo": "SE", "aarhus": "DK", "odense": "DK",
    "hamburg": "DE", "munich": "DE", "münchen": "DE", "cologne": "DE",
    "köln": "DE", "stuttgart": "DE", "dresden": "DE", "leipzig": "DE",
    "freiburg": "DE", "weimar": "DE", "heidelberg": "DE", "frankfurt": "DE",
    "barcelona": "ES", "madrid": "ES", "valencia": "ES", "a coruña": "ES",
    "porto": "PT", "coimbra": "PT",
    "lyon": "FR", "marseille": "FR", "bordeaux": "FR", "lille": "FR",
    "nantes": "FR", "strasbourg": "FR", "toulouse": "FR", "roubaix": "FR",
    "angers": "FR", "mulhouse": "FR", "dijon": "FR",
    "geneva": "CH", "genève": "CH", "lausanne": "CH", "basel": "CH",
    "bern": "CH", "innsbruck": "AT", "graz": "AT", "salzburg": "AT",
    "krakow": "PL", "kraków": "PL", "warsaw": "PL", "warszawa": "PL",
    "brno": "CZ", "ljubljana": "SI", "zagreb": "HR", "tallinn": "EE",
    "riga": "LV", "vilnius": "LT", "reykjavik": "IS",
}
_CC_RE = re.compile(r"\(([A-Z]{2})\)")
_ISO2 = {
    "AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX","AZ",
    "BA","BB","BD","BE","BF","BG","BH","BI","BJ","BL","BM","BN","BO","BQ","BR","BS",
    "BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG","CH","CI","CK","CL","CM","CN",
    "CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ","DK","DM","DO","DZ","EC","EE",
    "EG","EH","ER","ES","ET","FI","FJ","FK","FM","FO","FR","GA","GB","GD","GE","GF",
    "GG","GH","GI","GL","GM","GN","GP","GQ","GR","GS","GT","GU","GW","GY","HK","HM",
    "HN","HR","HT","HU","ID","IE","IL","IM","IN","IO","IQ","IR","IS","IT","JE","JM",
    "JO","JP","KE","KG","KH","KI","KM","KN","KP","KR","KW","KY","KZ","LA","LB","LC",
    "LI","LK","LR","LS","LT","LU","LV","LY","MA","MC","MD","ME","MF","MG","MH","MK",
    "ML","MM","MN","MO","MP","MQ","MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA",
    "NC","NE","NF","NG","NI","NL","NO","NP","NR","NU","NZ","OM","PA","PE","PF","PG",
    "PH","PK","PL","PM","PN","PR","PS","PT","PW","PY","QA","RE","RO","RS","RU","RW",
    "SA","SB","SC","SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS",
    "ST","SV","SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN","TO",
    "TR","TT","TV","TW","TZ","UA","UG","UM","US","UY","UZ","VA","VC","VE","VG","VI",
    "VN","VU","WF","WS","YE","YT","ZA","ZM","ZW",
}


def _valid_cc(code: str) -> str:
    return code if code in _ISO2 else ""


def extract_country(text: str, hint: str = "") -> str:
    for src in (hint, text):
        if not src:
            continue
        m = _CC_RE.search(src)
        if m and _valid_cc(m.group(1)):
            return m.group(1)
        low = src.lower()
        for name, code in _COUNTRIES.items():
            if re.search(r"\b" + re.escape(name) + r"\b", low):
                return code
    return ""


FUNDED_POS = ["fully funded", "full funding", "salaried", "salary",
              "stipend", "scholarship", "tuition waiver", "employed as",
              "employment contract", "monthly allowance"]
FUNDED_NEG = ["self-funded", "self funded", "without funding", "unfunded",
              "no funding", "fees apply", "tuition fees"]


def funding_signals(text: str) -> tuple[list[str], list[str]]:
    low = (text or "").lower()
    pos = [p for p in FUNDED_POS if p in low]
    neg = [n for n in FUNDED_NEG if n in low]
    return pos, neg


_INTERN_TITLE_RE = re.compile(
    r"\b(intern|internship|internships|praktikum|praktikant|stagiaire|stage)\b",
    re.I)
_NON_PHD_TITLE_RE = re.compile(
    r"\b(lecturer|professor|professorship|adjunct\s+professor|"
    r"assistant\s+professor|associate\s+professor|dean|associate\s+dean|"
    r"head\s+of|administrator|research\s+associate|research\s+fellow|"
    r"clinical\s+research\s+fellow|post-?doc(?:toral)?|bioinformatician|"
    r"innovation\s+associate|graduate\s+teaching\s+assistant|"
    r"research\s+assistant|technician|librarian|archivist|curator|"
    r"coordinator|manager|director|officer|operative|counsel|accountant|"
    r"sales\s+associate|sales\s+assistant|teacher\s+of)\b",
    re.I)
_EXPLICIT_PHD_TITLE_RE = re.compile(
    r"\b(ph\.?\s*d\.?\s*(?:position|positions|student|students|candidate|"
    r"candidates|studentship|studentships|fellowship|fellowships|"
    r"researcher|scholarship|opportunity|vacancy|programme|program|in\b)|"
    r"doctoral\s*(?:position|positions|student|students|candidate|candidates|"
    r"researcher|fellow|fellowship|scholarship|studentship|programme|program)|"
    r"doktorand(?:in)?|doctorant(?:e)?|mphil/phd|mres/phd|phd\s+and\s+mphil|"
    r"stipendiat|prae-?doc|th[eè]se\s+de\s+doctorat|contrat\s+doctoral|"
    r"marie\s+(?:sk[lł]odowska-)?curie\s+(?:itn|dn|doctoral))\b",
    re.I)
_PHD_BODY_OFFER_RE = re.compile(
    r"\b(phd\s+position|phd\s+studentship|doctoral\s+position|"
    r"doctoral\s+candidate|doctoral\s+researcher|verfassen\s+einer\s+dissertation|"
    r"work\s+toward\s+a\s+doctoral\s+degree|phd\s+project\s+with|"
    r"enrol(?:l)?\s+in\s+(?:a|our|the)\s+phd|pursue\s+a\s+phd)\b",
    re.I)


def detect_kind(title: str, description: str) -> str:
    """phd | job | other. Title-first classification so faculty/staff jobs
    that merely require a PhD in their description stay 'job', while real
    doctoral offers (including German TV-L E13 Dissertation roles) become 'phd'."""
    t = title or ""
    d = description or ""
    # Only treat as internship when the title itself is an internship
    # (avoids "certificates from internships" in PhD application lists)
    if _INTERN_TITLE_RE.search(t) and not re.search(r"\bstage\s+leader\b", t, re.I):
        return "other"
    if _EXPLICIT_PHD_TITLE_RE.search(t):
        return "phd"
    if _NON_PHD_TITLE_RE.search(t):
        return "job"
    if re.search(r"\b(ph\.?\s*d\.?|doctoral|doctorate)\b", t, re.I):
        return "phd"
    if _PHD_BODY_OFFER_RE.search(d):
        return "phd"
    return "job"
