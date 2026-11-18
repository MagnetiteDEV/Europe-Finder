"""Lightweight extraction: deadlines, countries, funding signals."""
from __future__ import annotations

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
}

_DEADLINE_HINT = re.compile(
    r"(deadline|closing date|apply by|applications? (?:close|due)|"
    r"deadline for application|submission deadline|"
    r"bewerbungsschluss|bewerbungsfrist|einsendeschluss)", re.I)
_DATE1 = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_DATE1B = re.compile(r"(\d{1,2})\.\s+([A-Za-zäöüÄÖÜ]+)\s+(\d{4})")
_DATE2 = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATE3 = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")


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
    "denmark": "DK", "danmark": "DK", "copenhagen": "DK", "finland": "FI",
    "suomi": "FI", "helsinki": "FI", "austria": "AT", "österreich": "AT",
    "vienna": "AT", "wien": "AT", "switzerland": "CH", "schweiz": "CH",
    "zurich": "CH", "zürich": "CH", "poland": "PL", "polska": "PL",
    "czech": "CZ", "czechia": "CZ", "prague": "CZ", "praha": "CZ",
    "hungary": "HU", "budapest": "HU", "greece": "GR", "athens": "GR",
    "croatia": "HR", "romania": "RO", "bulgaria": "BG", "estonia": "EE",
    "latvia": "LV", "lithuania": "LT", "slovenia": "SI", "slovakia": "SK",
    # v2.9: Australia (Workday/PageUp tenants) + art-school cities.
    # Order matters: dict iteration is first-match, so "scotland"
    # (above) still wins for "Perth, Scotland" over "perth" -> AU.
    # Bare "newcastle" is deliberately absent (UK/AU ambiguity); use
    # the "newcastle nsw" form. "victoria" is absent for the same reason.
    "australia": "AU", "melbourne": "AU", "sydney": "AU", "brisbane": "AU",
    "perth": "AU", "adelaide": "AU", "canberra": "AU", "hobart": "AU",
    "geelong": "AU", "wollongong": "AU", "gold coast": "AU",
    "queensland": "AU", "new south wales": "AU", "nsw": "AU",
    "western australia": "AU", "south australia": "AU", "tasmania": "AU",
    "australian capital territory": "AU", "newcastle nsw": "AU",
    "clayton": "AU", "caulfield": "AU", "parkville": "AU",
    "burwood": "AU", "waurn ponds": "AU", "warrnambool": "AU",
    "st lucia campus": "AU", "st kilda road": "AU", "peninsula campus": "AU",
    "espoo": "FI", "hanoi": "VN", "ho chi minh": "VN",
    "glasgow": "GB", "edinburgh": "GB", "dublin": "IE",
    "florence": "IT", "florenz": "IT", "rome": "IT", "roma": "IT",
    "turin": "IT", "torino": "IT", "naples": "IT", "napoli": "IT",
    "rotterdam": "NL", "eindhoven": "NL", "utrecht": "NL",
    "ghent": "BE", "gent": "BE", "antwerp": "BE", "leuven": "BE",
    "oslo": "NO", "bergen": "NO", "trondheim": "NO",
    "gothenburg": "SE", "göteborg": "SE", "aarhus": "DK", "odense": "DK",
    "hamburg": "DE", "munich": "DE", "münchen": "DE", "cologne": "DE",
    "köln": "DE", "stuttgart": "DE", "dresden": "DE", "leipzig": "DE",
    "barcelona": "ES", "madrid": "ES", "valencia": "ES", "porto": "PT",
    "lyon": "FR", "marseille": "FR", "bordeaux": "FR", "lille": "FR",
    "nantes": "FR", "strasbourg": "FR",
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


_PHD_RE = re.compile(
    r"\b(ph\.?\s?d\.?|doctoral|doctorate|doctorant|doktorand|doktorandin)\b",
    re.I)
_INTERN_RE = re.compile(r"\b(intern|internship|internships|praktikum|praktikant)\b", re.I)


def detect_kind(title: str, description: str) -> str:
    """phd | job | other. Used so the strict funded-only default applies
    to doctoral positions, while university job adverts (implicitly
    salaried employment) are only excluded when explicitly unfunded."""
    text = f"{title or ''}\n{description or ''}"
    if _INTERN_RE.search(text):
        return "other"
    if _PHD_RE.search(text):
        return "phd"
    return "job"
