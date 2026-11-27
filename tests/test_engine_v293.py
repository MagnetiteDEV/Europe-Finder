"""Comprehensive offline test suite for Europe-Finder engine v2.9.3."""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

# Provide a minimal feedparser stub only if running in an environment
# without feedparser installed (e.g. air-gapped CI/sandbox).
if "feedparser" not in sys.modules:
    try:
        import feedparser  # noqa: F401
    except ImportError:
        _fp = types.ModuleType("feedparser")
        _fp.parse = lambda raw: types.SimpleNamespace(entries=[])
        sys.modules["feedparser"] = _fp

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.adapters import FoundPosting
from engine.adapters import (
    academictransfer,
    ats,
    campusfrance_phd,
    crossref,
    daad,
    euraxess,
    fashionunited,
    jobbnorge,
    jobs_ac_uk,
    nordic_arts,
    orcid,
    pageup,
)
from engine.curated import load_all as load_curated
from engine.extract import clean_plain_text, detect_kind, extract_country, extract_deadline
from engine.funding import classify_funding
from engine.http import SourceBlocked
from engine.ingest import apply_policy, cross_source_dedupe, normalize
from engine.match import score_posting


class _FakeResp:
    def __init__(self, text="", json_data=None, status_code=200, headers=None):
        self.text = text
        self.content = text.encode("utf-8")
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        if self._json is not None:
            return self._json
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestExtractAndFunding(unittest.TestCase):
    def test_clean_plain_text_arthist_and_html(self):
        raw = "Apply &nbsp; at info document.write(String.fromCharCode(32 + 32)) [at] darthist.at<br/>Line 2 &amp; more"
        cleaned = clean_plain_text(raw)
        self.assertNotIn("document.write", cleaned)
        self.assertNotIn("&nbsp;", cleaned)
        self.assertNotIn("<br", cleaned)
        self.assertIn("info@darthist.at", cleaned)
        self.assertIn("Line 2 & more", cleaned)

    def test_extract_deadlines_multilingual(self):
        self.assertEqual(extract_deadline("Application deadline: 15 December 2026."), "2026-12-15")
        self.assertEqual(extract_deadline("Bewerbungsschluss: 3. Januar 2027"), "2027-01-03")
        self.assertEqual(extract_deadline("Date limite: 20 février 2027"), "2027-02-20")

    def test_detect_kind_title_first(self):
        # Faculty jobs that require a PhD in description must stay 'job'
        self.assertEqual(
            detect_kind("Lecturer in Creative Writing", "Candidates should have a PhD in Creative Writing."),
            "job",
        )
        self.assertEqual(
            detect_kind("Stage Leader MA Character Animation", "Lead an animation stage."),
            "job",
        )
        # Real PhD offers (including German Dissertation positions) must be 'phd'
        self.assertEqual(
            detect_kind("History of Art MPhil/PhD", "Undertake original doctoral research."),
            "phd",
        )
        self.assertEqual(
            detect_kind(
                "2 Stellen als Wissenschaftliche*r Mitarbeiter*in (TV-L E13)",
                "Aufgaben: Verfassen einer Dissertation im Bereich Kulturwissenschaft.",
            ),
            "phd",
        )
        # Mentioning 'internships' in application requirements must NOT turn a PhD into 'other'
        self.assertEqual(
            detect_kind("Doctoral Researcher in Art History", "Include certificates from internships."),
            "phd",
        )
        # Actual internship title -> 'other'
        self.assertEqual(detect_kind("Museum Curatorial Internship", "6 months"), "other")

    def test_strict_funding_rules(self):
        # Strict rule: bare scholarship/stipend/funded -> funding_unconfirmed
        cat, _, _ = classify_funding("PhD Fellowship", "Includes scholarship and monthly stipend.")
        self.assertEqual(cat, "funding_unconfirmed")

        cat, _, _ = classify_funding("PhD in Fashion Studies", "Fully funded 3-year studentship.")
        self.assertEqual(cat, "fully_funded_scholarship")

        for phrase in ["TV-L E13", "Contrat Doctoral", "CAO NU", "MSCA Doctoral Network", "employment contract"]:
            cat, _, _ = classify_funding("PhD Position", f"Funded under {phrase}.")
            self.assertEqual(cat, "salaried_doctoral_employment", msg=phrase)

        cat, _, flags = classify_funding("Visiting Researcher (unfunded position)", "No funding provided.")
        self.assertEqual(cat, "unfunded")
        self.assertTrue(flags)

    def test_extract_country_cities(self):
        self.assertEqual(extract_country("Birmingham"), "GB")
        self.assertEqual(extract_country("Camperdown Campus"), "AU")
        self.assertEqual(extract_country("Freiburg"), "DE")
        self.assertEqual(extract_country("Roubaix"), "FR")


