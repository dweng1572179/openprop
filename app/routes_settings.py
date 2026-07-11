"""Settings page — paste API keys / pick providers in the browser; saved to the
DB and applied live (no restart). Secrets are never rendered back; a blank field
keeps the stored value."""
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from . import ai, registry, settings_store
from .app import app, require_auth, templates
from .cache import budget_remaining_cents, spend_this_month
from .config import settings
from .settings_store import FIELDS


def _fields_ctx() -> list[dict]:
    out = []
    for name, label, kind in FIELDS:
        cur = getattr(settings, name, "")
        f = {"name": name, "label": label, "kind": kind, "secret": kind == "secret"}
        if kind.startswith("select:"):
            f["options"] = kind.split(":", 1)[1].split(",")
        if kind == "secret":
            f["is_set"] = bool(cur)
        else:
            f["value"] = cur
        out.append(f)
    return out


def _status() -> list[dict]:
    """What's active right now, so the user can see keys took effect."""
    return [
        {"label": "Geocoding (Census)", "on": registry.geocoder() is not None, "note": "free"},
        {"label": "Flood zone (FEMA)", "on": True, "note": "free"},
        {"label": "Property + owner + value (RentCast/…)", "on": registry.property_provider() is not None,
         "note": "needs RENTCAST_API_KEY"},
        {"label": "Skip trace (contacts)", "on": registry.skiptrace_provider() is not None,
         "note": "needs a skip-trace vendor + key"},
        {"label": "Distress flags (RealEstateAPI)", "on": registry.distress_provider() is not None,
         "note": "paid unlock"},
        {"label": "Fair Market Rent (HUD)", "on": registry.fmr_provider() is not None, "note": "free token"},
        {"label": "Median income (Census ACS)", "on": bool(settings.census_api_key), "note": "free key"},
        {"label": "AI (search / brief / score / outreach)", "on": ai.available(),
         "note": "needs ANTHROPIC_API_KEY (rules fallback otherwise)"},
    ]


def _ctx(request: Request, saved: bool = False) -> dict:
    return {
        "request": request, "fields": _fields_ctx(), "status": _status(), "saved": saved,
        "spend_cents": spend_this_month(), "budget_cents": settings.monthly_budget_cents,
        "remaining_cents": budget_remaining_cents(),
    }


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _=Depends(require_auth)):
    return templates.TemplateResponse("settings.html", _ctx(request))


@app.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request, _=Depends(require_auth)):
    form = await request.form()
    updates: dict[str, str] = {}
    for name, _label, kind in FIELDS:
        v = (form.get(name) or "").strip()
        # selects always apply (blank = a valid "disabled" choice); for everything
        # else a blank field means "keep what's stored" (don't wipe keys/model/budget).
        if kind.startswith("select:"):
            updates[name] = v
        elif v:
            updates[name] = v
    settings_store.save(updates)
    return templates.TemplateResponse("settings.html", _ctx(request, saved=True))
