# OpenProp

Self-hosted, AI-native property intelligence — a bring-your-own-keys, own-it
alternative to the big property-data subscriptions. Free gov data first
(Census/HUD/FEMA), paid providers (RentCast, skip-trace, RealEstateAPI) only on
cache miss, everything cached so you never pay twice.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # just set OPENPROP_PASSWORD (a login password)
./run.sh                      # http://localhost:8787  (8000 is often taken)
```

`./run.sh` defaults to port **8787**; change it with `OPENPROP_PORT=9000 ./run.sh`.
Or with Docker (persists the cache in a volume): `docker compose up` (same port,
also honors `OPENPROP_PORT`).

Then open **http://localhost:8787**, log in, and go to **Settings** — paste your API
keys right in the browser and hit Save. They apply immediately (no restart, no file
editing), and the Settings page shows which capabilities are live. The only thing
that belongs in `.env` is `OPENPROP_PASSWORD` (and optionally `SECRET_KEY`); all
provider keys are managed from the dashboard.

Runs with **zero keys** on free Census geocoding + FEMA flood. Paste keys in
Settings to unlock, each optional:
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

Budget guardrail: the monthly paid-spend cap (also editable in Settings) refuses
paid calls past the cap and shows a running spend total.

## Checks

```bash
python -m tests.test_smoke     # end-to-end: auth + live geocode + card + notes + skiptrace + AI
python -m tests.test_rentcast  # RentCast field mapping (canned JSON)
python -m tests.test_export    # CSV / XLSX export
python -m app.flags            # computed-flag logic
python -m app.filter_engine    # local filter engine
python -m app.ai               # NL-parser rules fallback
```

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
