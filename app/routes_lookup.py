"""/lookup — single-property lookup. Returns an HTMX partial (the property card)
that swaps into the home page. Kept thin; orchestration is in services.py."""
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse

from . import services
from .app import app, require_auth, templates
from .cache import BudgetExceeded


@app.post("/lookup", response_class=HTMLResponse)
def lookup_route(request: Request, address: str = Form(...), _=Depends(require_auth)):
    try:
        rec = services.lookup(address.strip())
    except BudgetExceeded as e:
        return templates.TemplateResponse("_error.html", {"request": request, "msg": str(e)})
    except Exception as e:  # noqa: BLE001 — surface any provider error to the UI
        return templates.TemplateResponse("_error.html", {"request": request, "msg": str(e)})
    if not rec:
        return templates.TemplateResponse(
            "_error.html", {"request": request, "msg": "No property matched that address."}
        )
    return templates.TemplateResponse("_property_card.html", {"request": request, "p": rec})
