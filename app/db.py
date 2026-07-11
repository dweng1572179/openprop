"""SQLite: cache + canonical records + notes + saved searches. Raw stdlib
sqlite3 — no ORM, no migrations. Schema is spec §5. Single file, WAL mode."""
import json
import sqlite3
from contextlib import contextmanager

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_cache (
    id            INTEGER PRIMARY KEY,
    provider      TEXT NOT NULL,
    endpoint      TEXT NOT NULL,
    request_hash  TEXT NOT NULL UNIQUE,
    response_json TEXT NOT NULL,
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),
    cost_cents    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cache_month ON provider_cache(fetched_at);

CREATE TABLE IF NOT EXISTS property (
    id            INTEGER PRIMARY KEY,
    apn           TEXT,
    address       TEXT NOT NULL,
    city          TEXT, state TEXT, zip TEXT, lat REAL, lng REAL, fips TEXT,
    property_type TEXT, land_use TEXT, year_built INTEGER,
    beds REAL, baths REAL, building_sqft INTEGER, lot_sqft INTEGER,
    assessed_value INTEGER, market_value INTEGER,
    est_loan_balance INTEGER, est_equity INTEGER, equity_pct INTEGER,
    tax_amount INTEGER, last_sale_date TEXT, last_sale_price INTEGER,
    owner_name TEXT, owner_mailing_addr TEXT, owner_occupied INTEGER, years_owned INTEGER,
    absentee INTEGER, out_of_state INTEGER, corporate_owned INTEGER,
    high_equity INTEGER, tax_delinquent INTEGER, vacant INTEGER,
    pre_foreclosure INTEGER, foreclosure INTEGER, auction INTEGER, lien INTEGER, probate INTEGER,
    flood_zone TEXT, rent_estimate INTEGER, fmr_by_bed TEXT, median_income INTEGER,
    source TEXT,
    owner_key     TEXT,   -- normalized owner name+mailing, for portfolio grouping
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(address, zip)
);
CREATE INDEX IF NOT EXISTS idx_prop_owner ON property(owner_key);

