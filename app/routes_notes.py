"""Notes CRUD — private per-property notes (CRM-style). Each
route returns the notes partial so HTMX swaps the list in place."""
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse

from . import db
from .app import app, require_auth, templates


def _render(request: Request, property_id: int) -> HTMLResponse:
    return templates.TemplateResponse(
        "_notes.html",
        {"request": request, "property_id": property_id, "notes": db.list_notes(property_id)},
    )


@app.get("/property/{property_id}/notes", response_class=HTMLResponse)
def notes_list(request: Request, property_id: int, _=Depends(require_auth)):
    return _render(request, property_id)


@app.post("/property/{property_id}/notes", response_class=HTMLResponse)
def notes_add(request: Request, property_id: int, body: str = Form(...), _=Depends(require_auth)):
    body = body.strip()[:5000]  # 5k-char cap
    if body:
        db.add_note(property_id, body)
    return _render(request, property_id)


@app.delete("/note/{note_id}", response_class=HTMLResponse)
def notes_delete(request: Request, note_id: int, _=Depends(require_auth)):
    property_id = db.delete_note(note_id)
    return _render(request, property_id or 0)
