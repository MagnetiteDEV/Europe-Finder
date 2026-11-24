# Europe-Finder

Live data feed for **Europe Opportunity Finder** (single-file iOS-friendly app).

- `docs/eof-live.js` — the published bundle (`window.__EOF_LIVE__ = {...}`),
  refreshed **daily at 09:30 Asia/Tehran** by GitHub Actions. Served via
  GitHub Pages: `https://magnetitedev.github.io/Europe-Finder/eof-live.js`
- `engine/` — the polite academic crawler (university ATS endpoints + Nature
  RSS + curated funding routes). User-Agent identifies it as personal academic
  research; it backs off on 429/403 and respects robots.txt.
- The app loads this file on every open with a `<script>` tag (JSONP-style),
  so live updates work even when the app is opened from the iOS Files app,
  where `fetch()` is blocked. If the network fails or the payload is invalid,
  the app falls back to its embedded snapshot.

No personal data is published here — only public job/scholarship postings.

## v2.9.4 Engine Fixes
- Jobbnorge rewritten on the site's public JSON API (`publicapi.jobbnorge.no/v3/jobs`): the old `/en/available-jobs` HTML listing 404s after the site moved to a JS app. One call returns the full list; the adapter filters PhD-marker titles with an arts signal (English + Norwegian terms) and parses `DD.MM.YYYY` deadlines.
- myScience.ch disabled in config: the site sits behind a verify-wall and every request times out from a plain HTTP client (even `/verify`) — it would burn ~90s per keyword in retries and return 0. The manual hub link stays; re-enable only with a browser/API route.
- Bundle version `v2.9.4` (`engine/export_web.py`).

## v2.9.3 Engine Highlights
- Expanded salaried/funded European PhD adapters: AcademicTransfer (NL), Jobbnorge (NO), Campus France Doctorat (FR), myScience.ch (CH), University of Copenhagen PhD (DK), plus targeted R1/Arts EURAXESS & PhD-first jobs.ac.uk queries and 14 curated European PhD routes (`data/phds.json`).
- Hardened artistic precision matcher (`engine/vocab.py`, `engine/match.py`, `engine/extract.py`) with STEM/engineering exclusions and false-friend guards.
- Universal per-source degraded-run guard + professor guard (`engine/ingest.py`) and polite delays across all adapters.
