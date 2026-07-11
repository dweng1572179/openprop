"""RealEstateAPI ("REAPI") — OpenProp's optional PAID unlock for the nationwide
distress/legal flags Rentcast can't provide, plus an alternative skip-trace
source. Verified contract:
  auth: x-api-key header + Content-Type: application/json · base https://api.realestateapi.com
  POST /v2/PropertyDetail  -> distress/legal flags + owner + valuation (1 metered call)
  POST /v2/PropertySearch  -> distress-filtered list builder            (1 metered call)
  POST /v2/SkipTrace       -> owner contact enrichment, persons[] shape (billed per hit)
All endpoints are POST with JSON bodies; every response carries a `credits`
field = the credits that call actually burned (the true billing unit).

Billing is credit-based and REAPI publishes NO fetchable per-endpoint dollar
sheet, so we can't price a call before making it. We wrap paid calls at flat,
conservative cent estimates (constants below) purely so the cache-layer budget
guardrail + spend meter stay protective; real spend could later be reconciled
from the logged `credits`. See _COST ponytail.

Verifier corrections baked into this build: we use POST /v2/SkipTrace (v2 —
v1's `output.identity{}`/`match` shape deprecates 2026-07-15), and there is NO
/v1/DNC endpoint — the do-not-call signal rides on each phone. (For future
implementers: the sibling valuation endpoints are POST /v2/PropertyAvm — not
LenderGradeAVM — and standalone comps are POST /v3/PropertyComps; neither is
wired here, only the four registry-required methods are.)"""
import httpx

from ..cache import cached
from ..config import settings
from ..models import ContactRecord, PropertyRecord, SearchFilters

_BASE = "https://api.realestateapi.com"
_TIMEOUT = 25.0

# ponytail: credit-based pricing has no fetchable dollar figure, so these are
# conservative flat per-call estimates — enough for the budget guardrail to bite,
# not a real invoice. Ceiling: replace with the true per-endpoint credit cost of
# whatever plan is bought (or reconcile after the fact from response `credits`).
REAPI_DETAIL_COST_CENTS = 10     # PropertyDetail / PropertySearch (metered property call)
REAPI_SKIPTRACE_COST_CENTS = 15  # SkipTrace (billed per matched person, pricier than a lookup)

# The distress/legal fields Rentcast can't provide — distress() returns exactly
# this subset so services.lookup can merge it onto a free Rentcast base record.
# Includes est_loan_balance/est_equity: per rentcast.py these too "arrive with
# the RealEstateAPI unlock" (Rentcast has no loan/mortgage data), and feeding
# est_equity lets flags.compute_flags light up equity_pct/high_equity for free.
_DISTRESS_KEYS = (
    "pre_foreclosure", "foreclosure", "auction", "lien", "probate",
    "tax_delinquent", "vacant", "market_value", "est_loan_balance", "est_equity",
)


def _any_flag(d: dict, *keys: str) -> bool | None:
    """OR a set of REAPI booleans, but stay None when ALL inputs are absent
    (unknown != False — same discipline as flags.py)."""
    vals = [d.get(k) for k in keys]
    if all(v is None for v in vals):
        return None
    return any(bool(v) for v in vals)


