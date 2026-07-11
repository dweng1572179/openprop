"""RentCast — OpenProp's primary property provider. Verified contract:
  auth: X-Api-Key header · base: https://api.rentcast.io/v1
  GET /properties          -> attributes + owner + tax  (1 billable req)
  GET /avm/value           -> market value + sale comps  (1 billable req)
  GET /avm/rent/long-term  -> rent estimate + rent comps (1 billable req)
A full card is up to 3 requests, each cached independently so re-views are free.
Billing: free 50/mo then $0.20/req -> we price every call at the 20¢ overage rate
so the budget guardrail is protective (a conservative upper bound; the first
50/mo are actually free). RentCast has NO loan/mortgage or distress fields, so
est_equity is left unknown here — it arrives with the RealEstateAPI unlock."""
import httpx

from ..cache import BudgetExceeded, cached
from ..config import settings
from ..models import PropertyRecord, SearchFilters

_BASE = "https://api.rentcast.io/v1"
_COST = 20  # cents; free-tier overage rate, used as a conservative spend estimate
_TIMEOUT = 25.0


def _latest(d: dict | None, field: str):
    """taxAssessments / propertyTaxes are keyed by year string — take the max."""
    if not d:
        return None
    try:
        newest = max(d.keys())
    except ValueError:
        return None
    return (d.get(newest) or {}).get(field)


class RentcastProvider:
    def __init__(self):
        self._headers = {"Accept": "application/json", "X-Api-Key": settings.rentcast_api_key}

    def _get(self, path: str, params: dict) -> list | dict:
        def fetch():
            r = httpx.get(f"{_BASE}{path}", params=params, headers=self._headers, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()

        return cached("rentcast", path, params, fetch, cost_cents=_COST)

    # --- mapping -------------------------------------------------------------

    def _map_record(self, raw: dict) -> dict:
        owner = raw.get("owner") or {}
        names = owner.get("names") or []
        mailing = (owner.get("mailingAddress") or {}).get("formattedAddress")
        return {
            "apn": raw.get("assessorID"),
            "address": raw.get("formattedAddress"),
            "city": raw.get("city"),
            "state": raw.get("state"),
            "zip": raw.get("zipCode"),
            "lat": raw.get("latitude"),
            "lng": raw.get("longitude"),
            "property_type": raw.get("propertyType"),
            "land_use": raw.get("zoning"),  # no land-use code; zoning is closest
            "year_built": raw.get("yearBuilt"),
            "beds": raw.get("bedrooms"),
            "baths": raw.get("bathrooms"),
            "building_sqft": raw.get("squareFootage"),
            "lot_sqft": raw.get("lotSize"),
            "assessed_value": _latest(raw.get("taxAssessments"), "value"),
            "tax_amount": _latest(raw.get("propertyTaxes"), "total"),
            "last_sale_date": raw.get("lastSaleDate"),
            "last_sale_price": raw.get("lastSalePrice"),
            "owner_name": " & ".join(names) if names else None,
            "owner_mailing_addr": mailing,
            "owner_occupied": raw.get("ownerOccupied"),
            # authoritative corporate signal (owner.type); flags.py won't override
            "corporate_owned": (owner.get("type") == "Organization") if owner.get("type") else None,
            "source": "rentcast",
        }

    # --- interface -----------------------------------------------------------

    def lookup(self, address: str) -> PropertyRecord | None:
        try:
            records = self._get("/properties", {"address": address})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None  # RentCast has no record for this address (not an error)
            raise
        if not records:
            return None
        rec = self._map_record(records[0])

        # value + rent are TWO MORE billable requests each lookup (3 total). RentCast's
        # free tier is only 50 requests/mo and overage is $0.20/req with no cap on the
        # key, so they are OPT-IN: set RENTCAST_FETCH_AVM=true to enable. Default off
        # keeps a lookup at exactly 1 request.
        if not settings.rentcast_fetch_avm:
            return PropertyRecord(**{k: v for k, v in rec.items() if k in PropertyRecord.model_fields})

        # best-effort so the base record still returns if these fail or the budget blocks them.
        for path, key, field in [
            ("/avm/value", "market_value", "price"),
            ("/avm/rent/long-term", "rent_estimate", "rent"),
        ]:
            try:
                avm = self._get(path, {"address": address, "lookupSubjectAttributes": "true"})
                if isinstance(avm, dict) and avm.get(field) is not None:
                    rec[key] = round(avm[field])
            except BudgetExceeded:
                break  # out of budget for extras; keep what we have
            except Exception:  # noqa: BLE001 — value/rent are enrichment, not required
                pass
        return PropertyRecord(**{k: v for k, v in rec.items() if k in PropertyRecord.model_fields})

    def search(self, f: SearchFilters) -> list[PropertyRecord]:
        """Coarse area search — RentCast filters only on location + physical
        attributes; equity/owner/distress filters are applied downstream by the
        local filter engine (RentCast has no server-side support for them)."""
        # Fetch a full coarse page (RentCast bills 1 request regardless of count),
        # so the local filter engine has enough rows to fill f.limit after refining.
        params: dict = {"limit": 500}
        if f.zip:
            params["zipCode"] = f.zip
        if f.city:
            params["city"] = f.city
        if f.state:
            params["state"] = f.state
        if f.property_type:
            params["propertyType"] = f.property_type
        if f.beds_min is not None:
            params["bedrooms"] = f.beds_min
        if f.year_built_min is not None:
            params["yearBuilt"] = f.year_built_min
        if not (params.get("zipCode") or params.get("city")):
            return []  # need at least an area to search
        records = self._get("/properties", params)
        out = []
        for raw in records if isinstance(records, list) else []:
            rec = self._map_record(raw)
            out.append(PropertyRecord(**{k: v for k, v in rec.items() if k in PropertyRecord.model_fields}))
        return out