-- Skip-trace results. Sensitive; local only.
CREATE TABLE IF NOT EXISTS contact (
    id            INTEGER PRIMARY KEY,
    property_id   INTEGER REFERENCES property(id) ON DELETE CASCADE,
    person_name   TEXT, age INTEGER,
    phones_json   TEXT, emails_json TEXT, addresses_json TEXT,
    identity_score REAL,
    traced_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS note (
    id            INTEGER PRIMARY KEY,
    property_id   INTEGER REFERENCES property(id) ON DELETE CASCADE,
    body          TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saved_search (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    filters_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Runtime config (API keys, provider choice) editable from the dashboard, so you
-- never have to touch .env. Overrides the .env defaults; local plaintext (same as
-- .env) — fine for a single-user localhost tool.
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS list_result (
    saved_search_id INTEGER REFERENCES saved_search(id) ON DELETE CASCADE,
    property_id     INTEGER REFERENCES property(id) ON DELETE CASCADE
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


# --- property persistence (upsert by address+zip) ----------------------------

_PROP_COLS = [
    "apn", "address", "city", "state", "zip", "lat", "lng", "fips",
    "property_type", "land_use", "year_built", "beds", "baths",
    "building_sqft", "lot_sqft", "assessed_value", "market_value",
    "est_loan_balance", "est_equity", "equity_pct", "tax_amount",
    "last_sale_date", "last_sale_price", "owner_name", "owner_mailing_addr",
    "owner_occupied", "years_owned", "absentee", "out_of_state",
    "corporate_owned", "high_equity", "tax_delinquent", "vacant",
    "pre_foreclosure", "foreclosure", "auction", "lien", "probate",
    "flood_zone", "rent_estimate", "fmr_by_bed", "median_income", "source",
    "owner_key",
]


def save_property(rec: dict) -> int:
    """Upsert a normalized property dict; return its row id. `fmr_by_bed` is
    JSON-encoded here so callers pass the plain dict."""
    row = {k: rec.get(k) for k in _PROP_COLS}
    # SQLite UNIQUE treats NULLs as distinct, so a NULL zip would dupe rows on
    # repeat lookups — coerce to '' so ON CONFLICT(address, zip) actually fires.
    row["zip"] = row.get("zip") or ""
    if isinstance(row.get("fmr_by_bed"), dict):
        row["fmr_by_bed"] = json.dumps(row["fmr_by_bed"])
    for b in ("owner_occupied", "absentee", "out_of_state", "corporate_owned",
              "high_equity", "tax_delinquent", "vacant", "pre_foreclosure",
              "foreclosure", "auction", "lien", "probate"):
        if row.get(b) is not None:
            row[b] = int(bool(row[b]))
    cols = ", ".join(_PROP_COLS)
    placeholders = ", ".join(f":{c}" for c in _PROP_COLS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _PROP_COLS if c != "address")
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO property ({cols}, updated_at) "
            f"VALUES ({placeholders}, datetime('now')) "
            f"ON CONFLICT(address, zip) DO UPDATE SET {updates}, updated_at=datetime('now') "
            f"RETURNING id",
            row,
        )
        return cur.fetchone()["id"]


def get_property(property_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM property WHERE id = ?", (property_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("fmr_by_bed"):  # stored as JSON text — decode so callers get the dict back
        d["fmr_by_bed"] = json.loads(d["fmr_by_bed"])
    return d


# --- notes -------------------------------------------------------------------

def add_note(property_id: int, body: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO note (property_id, body) VALUES (?, ?)", (property_id, body))


def list_notes(property_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, body, created_at FROM note WHERE property_id = ? ORDER BY id DESC",
            (property_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_note(note_id: int) -> int | None:
    """Delete a note; return its property_id (to re-render that list) or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT property_id FROM note WHERE id = ?", (note_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM note WHERE id = ?", (note_id,))
        return row["property_id"]


# --- skip-trace contacts (PII; local only) -----------------------------------

def save_contact(property_id: int, c) -> None:
    """Persist a ContactRecord. c.phones/emails/addresses are stored as JSON."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO contact (property_id, person_name, age, phones_json, "
            "emails_json, addresses_json, identity_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (property_id, c.person_name, c.age, json.dumps(c.phones),
             json.dumps(c.emails), json.dumps(c.addresses), c.identity_score),
        )


def get_contact(property_id: int) -> dict | None:
    """Most recent skip-trace result for a property, with JSON fields decoded."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM contact WHERE property_id = ? ORDER BY id DESC LIMIT 1",
            (property_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("phones_json", "emails_json", "addresses_json"):
        d[k] = json.loads(d[k]) if d.get(k) else []
    return d


def save_saved_search(name: str, filters_json: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO saved_search (name, filters_json) VALUES (?, ?) RETURNING id",
            (name, filters_json),
        )
        return cur.fetchone()["id"]


def list_saved_searches() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, filters_json, created_at FROM saved_search ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_saved_search(search_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM saved_search WHERE id = ?", (search_id,)).fetchone()
    return dict(row) if row else None


def delete_saved_search(search_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM saved_search WHERE id = ?", (search_id,))


def owner_portfolio(property_id: int) -> list[dict]:
    """Other cached properties tied to the same owner (linked-properties parity)."""
    with get_conn() as conn:
        me = conn.execute("SELECT owner_key FROM property WHERE id = ?", (property_id,)).fetchone()
        if not me or not me["owner_key"]:
            return []
        rows = conn.execute(
            "SELECT id, address, city, state, market_value, est_equity FROM property "
            "WHERE owner_key = ? AND id != ? ORDER BY market_value DESC",
            (me["owner_key"], property_id),
        ).fetchall()
    return [dict(r) for r in rows]
