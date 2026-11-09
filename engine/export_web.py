"""Inline the latest data into the PWA so it works from file://
with zero server: writes app/data/data.js.

Only non-personal data is exported: the candidate profile itself
(profile.json) NEVER leaves the project directory.

Usage:  .venv/bin/python -m engine.export_web   (from project root)
"""
from __future__ import annotations

import json
from pathlib import Path

from .funding import FA_LABEL as FUNDING_FA
from .vocab import FIELD_GROUPS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
APP_DATA = ROOT / "app" / "data"
VERSION = "v2.1"


def build_bundle() -> dict:
    """Assemble the data bundle shared by all web exports (PWA + live)."""
    postings = json.loads((DATA / "postings.json").read_text(encoding="utf-8")) \
        if (DATA / "postings.json").exists() else {"meta": {}, "postings": []}
    digest = json.loads((DATA / "digest.json").read_text(encoding="utf-8")) \
        if (DATA / "digest.json").exists() else {"picks": []}
    policy = json.loads((ROOT / "policy.json").read_text(encoding="utf-8"))
    inst = json.loads((ROOT / "institutions.json").read_text(encoding="utf-8")) \
        if (ROOT / "institutions.json").exists() else {"meta": {}, "connected": []}
    profs = json.loads((DATA / "professors.json").read_text(encoding="utf-8")) \
        if (DATA / "professors.json").exists() else {"meta": {}, "professors": []}
    return {
        "version": VERSION,
        "meta": postings.get("meta", {}),
        "groups": [{"id": gid, "fa": fa}
                   for gid, (fa, _, _) in FIELD_GROUPS.items()],
        "funding_labels": FUNDING_FA,
        "funding_accepted": policy["funding"]["acceptedWhenFilterOn"],
        "priority_countries": policy.get("priorityCountries", []),
        "eligibility_labels": {
            "confirmed_eligible": "واجد شرایط بودن تأیید شده",
            "no_exclusion_found": "منع مشخصی یافت نشد (تأیید قطعی نیست)",
            "clarification_required": "نیازمند استعلام از دانشگاه/کارفرما",
            "restricted": "محدودیت رسمی اعلام شده",
            "insufficient_information": "اطلاعات کافی نیست",
        },
        "institutions": {
            "connected_count": inst["meta"].get("connected_count", 0),
            "prospect_count": inst["meta"].get("prospect_count", 0),
            "connected": [
                {"name": c["name"], "country": c["country"],
                 "city": c.get("city", ""), "ats": c["ats"],
                 "careers_url": c["careers_url"]}
                for c in inst.get("connected", [])
            ],
        },
        "postings": postings.get("postings", []),
        "professors": profs.get("professors", []),
        "digest": digest,
    }


def main() -> None:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle()
    js = ("window.EOF_DATA = " +
          json.dumps(bundle, ensure_ascii=False) + ";\n")
    (APP_DATA / "data.js").write_text(js, encoding="utf-8")
    print(f"exported {len(bundle['postings'])} postings -> app/data/data.js")


if __name__ == "__main__":
    main()