def _split_name(name: str) -> tuple[str, str]:
    """First token -> first_name, remainder -> last_name.
    ponytail: naive whitespace split — doesn't handle "Last, First" or company
    names. Ceiling: OpenProp always passes owner_name as "First Last", and REAPI
    tolerates a partial name for matching, so this is good enough on purpose."""
    parts = (name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


class ReapiProvider:
    """PropertyProvider + the distress unlock (see registry.distress_provider)."""

    def __init__(self):
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": settings.reapi_api_key,  # NOT Bearer — REAPI uses a static key header
        }

    def _post(self, path: str, body: dict, cost_cents: int) -> dict:
        def fetch():
            r = httpx.post(f"{_BASE}{path}", json=body, headers=self._headers, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()

        return cached("reapi", path, body, fetch, cost_cents=cost_cents)

    # --- mapping -------------------------------------------------------------

    def _map_record(self, raw: dict, fallback_address: str = "") -> dict:
        """REAPI PropertyDetail `data{}` (or a PropertySearch result row) -> the
        PropertyRecord field dict. The two shapes DIFFER and both are handled:
        PropertyDetail nests under propertyInfo/lotInfo/taxInfo/ownerInfo, while a
        PropertySearch row is FLAT and uses its own names for several fields
        (squareFeet not livingSquareFeet, lastSaleAmount not lastSalePrice,
        companyName/owner1LastName not owner1FullName). Search-row shape verified
        live against zip 90007 (2026-07-11); reading only the nested blocks silently
        blanked owner/value/beds on every search result."""
        prop = raw.get("propertyInfo") or {}
        lot = raw.get("lotInfo") or {}
        tax = raw.get("taxInfo") or {}
        owner = raw.get("ownerInfo") or {}
        sale = raw.get("lastSale") or {}

        addr = prop.get("address") or raw.get("address") or {}
        if isinstance(addr, str):
            full_addr, city, state, zipc = addr, None, None, None
        else:
            full_addr = addr.get("label") or addr.get("address") or fallback_address or None
            city = addr.get("city") or raw.get("city")
            state = addr.get("state") or raw.get("state")
            zipc = addr.get("zip") or raw.get("zip")

        mail = owner.get("mailAddress") or raw.get("mailAddress") or {}
        owner_mailing = mail.get("label") or mail.get("address") or None
        if not owner_mailing and mail:
            owner_mailing = ", ".join(
                str(x) for x in (mail.get("street"), mail.get("city"), mail.get("state"), mail.get("zip")) if x
            ) or None

        equity_pct = raw.get("equityPercent")
        # a search row spells the owner across companyName / owner1FirstName+LastName;
        # PropertyDetail hands us a single owner1FullName.
        person = " ".join(str(x) for x in (raw.get("owner1FirstName"), raw.get("owner1LastName")) if x)
        rec = {
            # identity / location
            "apn": lot.get("apn") or raw.get("apn"),
            "address": full_addr or fallback_address,  # PropertyRecord.address is required
            "city": city,
            "state": state,
            "zip": zipc,
            "lat": lot.get("latitude") or raw.get("latitude"),
            "lng": lot.get("longitude") or raw.get("longitude"),
            # physical
            "property_type": prop.get("propertyType") or raw.get("propertyType"),
            "year_built": prop.get("yearBuilt") or raw.get("yearBuilt"),
            "beds": prop.get("bedrooms") or raw.get("bedrooms"),
            "baths": prop.get("bathrooms") or raw.get("bathrooms"),
            "building_sqft": (prop.get("livingSquareFeet") or prop.get("buildingSquareFeet")
                              or raw.get("squareFeet")),
            "lot_sqft": prop.get("lotSquareFeet") or lot.get("lotSquareFeet") or raw.get("lotSquareFeet"),
            # valuation / tax
            "assessed_value": tax.get("assessedValue") or raw.get("assessedValue"),
            "market_value": raw.get("estimatedValue"),
            "est_loan_balance": raw.get("openMortgageBalance"),
            # estimatedEquity is the dollar figure. `equity` is a BOOLEAN on a search
            # row (the high-equity filter bit), so it must never be read as an amount —
            # doing so reported $0 equity on a property with $1.39M of it.
            "est_equity": raw.get("estimatedEquity"),
            "equity_pct": round(equity_pct) if equity_pct is not None else None,
            "tax_amount": tax.get("taxAmount") or raw.get("taxAmount"),
            "last_sale_date": sale.get("lastSaleDate") or raw.get("lastSaleDate"),
            "last_sale_price": (sale.get("lastSalePrice") or raw.get("lastSalePrice")
                                or raw.get("lastSaleAmount")),
            # owner
            "owner_name": owner.get("owner1FullName") or owner.get("companyName") or person or raw.get("companyName"),
            "owner_mailing_addr": owner_mailing,
            "owner_occupied": owner.get("ownerOccupied") if owner.get("ownerOccupied") is not None
            else raw.get("ownerOccupied"),
            "corporate_owned": (owner.get("corporateOwned") if owner.get("corporateOwned") is not None
                                else raw.get("corporateOwned")),
            "years_owned": raw.get("yearsOwned"),
            # enrichment the search row already paid for — no extra call needed
            "rent_estimate": raw.get("rentAmount"),
            "median_income": raw.get("medianIncome"),
            "absentee": raw.get("absenteeOwner"),
            "out_of_state": raw.get("outOfStateAbsenteeOwner"),
            # distress / legal — the whole point of the unlock (EXACT REAPI names)
            "pre_foreclosure": raw.get("preForeclosure"),
            # foreclosureInfo[] is an array of records; presence => foreclosure
            "foreclosure": True if raw.get("foreclosureInfo") else raw.get("foreclosure"),
            "auction": raw.get("auction"),
            # ponytail: taxLien/lien are DEPRECATED + unreliable on PropertyDetail;
            # real lien depth lives in POST /v2/Reports/PropertyLiens (a second paid
            # report we don't call here). Ceiling: this is a coarse presence bit only.
            "lien": raw.get("lien") if raw.get("lien") is not None else raw.get("taxLien"),
            "probate": _any_flag(raw, "death", "deathTransfer", "spousalDeath", "inherited"),
            # ponytail: tax_delinquent is a PropertySearch FILTER, not a documented
            # PropertyDetail boolean — resolves to None on detail lookups.
            "tax_delinquent": raw.get("taxDelinquent"),
            "vacant": raw.get("vacant"),
            "source": "reapi",
        }
        return rec

    def _to_record(self, raw: dict, fallback_address: str = "") -> PropertyRecord:
        rec = self._map_record(raw, fallback_address)
        return PropertyRecord(**{k: v for k, v in rec.items() if k in PropertyRecord.model_fields})

    def _search_body(self, f: SearchFilters) -> dict:
        """SearchFilters -> REAPI PropertySearch snake_case filter body. OpenProp's
        cheap filters pass straight through; the paid unlock's value-add is the
        distress flags at the bottom.
        ponytail: SearchFilters.out_of_state and .owner_occupied have no clean
        REAPI search key (out_of_state only surfaces via the absentee flags, and
        there's no owner_occupied filter), so they're not forwarded — the local
        filter engine still applies them over the returned rows."""
        pairs = {
            # location
            "state": f.state,
            "county": f.county,
            "city": f.city,
            "zip": f.zip,
            # physical
            "property_type": f.property_type,
            "beds_min": f.beds_min,
            "baths_min": f.baths_min,
            "year_built_min": f.year_built_min,
            "year_built_max": f.year_built_max,
            "building_size_min": f.building_sqft_min,
            "lot_size_min": f.lot_sqft_min,
            # value / equity
            "value_min": f.value_min,
            "value_max": f.value_max,
            "assessed_value_min": f.assessed_value_min,
            "equity_percent_min": f.equity_pct_min,
            "years_owned": f.years_owned_min,  # REAPI exposes a single years_owned, not a _min
            # demographics
            "median_income_min": f.median_income_min,
            # ownership + distress flags — the paid unlock Rentcast can't serve
            "absentee_owner": f.absentee,
            "corporate_owned": f.corporate_owned,
            "high_equity": f.high_equity,
            "tax_delinquent": f.tax_delinquent,
            "vacant": f.vacant,
            "pre_foreclosure": f.pre_foreclosure,
        }
        body: dict = {"size": min(f.limit, 500)}
        body.update({k: v for k, v in pairs.items() if v is not None})
        return body

    # --- interface -----------------------------------------------------------

    def lookup(self, address: str) -> PropertyRecord | None:
        resp = self._post("/v2/PropertyDetail", {"address": address}, REAPI_DETAIL_COST_CENTS)
        data = (resp or {}).get("data")
        if not data:
            return None
        return self._to_record(data, address)

    def search(self, f: SearchFilters) -> list[PropertyRecord]:
        resp = self._post("/v2/PropertySearch", self._search_body(f), REAPI_DETAIL_COST_CENTS)
        rows = (resp or {}).get("data") or []
        return [self._to_record(raw) for raw in rows if isinstance(raw, dict)]

    def distress(self, address: str) -> dict | None:
        """The distress-flag subset only — the fields Rentcast can't provide, so
        services.lookup can merge them onto a free Rentcast base record. Reuses
        the same PropertyDetail call as lookup(): cached() keys on the request, so
        when REAPI is BOTH property + distress provider this is a free cache hit."""
        resp = self._post("/v2/PropertyDetail", {"address": address}, REAPI_DETAIL_COST_CENTS)
        data = (resp or {}).get("data")
        if not data:
            return None
        rec = self._map_record(data, address)
        # only forward known values so we never overwrite a base field with None
        return {k: rec[k] for k in _DISTRESS_KEYS if rec.get(k) is not None}


class ReapiSkipTrace:
    """SkipTraceProvider — POST /v2/SkipTrace, persons[] shape (v2, live 2026-01-16)."""

    def __init__(self):
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": settings.reapi_api_key,
        }

    def _post(self, path: str, body: dict, cost_cents: int) -> dict:
        def fetch():
            r = httpx.post(f"{_BASE}{path}", json=body, headers=self._headers, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()

        return cached("reapi", path, body, fetch, cost_cents=cost_cents)

    def _map_phone(self, ph: dict) -> dict:
        # ponytail: v2 renamed the DNC signal to `phoneFtcDnc` and dropped v1's
        # `isConnected`; we read both names so a phone maps whichever shape the
        # live endpoint returns. is_connected -> None on pure v2 (no source).
        dnc = ph.get("doNotCall")
        if dnc is None:
            dnc = ph.get("phoneFtcDnc")
        return {
            "number": ph.get("phone"),
            "type": ph.get("phoneType"),
            "is_connected": ph.get("isConnected"),
            "dnc": dnc,  # key matches _contact.html + the batchdata provider
            "last_seen": ph.get("phoneLastSeen"),
        }

    def _map_address(self, a: dict) -> dict:
        return {
            "street": a.get("streetAddress") or a.get("address"),  # key matches _contact.html
            "city": a.get("city"),
            "state": a.get("state"),
            "zip": a.get("zip"),
        }

    def trace(self, name: str, address: str, city: str, state: str, zip: str) -> ContactRecord | None:
        first, last = _split_name(name)
        body = {
            "first_name": first,
            "last_name": last,
            "address": address,
            "city": city,
            "state": state,
            "zip": zip,
        }
        resp = self._post("/v2/SkipTrace", body, REAPI_SKIPTRACE_COST_CENTS)
        persons = (resp or {}).get("persons") or []
        if not persons:
            return None
        p = persons[0]

        addresses = [self._map_address(a) for a in (p.get("address"), p.get("previousAddress")) if a]
        return ContactRecord(
            person_name=p.get("fullName"),
            age=p.get("age"),
            phones=[self._map_phone(ph) for ph in (p.get("phones") or [])],
            # ponytail: v2 emails are bare strings (no is_validated/is_business
            # flag v1 carried) — wrap each so the ContactRecord email dict shape holds.
            emails=[{"email": e} for e in (p.get("emails") or []) if e],
            addresses=addresses,
            # v2 SkipTrace exposes no numeric identity/match score (v1 had only a
            # `match` boolean), so identity_score stays None.
            identity_score=None,
        )
