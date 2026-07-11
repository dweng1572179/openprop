"""Skip trace — the pay-per-hit owner-contact lookup. Two-step by design (spec
§8): the confirm route shows the estimated cost + remaining budget; only an
explicit POST spends. Never auto-traced. Results are PII, stored locally only."""
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from . import db, registry
from .app import app, require_auth, templates
from .cache import BudgetExceeded, budget_remaining_cents
from .config import settings


def _split_name(owner_name: str) -> tuple[str, str]:
    parts = (owner_name or "").split()
    if not parts:
        return "", ""
    return " ".join(parts[:-1]) or parts[0], parts[-1]


@app.get("/property/{property_id}/skiptrace/confirm", response_class=HTMLResponse)
def skiptrace_confirm(request: Request, property_id: int, _=Depends(require_auth)):
    ctx = {
        "request": request,
        "property_id": property_id,
        "existing": db.get_contact(property_id),
        "provider_ready": registry.skiptrace_provider() is not None,
        "cost_cents": settings.skiptrace_cost_cents,
        "remaining_cents": budget_remaining_cents(),
    }
    return templates.TemplateResponse("_skiptrace_confirm.html", ctx)


@app.post("/property/{property_id}/skiptrace", response_class=HTMLResponse)
def skiptrace_run(request: Request, property_id: int, _=Depends(require_auth)):
    provider = registry.skiptrace_provider()
    prop = db.get_property(property_id)
    if provider is None or not prop:
        return templates.TemplateResponse(
            "_error.html", {"request": request, "msg": "Skip-trace vendor not configured."}
        )
    if not prop.get("owner_name"):
        return templates.TemplateResponse(
            "_error.html", {"request": request, "msg": "No owner name on record to trace."}
        )
    first, last = _split_name(prop["owner_name"])
    try:
        contact = provider.trace(
            name=prop["owner_name"], address=prop.get("address") or "",
            city=prop.get("city") or "", state=prop.get("state") or "",
            zip=prop.get("zip") or "",
        )
    except BudgetExceeded as e:
        return templates.TemplateResponse("_error.html", {"request": request, "msg": str(e)})
    except Exception as e:  # noqa: BLE001
        return templates.TemplateResponse("_error.html", {"request": request, "msg": f"Skip trace failed: {e}"})
    if not contact:
        return templates.TemplateResponse(
            "_error.html", {"request": request, "msg": "No contact match found for this owner."}
        )
    db.save_contact(property_id, contact)
    return templates.TemplateResponse(
        "_contact.html", {"request": request, "contact": db.get_contact(property_id)}
    )


@app.get("/property/{property_id}/portfolio", response_class=HTMLResponse)
def portfolio(request: Request, property_id: int, _=Depends(require_auth)):
    return templates.TemplateResponse(
        "_portfolio.html",
        {"request": request, "properties": db.owner_portfolio(property_id)},
    )
