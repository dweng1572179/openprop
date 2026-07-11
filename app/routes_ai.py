"""AI routes — NL search (always available via rules fallback) + per-property
brief / lead score / outreach draft (need an Anthropic key)."""
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse

from . import ai, db, services
from .app import app, require_auth, templates
from .routes_search import _geojson  # escaped GeoJSON builder (shared)


@app.post("/ai/parse", response_class=HTMLResponse)
def ai_parse(request: Request, query: str = Form(...), _=Depends(require_auth)):
    f = ai.nl_to_filters(query.strip())
    interpreted = {k: v for k, v in f.model_dump().items() if v is not None and k != "limit"}
    try:
        results = services.search(f)
    except Exception as e:  # noqa: BLE001
        return templates.TemplateResponse("_error.html", {"request": request, "msg": str(e)})
    return templates.TemplateResponse("_results.html", {
        "request": request, "results": results, "geojson": _geojson(results),
        "filters_json": f.model_dump_json(), "interpreted": interpreted,
    })


def _prose(request: Request, property_id: int, fn, label: str) -> HTMLResponse:
    p = db.get_property(property_id)
    if not p:
        return templates.TemplateResponse("_error.html", {"request": request, "msg": "Unknown property."})
    if not ai.available():
        return templates.TemplateResponse(
            "_error.html", {"request": request, "msg": "Set ANTHROPIC_API_KEY to use AI features."})
    text = fn(p)
    return templates.TemplateResponse(
        "_ai_text.html", {"request": request, "label": label, "text": text or "(no output)"})


@app.post("/ai/brief/{property_id}", response_class=HTMLResponse)
def ai_brief(request: Request, property_id: int, _=Depends(require_auth)):
    return _prose(request, property_id, ai.brief, "Brief")


@app.post("/ai/outreach/{property_id}", response_class=HTMLResponse)
def ai_outreach(request: Request, property_id: int, _=Depends(require_auth)):
    return _prose(request, property_id, ai.outreach, "Outreach draft")


@app.post("/ai/score/{property_id}", response_class=HTMLResponse)
def ai_score(request: Request, property_id: int, _=Depends(require_auth)):
    p = db.get_property(property_id)
    if not p:
        return templates.TemplateResponse("_error.html", {"request": request, "msg": "Unknown property."})
    if not ai.available():
        return templates.TemplateResponse(
            "_error.html", {"request": request, "msg": "Set ANTHROPIC_API_KEY to use AI features."})
    result = ai.score_lead(p)
    return templates.TemplateResponse("_ai_score.html", {"request": request, "result": result})
