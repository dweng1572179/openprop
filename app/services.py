"""Service layer — orchestration between routes and providers. Enrichment is
best-effort: a missing (not-yet-built) or failing provider degrades that panel,
never the whole lookup. This is the free-first, optional-unlock design (spec §3)."""
import logging

from . import registry
from .cache import BudgetExceeded
from .db import save_property
from .filter_engine import apply_filters
from .flags import compute_flags
from .models import PropertyRecord, SearchFilters

log = logging.getLogger("openprop")


def _try(label: str, fn):
    """Run an enrichment step best-effort; swallow provider gaps/outages. A
    budget block always propagates — the user must see why data is missing."""
    try:
        return fn()
    except BudgetExceeded:
        raise
    except ImportError:
        return None  # provider not built/wired yet
    except Exception as e:  # noqa: BLE001 — enrichment must not break lookup
        log.warning("enrichment %s failed: %s", label, e)
        return None


def lookup(address: str) -> PropertyRecord | None:
    """Geocode -> property provider -> free enrichment -> flags -> cache -> record."""
    geo = registry.geocoder()
    if geo is None:
        raise RuntimeError("no geocoder configured (set GEOCODER=census)")
    g = geo.geocode(address)
    if not g:
        return None

    rec: dict = {
        "address": g.get("matched_address") or address,
        "city": g.get("city"),
        "state": g.get("state"),
        "zip": g.get("zip"),
        "lat": g.get("lat"),
        "lng": g.get("lng"),
        "fips": g.get("county_fips"),
        "source": "census",
    }

    pp = registry.property_provider()
    if pp is not None:
        pr = _try("property", lambda: pp.lookup(rec["address"]))
        if pr:
            # provider fields win where present; keep geocode fallbacks
            for k, v in pr.model_dump(exclude_none=True).items():
                rec[k] = v
            rec["source"] = pr.source or rec["source"]

    # --- free / optional enrichment (best-effort) ---
    if rec.get("lat") and rec.get("lng"):
        fp = _try("flood", registry.flood_provider)
        if fp:
            rec["flood_zone"] = _try("flood_zone", lambda: fp.flood_zone(rec["lat"], rec["lng"]))

    if rec.get("fips"):
        dp = _try("demographics", registry.demographics_provider)
        if dp:
            rec["median_income"] = _try("median_income", lambda: dp.median_income(rec["fips"]))

    fmr = _try("fmr_provider", registry.fmr_provider)
    if fmr:
        rec["fmr_by_bed"] = _try("fmr", lambda: fmr.fmr(rec.get("zip"), rec.get("fips")))

    # optional paid distress unlock
    dd = _try("distress", registry.distress_provider)
    if dd and hasattr(dd, "distress"):
        flags = _try("distress_flags", lambda: dd.distress(rec["address"]))
        if flags:
            rec.update(flags)

    compute_flags(rec)
    rec["id"] = save_property(rec)
    return PropertyRecord(**{k: v for k, v in rec.items() if k in PropertyRecord.model_fields})


def search(f: SearchFilters) -> list[PropertyRecord]:
    """List builder: provider coarse area search -> compute flags -> cache each
    -> local filter engine applies the cheap filters the provider can't. Returns
    the refined set. (Equity/distress filters need the paid unlock — a Rentcast-
    only set has no market value, so equity-based filters exclude everything.)"""
    pp = registry.property_provider()
    if pp is None:
        raise RuntimeError("no property provider configured (set PROPERTY_PROVIDER + key)")
    coarse = pp.search(f)
    enriched: list[PropertyRecord] = []
    for rec in coarse:
        d = rec.model_dump()
        compute_flags(d)
        d["id"] = save_property(d)
        enriched.append(PropertyRecord(**{k: v for k, v in d.items() if k in PropertyRecord.model_fields}))
    return apply_filters(enriched, f)