class TestArtisticMatcher(unittest.TestCase):
    def _score(self, title, desc="", org="", source="jobsacuk"):
        p = FoundPosting(source=source, external_id="1", title=title, organization=org, description=desc)
        score_posting(p)
        return p

    def test_norwegian_artistic_titles_score(self):
        # v2.9.4: Jobbnorge titles are Norwegian bare nouns — the matcher
        # must see "kunst", "musikk", "teater" as artistic, not score 0.
        p_kunst = self._score("Stipendiat i kunst og kultur i skolen, med fokus på drama og teater",
                              "Universitetet i Stavanger", source="jobbnorge")
        self.assertFalse(p_kunst.excluded)
        self.assertGreaterEqual(p_kunst.fit_score, 45)

        p_musikk = self._score("Stipendiat i musikk", "NTNU", source="jobbnorge")
        self.assertFalse(p_musikk.excluded)
        self.assertGreaterEqual(p_musikk.fit_score, 45)

        p_ark = self._score("Stipendiat i forhistorisk arkeologi",
                            "Universitetet i Stavanger", source="jobbnorge")
        self.assertFalse(p_ark.excluded)

        # ...while a Norwegian engineering PhD still scores 0
        p_solar = self._score("PhD Research Fellow in Design and Analysis of Floating Solar Arrays",
                              "Universitetet i Agder", source="jobbnorge")
        self.assertEqual(p_solar.fit_score, 0)

    def test_stem_and_false_positives_rejected(self):
        # Chemistry / Food LCA without artistic context must NOT score Strong
        p_food = self._score(
            "Casual Research Officer (Food Process Modelling and Consequential LCA)",
            "Qld Alliance for Agriculture and Food Innovation",
            source="ats:workday",
        )
        self.assertTrue(p_food.excluded)
        self.assertLessEqual(p_food.fit_score, 15)

        p_photo = self._score(
            "Doctoral Researcher in Photocatalysts for Circular Economy",
            "Photocatalytic water splitting and life cycle assessment.",
            source="phdgermany",
        )
        self.assertTrue(p_photo.excluded)
        self.assertLessEqual(p_photo.fit_score, 15)

        # French engineering degrees in textile chemistry/engineering excluded
        p_ing = self._score(
            "Diplôme d'ingénieur de l'Institut textile et chimique de Lyon",
            "Level: M2 Field: Chemistry, Fashion",
            source="campusfrance",
        )
        self.assertTrue(p_ing.excluded)

        # Full-stack software role stating fashion/textile is not essential -> excluded
        p_dev = self._score(
            "Innovation Associate – Design For Recycling Project",
            "Full-stack experience in TypeScript, Node.js and PostgreSQL. "
            "Experience in fashion, textiles, sustainability would be beneficial but is not essential.",
            org="University of the Arts London",
            source="ats:wp",
        )
        self.assertTrue(p_dev.excluded)

        # False friends: Grounds Operative ("craft practices"), Impact Officer ("tailoring messages"), Retail sales
        p_grounds = self._score("Grounds Operative", "Learn new techniques and craft practices on grass pitches.")
        self.assertEqual(p_grounds.fit_score, 0)

        p_impact = self._score("Impact Officer: Policy Modelling for Health", "Tailoring messages to audiences.")
        self.assertEqual(p_impact.fit_score, 0)

        p_sales = self._score("Seasonal Sales Associate", "Work in a luxury fashion store. Value chain goals.")
        self.assertLessEqual(p_sales.fit_score, 15)

    def test_authentic_artistic_postings_score_high(self):
        p_art = self._score("History of Art MPhil/PhD", "Doctoral research in History of Art.", org="University of Warwick")
        self.assertFalse(p_art.excluded)
        self.assertGreaterEqual(p_art.fit_score, 70)

        p_ual = self._score("Senior Lecturer and Course Leader MA Illustration", "Camberwell College of Arts.", org="University of the Arts London", source="ats:wp")
        self.assertFalse(p_ual.excluded)
        self.assertGreaterEqual(p_ual.fit_score, 70)

        p_cumulus = self._score("Associate Professor in Design", "Northumbria University School of Design", org="Northumbria University", source="cumulus")
        self.assertFalse(p_cumulus.excluded)
        self.assertGreaterEqual(p_cumulus.fit_score, 70)

        p_ensci = self._score("designer textile", "Level: M2 Field: Design", org="ENSCI Les Ateliers", source="campusfrance")
        self.assertFalse(p_ensci.excluded)
        self.assertGreaterEqual(p_ensci.fit_score, 70)

        p_freiburg = self._score(
            "2 Stellen (TV-L E13) in Literatur- und Kulturwissenschaft",
            "Verfassen einer Dissertation im Bereich Kulturwissenschaft.",
            org="Universität Freiburg",
            source="phdgermany",
        )
        self.assertFalse(p_freiburg.excluded)
        self.assertGreaterEqual(p_freiburg.fit_score, 70)


