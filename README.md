# OpenProp

Self-hosted, AI-native property intelligence — a bring-your-own-keys, own-it
alternative to the big property-data subscriptions. Free gov data first
(Census/HUD/FEMA), paid providers (RentCast, skip-trace, RealEstateAPI) only on
cache miss, everything cached so you never pay twice.

## Run

Non-technical? Double-click **Start OpenProp** (`.command` on Mac, `.bat` on
Windows) — it builds the venv on first run and opens the browser. Docker is not
needed; Windows only needs Python from python.org. See `guide/` for the
illustrated walkthroughs.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # just set OPENPROP_PASSWORD (a login password)
./run.sh                      # http://localhost:8787  (8000 is often taken)
```

`./run.sh` defaults to port **8787**; change it with `OPENPROP_PORT=9000 ./run.sh`.
Docker is optional (`docker compose up` — same port, also honors `OPENPROP_PORT`,
and persists the cache in a volume); it buys nothing for a single local user.

Then open **http://localhost:8787**, log in, and go to **Settings** — paste your API
keys right in the browser and hit Save. They apply immediately (no restart, no file
editing), and the Settings page shows which capabilities are live. The only thing
that belongs in `.env` is `OPENPROP_PASSWORD` (and optionally `SECRET_KEY`); all
provider keys are managed from the dashboard.

Runs with **zero keys** on free Census geocoding + FEMA flood. Paste keys in
Settings to unlock, each optional. Note `PROPERTY_PROVIDER` (a Settings dropdown,
ships as `reapi`) must **match the key you paste** — a RentCast key with the
provider still on `reapi` yields "no property provider configured".
- **RealEstateAPI** — the list builder. Set `PROPERTY_PROVIDER=reapi` for this. Its
  area search is the only one that returns a workable lead on every row (owner,
  value, equity, loan balance, foreclosure/lien/probate/vacant), plus alt skip trace.
- **RentCast** — per-address detail + AVM/rent comps (free 50/mo). Good for single
  lookups; its *bulk* listing carries no value/equity/distress and is mostly blank
  rows in dense zips, so equity/distress filters match nothing when it backs search.
- **Skip-trace vendor** (BatchData, or an Apify actor — set `SKIPTRACE_PROVIDER=apify` + your `apify_api_...` token) — contact lookup (pay-per-hit)
- **Regrid** — parcel-boundary map overlay
- **HUD FMR / Census** — free FMR + median-income enrichment
- **Anthropic** — AI search / brief / lead score / outreach (rules-based NL fallback without it)

Budget guardrail: a monthly paid-spend cap refuses paid calls past the limit (free
data still works) and shows a running spend total in the header. **Adjust it anytime**
in the browser — **Settings → "Monthly paid-spend cap (cents)"** — and it applies
immediately, no restart. Set it to whatever you're comfortable spending.

## Checks

```bash
python -m tests.test_smoke     # end-to-end: auth + live geocode + card + notes + skiptrace + AI
python -m tests.test_rentcast  # RentCast field mapping (canned JSON)
python -m tests.test_export    # CSV / XLSX export
python -m tests.test_cache_db  # cache-as-hit / spend accounting / NULL-zip dedupe
python -m tests.test_providers # provider field mapping (canned JSON)
python -m app.flags            # computed-flag logic
python -m app.filter_engine    # local filter engine
python -m app.ai               # NL-parser rules fallback
```

Each test module sets its own env (temp DB, blank keys) at import, so run them
**one process at a time** — as above, or `pytest tests/test_smoke.py`. A single
`pytest tests` run imports every module first, and the first one to import wins
the config singleton, so the others get a DB and a password they didn't ask for.

## Sibling project

**[OpenLease](https://github.com/dweng1572179/openlease)** — the open, self-hosted
SpaceFinder: an AI-native commercial-real-estate leasing search over four metros (New
York, Miami, Los Angeles, Chicago). Same author, same architecture, adjacent domain —
runs keyless-first on port **8788**, so it and OpenProp (8787) can run side by side.

## Layout

```
app/
  app.py            FastAPI app, auth, home
  config.py         .env settings
  db.py             SQLite schema + persistence
  models.py         normalized PropertyRecord / SearchFilters / ContactRecord
  cache.py          cache-through + monthly budget guardrail
  flags.py          free computed distress/ownership flags
  filter_engine.py  local filter engine (the cheap filters)
  services.py       lookup orchestration (geocode → provider → enrich → flags)
  registry.py       capability → active provider (from .env)
  routes_*.py       feature routes, one per phase
  providers/        one file per data source behind base.py Protocols
  templates/        Jinja + HTMX + Tailwind(CDN) + MapLibre
```
