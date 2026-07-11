"""FastAPI app: single service, single user. Routes stay thin — orchestration
lives in services.py, data access in db.py, provider calls behind registry.py.
Auth is one password + a signed session cookie (Starlette SessionMiddleware)."""
import secrets

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .cache import budget_remaining_cents, spend_this_month
from .config import settings
from .db import init_db

app = FastAPI(title="OpenProp")

_secret = settings.secret_key or secrets.token_hex(32)
if not settings.secret_key:
    print("[openprop] no SECRET_KEY set — using an ephemeral one "
          "(sessions reset on restart). Set SECRET_KEY in .env to persist.")
if settings.openprop_password == "changeme":
    print("[openprop] WARNING: OPENPROP_PASSWORD is still the default 'changeme' — "
          "set a real password in .env before exposing this beyond localhost.")
app.add_middleware(
    SessionMiddleware, secret_key=_secret, same_site="lax",
    https_only=settings.session_https_only,  # Secure flag; enable when behind HTTPS
)

templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def _startup():
    init_db()
    from . import settings_store
    settings_store.load_overrides()  # apply dashboard-saved keys over .env defaults


# --- auth --------------------------------------------------------------------

def require_auth(request: Request):
    """Dependency: bounce unauthenticated requests to /login."""
    if not request.session.get("auth"):
        raise _redirect("/login")
    return True


class _Redirect(Exception):
    def __init__(self, to: str):
        self.to = to


def _redirect(to: str) -> _Redirect:
    return _Redirect(to)


@app.exception_handler(_Redirect)
async def _redirect_handler(request: Request, exc: _Redirect):
    return RedirectResponse(exc.to, status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, settings.openprop_password):
        request.session["auth"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Wrong password."}, status_code=401
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- home --------------------------------------------------------------------

def _spend_ctx() -> dict:
    return {
        "spend_cents": spend_this_month(),
        "budget_cents": settings.monthly_budget_cents,
        "remaining_cents": budget_remaining_cents(),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request, _=Depends(require_auth)):
    from . import registry
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "provider_ready": registry.property_provider() is not None, **_spend_ctx()},
    )


# Feature routes (lookup, enrichment, skiptrace, search, ai, notes,
# saved-searches, export) attach to `app` here as each phase lands:
from . import routes_lookup     # noqa: E402,F401  (Phase 1)
from . import routes_notes      # noqa: E402,F401  (Phase 2)
from . import routes_skiptrace  # noqa: E402,F401  (Phase 3)
from . import routes_search     # noqa: E402,F401  (Phase 4)
from . import routes_ai         # noqa: E402,F401  (Phase 5)
from . import routes_settings   # noqa: E402,F401  (dashboard settings)