class TestNewAndUpgradedAdapters(unittest.TestCase):
    def test_academictransfer_api_and_html_fallback(self):
        api_json = {
            "results": [{
                "id": 99101,
                "title": "PhD Position in Fashion Studies and Visual Culture",
                "organisation": {"name": "University of Amsterdam"},
                "city": "Amsterdam",
                "url": "/en/jobs/99101/phd-fashion/",
                "description": "<p>4-year salaried PhD under CAO NU.</p>",
                "end_date": "2027-02-15",
            }]
        }
        sess = mock.MagicMock()
        sess.get.return_value = _FakeResp(json_data=api_json)
        with mock.patch("time.sleep"):
            posts = academictransfer.search(sess, {"keywords": ["fashion"], "delay_seconds": 0})
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].country, "NL")
        self.assertEqual(posts[0].kind, "phd")
        self.assertEqual(posts[0].deadline, "2027-02-15")

        # HTML fallback when API returns non-JSON
        html = '<a href="/en/jobs/88202/phd-art-history/">PhD Candidate in Art History &amp; Museum Studies</a>'
        posts_html = academictransfer._parse_html_page(html)
        self.assertEqual(len(posts_html), 1)
        self.assertEqual(posts_html[0].external_id, "88202")
        self.assertEqual(posts_html[0].kind, "phd")

        # v2.9.4: real cards use an EMPTY overlay anchor; the title lives in
        # the <h3> and the summary in the <p> that follow it in the card.
        card = ('<article><a href="/en/jobs/365814/phd-position-in-applied-topology/" '
                'class="absolute inset-0"><!--[--><!--]--></a><div><h3>PhD Position In Applied Topology</h3>'
                '<p>Do you have an inquisitive mind and a passion for Mathematics?</p></div></article>')
        posts_card = academictransfer._parse_html_page(card)
        self.assertEqual(len(posts_card), 1)
        self.assertEqual(posts_card[0].external_id, "365814")
        self.assertEqual(posts_card[0].title, "PhD Position In Applied Topology")
        self.assertIn("Mathematics", posts_card[0].description)

    def test_jobbnorge_api_parser_and_block(self):
        payload = {"jobs": [
            {"id": 311685, "title": "PhD Research Fellow in maps and models for nature in land-use planning",
             "employer": "Høgskulen på Vestlandet", "department": "Faculty of Art",
             "deadline": "03.01.2027", "link": "https://www.jobbnorge.no/ledige-stillinger/stilling/311685",
             "summary": "PhD Research Fellow in Artistic Research and visual culture.",
             "publicationDate": "2026-11-20",
             "locations": [{"municipality": "Bergen", "area": "Bergen", "isPrimary": True}]},
            {"id": 308700, "title": "Sykepleier til Gatehospitalet",
             "employer": "Frelsesarmeen", "deadline": "Løpende",
             "link": "https://www.jobbnorge.no/ledige-stillinger/stilling/308700",
             "summary": "søker sykepleier", "publicationDate": "2026-11-19",
             "locations": [{"municipality": "Bergen", "isPrimary": True}]},
            {"id": 310606, "title": "Stipendiat i forhistorisk arkeologi",
             "employer": "Universitetet i Stavanger", "deadline": "23.12.2026",
             "link": "https://www.jobbnorge.no/ledige-stillinger/stilling/310606",
             "summary": "Stipendiat i arkeologi og kulturarv.",
             "publicationDate": "2026-11-18",
             "locations": [{"municipality": "Stavanger", "isPrimary": True}]},
        ]}
        posts = jobbnorge._parse_api(payload)
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].country, "NO")
        self.assertEqual(posts[0].kind, "phd")
        self.assertEqual(posts[0].deadline, "2027-01-03")
        self.assertEqual(posts[1].deadline, "2026-12-23")
        self.assertEqual(jobbnorge._parse_deadline("Løpende"), "")

        # Verify SourceBlocked (429) stops immediately with a single call
        sess = mock.MagicMock()
        sess.get.return_value = _FakeResp(status_code=429)
        posts_blocked = jobbnorge.search(sess, {"keywords": ["PhD art", "PhD design"], "delay_seconds": 0})
        self.assertEqual(posts_blocked, [])
        self.assertEqual(sess.get.call_count, 1)

    def test_myscience_disabled_in_config(self):
        # myScience.ch is behind a verify-wall (all requests time out);
        # the source stays disabled until a browser/API route exists.
        # Campus France Doctorat likewise has no public API (session-driven
        # listing, verified 2026-11-25) and stays disabled.
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["sources"]["myscience"]["enabled"])
        self.assertFalse(cfg["sources"]["campusfrance_phd"]["enabled"])

    def test_campusfrance_phd_parser(self):
        html = '<div class="card"><a href="/phd/offers/45123">Thèse en histoire de la mode et culture visuelle</a><span>Contrat doctoral — Date limite: 30 mars 2027</span></div>'
        posts = campusfrance_phd._parse_offers(html)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].country, "FR")
        self.assertEqual(posts[0].kind, "phd")
        self.assertEqual(posts[0].deadline, "2027-03-30")

    def test_nordic_arts_myscience_and_ku_phd(self):
        mysci_html = '<a href="/jobs/id65432-phd_art_history">PhD Position in Art History and Curatorial Studies</a>'
        m_posts = nordic_arts._parse_myscience(mysci_html)
        self.assertEqual(len(m_posts), 1)
        self.assertEqual(m_posts[0].country, "CH")
        self.assertEqual(m_posts[0].kind, "phd")

        # all-vacancies table rows: bare DD-MM-YYYY deadline cell, and a
        # Research Assistant row whose PhD marker must not classify it.
        ku_html = (
            '<a href="/all-vacancies/?show=171284">PhD position in Geoscience '
            'Education Research</a></td><td>Faculty of Science</td>'
            '<td>Department of Science Education</td><td>29-11-2026</td>'
            '<a href="/all-vacancies/?show=171285">Research Assistant with '
            'opportunity for PhD-fellowship continuation</a></td>'
            '<td>Faculty of Health and Medical Sciences</td>'
            '<td>Department of Biomedical Sciences</td><td>29-11-2026</td>'
        )
        k_posts = nordic_arts._parse_ku_phd(ku_html)
        self.assertEqual(len(k_posts), 1)
        self.assertEqual(k_posts[0].country, "DK")
        self.assertEqual(k_posts[0].kind, "phd")
        self.assertEqual(k_posts[0].deadline, "2026-11-29")
        self.assertTrue(nordic_arts.KU_PHD_URL.endswith("/all-vacancies/"))

    def test_euraxess_r1_parser(self):
        html = """
        <article class="ecl-content-item">
          <ul class="ecl-content-block__primary-meta-container">
            <li class="ecl-content-block__primary-meta-item">University of Copenhagen</li>
            <li class="ecl-content-block__primary-meta-item">Posted on: 20 November 2026</li>
            <li class="ecl-content-block__secondary-meta-item">Application Deadline: 15 January 2027</li>
            <li class="ecl-content-block__secondary-meta-item">Denmark</li>
          </ul>
          <a class="ecl-link--standalone" href="/jobs/399999"><span>PhD Fellowship in Fashion Sustainability</span></a>
          <div class="ecl-content-block__description"><p>Salaried doctoral employment in Copenhagen.</p></div>
        </article>
        """
        posts = euraxess._parse_page(html, force_phd=True)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].country, "DK")
        self.assertEqual(posts[0].deadline, "2027-01-15")
        self.assertEqual(posts[0].kind, "phd")

    def test_euraxess_blocked_facet_falls_through_to_safety_net(self):
        card_html = """
        <article class="ecl-content-item">
          <ul class="ecl-content-block__primary-meta-container">
            <li class="ecl-content-block__primary-meta-item">University of Copenhagen</li>
            <li class="ecl-content-block__primary-meta-item">Posted on: 20 November 2026</li>
            <li class="ecl-content-block__secondary-meta-item">Denmark</li>
          </ul>
          <a class="ecl-link--standalone" href="/jobs/399998"><span>PhD Fellowship in Fashion Sustainability</span></a>
          <div class="ecl-content-block__description"><p>Salaried doctoral employment in Copenhagen.</p></div>
        </article>
        """

        def fake_get(url, params=None, timeout=None, headers=None):
            if params:
                return _FakeResp(status_code=403)
            return _FakeResp(text=card_html)

        sess = mock.MagicMock()
        sess.get.side_effect = fake_get
        posts = euraxess.search(sess, {"delay_seconds": 0, "pages": 1})
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].external_id, "399998")

    def test_jobs_ac_uk_stem_prereject_and_polite_delay(self):
        self.assertFalse(jobs_ac_uk._title_matches("PhD in Mechanical Engineering", phd_mode=True))
        self.assertFalse(jobs_ac_uk._title_matches("UX Designer", phd_mode=False))
        self.assertTrue(jobs_ac_uk._title_matches("PhD Studentship in Fashion Studies", phd_mode=True))

    def test_ats_workday_country_and_kuleuven_direct_url(self):
        sess = mock.MagicMock()
        sess.post.return_value = _FakeResp(json_data={
            "total": 1,
            "jobPostings": [{
                "title": "Doctoral Researcher in Fashion Design",
                "externalPath": "/job/Otaniemi/Doctoral-Researcher_R99999",
                "locationsText": "Otaniemi",
                "bulletFields": ["R99999"],
            }],
        })
        w = ats.fetch_workday(sess, {
            "name": "Aalto University",
            "country": "FI",
            "endpoint": "https://aalto.wd3.myworkdayjobs.com/wday/cxs/aalto/aalto/jobs",
        })
        self.assertEqual(w[0].country, "FI")

        sess.post.return_value = _FakeResp(json_data={
            "hits": [{
                "_source": {
                    "id": "60785545",
                    "orgUnitDescription": "History, Faculty of Arts",
                    "city": "Gent",
                    "applyBefore": "20270115",
                    "posting": {"title": "PhD in Art History", "teaser": "Doctoral position."},
                }
            }]
        })
        ku = ats.fetch_kuleuven(sess, {"country": "BE", "careers_url": "https://example.org", "endpoint": "https://example.org/search"})
        self.assertEqual(ku[0].url, "https://www.kuleuven.be/personeel/jobsite/jobs/60785545?lang=en")
        self.assertTrue(ku[0].organization.startswith("KU Leuven"))

    def test_ats_blocked_tenant_does_not_stop_other_tenants(self):
        def blocked(session, tenant):
            raise SourceBlocked("403 from blocked tenant")

        def ok(session, tenant):
            return [FoundPosting(source="ats:varbi", external_id="v1",
                                 title="PhD in Visual Culture",
                                 organization="Lund University")]

        tenants = [
            {"ats": "workday", "name": "Blocked University", "verified": True,
             "endpoint": "https://example.org/wday/cxs/x/x/jobs"},
            {"ats": "varbi", "name": "Lund University", "verified": True,
             "endpoint": "https://example.org/varbi"},
        ]
        with tempfile.TemporaryDirectory() as td:
            tenants_file = Path(td) / "tenants.json"
            tenants_file.write_text(json.dumps(tenants), encoding="utf-8")
            with mock.patch.dict(ats.FETCHERS, {"workday": blocked, "varbi": ok}):
                posts = ats.search(mock.MagicMock(),
                                   {"tenants_file": str(tenants_file),
                                    "delay_seconds": 0})
        self.assertEqual([p.source for p in posts], ["ats:varbi"])

    def test_fashionunited_uk_city_overrides_company_hq(self):
        d = {
            "title": "Seasonal Sales Assistant",
            "hiringOrganization": {"name": "PANDORA"},
            "jobLocation": {"address": {"addressLocality": "Birmingham", "addressCountry": ""}},
            "description": "Rate £13.25. Headquartered in Copenhagen, Denmark.",
        }
        p = fashionunited._from_detail("https://fashionunited.uk/fashion-jobs/x-123", "123", d)
        self.assertEqual(p.country, "GB")


