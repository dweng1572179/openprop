"""Runtime settings — lets you paste API keys in the dashboard instead of editing
.env + restarting. DB `setting` rows override the .env-loaded `settings` object
live; saving rebuilds the provider registry so new keys take effect immediately.
Precedence: DB override > .env > default."""
from .config import settings
from .db import get_conn

# (name, label, kind) — kind: "secret" | "text" | "int" | "select:a,b,c"
FIELDS = [
    ("property_provider", "Primary property provider", "select:rentcast,regrid,reapi"),
    ("skiptrace_provider", "Skip-trace vendor", "select:,batchdata,reapi"),
    ("rentcast_api_key", "RentCast API key", "secret"),
    ("skiptrace_api_key", "Skip-trace API key", "secret"),
    ("reapi_api_key", "RealEstateAPI key (distress unlock)", "secret"),
    ("regrid_api_token", "Regrid API token (parcel map)", "secret"),
    ("hud_fmr_token", "HUD FMR token", "secret"),
    ("census_api_key", "Census API key (median income)", "secret"),
    ("anthropic_api_key", "Anthropic API key (AI features)", "secret"),
    ("llm_model", "LLM model", "text"),
    ("monthly_budget_cents", "Monthly paid-spend cap (cents)", "int"),
]
_KINDS = {name: kind for name, label, kind in FIELDS}
SECRETS = {name for name, _, kind in FIELDS if kind == "secret"}


def _apply(name: str, value: str) -> None:
    if not hasattr(settings, name):
        return
    if _KINDS.get(name) == "int":
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
    setattr(settings, name, value)  # live override on the shared settings object


def load_overrides() -> None:
    """Apply saved DB overrides onto `settings` at startup."""
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM setting").fetchall()
    for r in rows:
        _apply(r["key"], r["value"])


def save(updates: dict[str, str]) -> None:
    """Persist + apply updates, then rebuild providers so keys take effect now."""
    from . import registry
    with get_conn() as conn:
        for name, value in updates.items():
            conn.execute(
                "INSERT INTO setting (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (name, str(value)),
            )
    for name, value in updates.items():
        _apply(name, str(value))
    registry.reset()  # drop cached provider instances built with the old keys
