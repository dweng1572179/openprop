"""List Builder — area search + local filters + MapLibre pins + saved searches +
export. The provider returns a coarse area set; filter_engine refines it; results
double as map pins (GeoJSON) and export rows. Export re-runs from the filters
(no server-side result-set state to keep)."""
import json

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, Response
from starlette.datastructures import FormData

from . import db, registry, services
from .app import app, require_auth, templates
from .cache import BudgetExceeded, budget_remaining_cents, spend_this_month
from .config import settings
from .export import to_csv, to_xlsx
from .models import SearchFilters

_INT = {"beds_min", "baths_min", "year_built_min", "year_built_max", "building_sqft_min",
        "lot_sqft_min", "value_min", "value_max", "assessed_value_min", "equity_pct_min",
        "years_owned_min", "median_income_min", "limit"}
_BOOL = {"absentee", "out_of_state", "owner_occupied", "corporate_owned", "high_equity",
         "tax_delinquent", "vacant", "pre_foreclosure"}
_STR = {"state", "county", "city", "zip", "property_type"}


def _filters_from_form(form: FormData) -> SearchFilters:
    data: dict = {}
    for k in _STR:
        v = (form.get(k) or "").strip()
        if v:
            data[k] = v
    for k in _INT:
        v = (form.get(k) or "").strip()
        if v:
            try:
                data[k] = int(v)
            except ValueError:
                pass
    for k in _BOOL:
        v = form.get(k)
        if v in ("true", "false"):
            data[k] = v == "true"
    return SearchFilters(**data)


def _geojson(results) -> str:
    feats = [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [r.lng, r.lat]},
         "properties": {"address": r.address, "value": r.market_value}}
        for r in results if r.lat and r.lng
    ]
    # escape "</" so a provider address containing "</script>" can't break out of
    # the <script type="application/json"> block it's embedded in (XSS).
    return json.dumps({"type": "FeatureCollection", "features": feats}).replace("</", "<\\/")


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, _=Depends(require_auth)):
    return templates.TemplateResponse("search.html", {
        "request": request,
        "saved": db.list_saved_searches(),
        "parcel_tiles": _parcel_tiles(),
        "spend_cents": spend_this_month(),
        "budget_cents": settings.monthly_budget_cents,
        "remaining_cents": budget_remaining_cents(),
    })


@app.post("/search", response_class=HTMLResponse)
async def search_run(request: Request, _=Depends(require_auth)):
    f = _filters_from_form(await request.form())
    try:
        results = services.search(f)
    except Exception as e:  # noqa: BLE001
        return templates.TemplateResponse("_error.html", {"request": request, "msg": str(e)})
    return templates.TemplateResponse("_results.html", {
        "request": request, "results": results, "geojson": _geojson(results),
        "filters_json": f.model_dump_json(),
    })


@app.post("/export")
async def export(request: Request, _=Depends(require_auth)):
    form = await request.form()
    fmt = form.get("fmt", "csv")
    f = _filters_from_form(form)
    try:
        results = services.search(f)
    except Exception as e:  # noqa: BLE001 — return the error as text, not a raw 500
        return Response(f"Export failed: {e}", status_code=400, media_type="text/plain")
    if fmt == "xlsx":
        return Response(
            to_xlsx(results),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=openprop.xlsx"},
        )
    return Response(to_csv(results), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=openprop.csv"})


# --- saved searches ----------------------------------------------------------

@app.post("/saved-searches", response_class=HTMLResponse)
async def saved_save(request: Request, _=Depends(require_auth)):
    form = await request.form()
    name = (form.get("name") or "Untitled").strip()
    f = _filters_from_form(form)
    db.save_saved_search(name, f.model_dump_json())
    return templates.TemplateResponse(
        "_saved_searches.html", {"request": request, "saved": db.list_saved_searches()}
    )


@app.post("/saved-searches/{search_id}/run", response_class=HTMLResponse)
def saved_run(request: Request, search_id: int, _=Depends(require_auth)):
    s = db.get_saved_search(search_id)
    if not s:
        return templates.TemplateResponse("_error.html", {"request": request, "msg": "Saved search not found."})
    f = SearchFilters.model_validate_json(s["filters_json"])
    try:
        results = services.search(f)
    except Exception as e:  # noqa: BLE001
        return templates.TemplateResponse("_error.html", {"request": request, "msg": str(e)})
    return templates.TemplateResponse("_results.html", {
        "request": request, "results": results, "geojson": _geojson(results),
        "filters_json": s["filters_json"],
    })


@app.delete("/saved-searches/{search_id}", response_class=HTMLResponse)
def saved_delete(request: Request, search_id: int, _=Depends(require_auth)):
    db.delete_saved_search(search_id)
    return templates.TemplateResponse(
        "_saved_searches.html", {"request": request, "saved": db.list_saved_searches()}
    )


def _parcel_tiles() -> str | None:
    """Regrid vector-tile URL for the parcel overlay, if configured.

    A token is necessary but NOT sufficient: Regrid sells the API key free and the
    parcel DATA by subscription. An unlicensed account authenticates fine (HTTP 200)
    and returns an empty FeatureCollection everywhere, and its tiles come back 204 —
    so the overlay just draws nothing. If parcels don't appear, check coverage on the
    Regrid account before suspecting this code.
    """
    try:
        from .providers.regrid import RegridProvider
        if settings.regrid_api_token:
            return RegridProvider().tile_url()
    except Exception:  # noqa: BLE001 — overlay is optional
        pass
    return None