class TestCuratedAndPipeline(unittest.TestCase):
    def test_curated_loads_all_three_kinds(self):
        items = load_curated()
        by_kind = {}
        for it in items:
            by_kind[it.kind] = by_kind.get(it.kind, 0) + 1
            self.assertTrue(it.url.startswith("https://"), msg=it.external_id)
            self.assertTrue(it.curated)
        self.assertEqual(by_kind.get("phd"), 14)
        self.assertEqual(by_kind.get("master"), 7)
        self.assertEqual(by_kind.get("scholarship"), 9)

    def test_cross_source_dedupe(self):
        p1 = FoundPosting(source="jobsacuk", external_id="1", title="Lecturer in Visual Culture",
                          organization="University of the Arts London, LCF", description="Long desc " * 20, deadline="2026-12-01")
        p2 = FoundPosting(source="ats:wp", external_id="2", title="Lecturer in Visual Culture",
                          organization="University of the Arts London", description="Short", deadline="")
        deduped = cross_source_dedupe([p1, p2])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].also_in, ["ats:wp"])


    def test_degraded_run_guard_and_hollow_bundle_guard(self):
        from engine import export_live, ingest
        # Test _is_not_expired
        self.assertTrue(ingest._is_not_expired({"deadline": "2099-01-01"}))
        self.assertTrue(ingest._is_not_expired({"deadline": ""}))
        self.assertFalse(ingest._is_not_expired({"deadline": "2020-01-01"}))

        # Test professor degraded-run guard preserves previous 15 profs when live returns 2
        prev_profs = [{"name": f"Prof {i}", "fit_score": 70, "sources": ["crossref"]} for i in range(15)]
        with tempfile.TemporaryDirectory() as td:
            old_data = ingest.DATA
            ingest.DATA = Path(td)
            try:
                sess = mock.MagicMock()
                cfg = {"politeness": {"delay_seconds": 0}, "professors": {"orcid": {"enabled": False}, "crossref": {"enabled": False}}}
                kept = ingest.collect_professors(sess, cfg, prev_profs=prev_profs)
                self.assertEqual(len(kept), 15)
            finally:
                ingest.DATA = old_data

        # Test hollow-bundle guard in export_live refuses >50% drop
        with tempfile.TemporaryDirectory() as td:
            out_js = Path(td) / "eof-live.js"
            prev_bundle = {"postings": [{"id": i} for i in range(100)]}
            out_js.write_text("window.__EOF_LIVE__ = " + json.dumps(prev_bundle) + ";\n", encoding="utf-8")
            with mock.patch.object(export_live, "build_bundle", return_value={"postings": [{"id": 1}]}), \
                 mock.patch.object(sys, "argv", ["export_live", str(out_js)]):
                with self.assertRaises(SystemExit) as ctx:
                    export_live.main()
                self.assertEqual(ctx.exception.code, 1)
            # Previous healthy bundle untouched
            self.assertEqual(export_live._previous_count(out_js), 100)

    def test_ats_subtype_degraded_guard_restores_missing_subtype(self):
        from engine import ingest
        posts = [FoundPosting(source="ats:varbi", external_id="v1",
                              title="Fresh Varbi PhD", organization="Lund University",
                              deadline="2099-01-01")]
        prev = [
            {"source": "ats:workday", "external_id": "w1", "title": "Old Workday PhD",
             "organization": "Aalto University", "deadline": "2099-01-01"},
            {"source": "ats:workday", "external_id": "w-expired", "title": "Expired Workday PhD",
             "organization": "Aalto University", "deadline": "2020-01-01"},
            {"source": "ats:varbi", "external_id": "v0", "title": "Old Varbi PhD",
             "organization": "Lund University", "deadline": "2099-01-01"},
        ]
        warnings = ingest._apply_degraded_guards(
            posts, prev, ["ats"], {"ats": 1}, {"ats:varbi": 1}, "test bundle")
        keys = {(p.source, p.external_id) for p in posts}
        self.assertIn(("ats:workday", "w1"), keys)
        self.assertNotIn(("ats:workday", "w-expired"), keys)
        self.assertNotIn(("ats:varbi", "v0"), keys)
        self.assertTrue(any("ats:workday" in w for w in warnings))

    def test_daad_block_reason_reaches_bundle_warning(self):
        from engine import ingest
        # DAAD adapters must not swallow SourceBlocked: ingest records
        # the reason and the degraded guard puts it in the warning.
        with mock.patch.object(daad, "polite_get",
                               side_effect=SourceBlocked("403 from https://www2.daad.de")):
            with self.assertRaises(SourceBlocked):
                daad.search(mock.MagicMock(), {"delay_seconds": 0})
            with self.assertRaises(SourceBlocked):
                daad.search_phd(mock.MagicMock(), {})
        posts = []
        prev = [{"source": "daad", "external_id": "d1", "title": "Old DAAD programme",
                 "organization": "DAAD", "deadline": "2099-01-01"}]
        warnings = ingest._apply_degraded_guards(
            posts, prev, ["daad"], {"daad": 0}, {},
            "test bundle", {"daad": "403 from https://www2.daad.de"})
        self.assertEqual(len(posts), 1)
        self.assertTrue(any("403 from https://www2.daad.de" in w for w in warnings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
