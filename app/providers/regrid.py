"""Regrid (Landgrid) — OpenProp's Phase-4 parcel BOUNDARY + alt owner/zoning source.
Verified contract (2026-07-11 live curl + Regrid schema docs):
  auth: `token` QUERY param on EVERY request (no header/OAuth); missing -> 401.
  records base: https://app.regrid.com/api/v2 · tileserver: https://tiles.regrid.com/api/v1
  GET /parcels/address?query=<addr>  -> parcel by street address
  GET /parcels/point?lat=&lon=       -> parcel(s) at a coordinate (the map-click call)
  GET /parcels/query?fields[k][op]=v -> area/field query (ANDs up to 4 filters)
  GET /parcels/{z}/{x}/{y}.mvt (tiles host) -> MapLibre vector tiles, source-layer 'parcels'
Response gotcha: the FeatureCollection is nested under a top-level `parcels` key,
and parcel columns live under feature.properties.fields.* (NOT flat on properties).
Geometry is GeoJSON Polygon/MultiPolygon — directly MapLibre-renderable, the unique
value-add vs Rentcast. This is boundaries + owner/mailing + zoning/land-use only:
no AVM/rent/comps/skip-trace (Rentcast/REAPI stay primary for those).
Billing: flat-rate monthly SUBSCRIPTION (~$375/mo incl. records + tiles), NOT metered
per-call — so every hit is priced at 0c and the budget guardrail ignores Regrid."""
import httpx

from ..cache import cached
from ..config import settings
from ..models import PropertyRecord, SearchFilters

_BASE = "https://app.regrid.com/api/v2"
_TILES = "https://tiles.regrid.com/api/v1"
# ponytail: Regrid is a flat-rate monthly subscription, not per-request billing,
# so we spend 0c per call — the spend meter only tracks the metered providers
# (Rentcast/REAPI). The ~$375/mo is a fixed cost, invisible to the per-call cap.
_COST = 0
_TIMEOUT = 25.0


def _features(data: dict | None) -> list[dict]:
    """Pull the feature array out of Regrid's nested `parcels` envelope."""
    return ((data or {}).get("parcels") or {}).get("features") or []


def _centroid(geometry: dict | None) -> tuple[float | None, float | None]:
    """Vertex-mean (lat, lng) of the polygon rings — geometry is always present.
    ponytail: a plain average of the boundary vertices, NOT an area-weighted
    centroid; it's only used to seed a marker, and lat/lng isn't load-bearing
    (the frontend renders the real Polygon from parcel_boundary/the tiles)."""
    pts: list = []

    def walk(node) -> None:
        if isinstance(node, list) and len(node) == 2 and all(isinstance(n, (int, float)) for n in node):
            pts.append(node)  # a [lng, lat] coordinate pair
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk((geometry or {}).get("coordinates"))
    if not pts:
        return None, None
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def _mailing(f: dict) -> str | None:
    """Compose the owner mailing address from Regrid's split mail_* columns."""
    parts = [f.get("mailadd"), f.get("mail_address2"), f.get("mail_city"),
             f.get("mail_state2"), f.get("mail_zip")]
    joined = " ".join(str(p).strip() for p in parts if p)
    return joined or None


class RegridProvider:
    def _get(self, path: str, params: dict) -> dict:
        # token rides on every request as a query param (contract auth); kept out
        # of the cache key so hits don't fragment if the token is rotated.
        query = {**params, "token": settings.regrid_api_token}

        def fetch():
            r = httpx.get(f"{_BASE}{path}", params=query, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()

        return cached("regrid", path, params, fetch, cost_cents=_COST)

    # --- mapping -------------------------------------------------------------

    def _map_record(self, feat: dict) -> dict:
        props = feat.get("properties") or {}
        f = props.get("fields") or {}
        lat, lng = _centroid(feat.get("geometry"))
        return {
            "apn": f.get("parcelnumb") or f.get("alt_parcelnumb1"),
            "address": f.get("address") or props.get("headline"),
            "city": f.get("scity") or f.get("city"),
            "state": f.get("state2"),
            "zip": f.get("szip"),
            "lat": lat,
            "lng": lng,
            "fips": f.get("geoid"),  # county FIPS
            # raw county use code/desc; Regrid's standardized zoning has no
            # PropertyRecord slot (model has land_use only), so it's dropped here.
            "land_use": f.get("usedesc") or f.get("usecode"),
            "year_built": f.get("yearbuilt"),
            "lot_sqft": f.get("ll_gissqft"),
            # parval is the county ASSESSED value, not an AVM — Rentcast owns market_value.
            "assessed_value": f.get("parval"),
            "last_sale_date": f.get("saledate"),
            "last_sale_price": f.get("saleprice"),
            "owner_name": f.get("owner"),
            "owner_mailing_addr": _mailing(f),
            # owner_occupied/absentee/out_of_state are derived downstream by
            # flags.py (situs vs mailing) — Regrid has no native owner-occupied bit.
            "source": "regrid",
        }

    def _to_record(self, feat: dict) -> PropertyRecord:
        rec = self._map_record(feat)
        return PropertyRecord(**{k: v for k, v in rec.items() if k in PropertyRecord.model_fields})

    # --- interface -----------------------------------------------------------

    def lookup(self, address: str) -> PropertyRecord | None:
        feats = _features(self._get("/parcels/address", {"query": address}))
        return self._to_record(feats[0]) if feats else None

    def search(self, f: SearchFilters) -> list[PropertyRecord]:
        """Area/field query via /parcels/query bracket-syntax filters. Regrid ANDs
        at most 4 filters/call, so we send the location-anchored ones and let the
        local filter engine apply the remainder over cached records."""
        # bracket-syntax field filters (contract: fields[<name>][<op>]=<value>).
        filters: dict = {}
        if f.state:
            filters["fields[state2][eq]"] = f.state
        if f.county:
            filters["fields[county][ilike]"] = f.county
        if f.city:
            filters["fields[scity][ilike]"] = f.city
        if f.zip:
            filters["fields[szip][eq]"] = f.zip
        if f.year_built_min is not None:
            filters["fields[yearbuilt][gte]"] = f.year_built_min
        if f.lot_sqft_min is not None:
            filters["fields[ll_gissqft][gte]"] = f.lot_sqft_min
        if f.assessed_value_min is not None:
            filters["fields[parval][gte]"] = f.assessed_value_min
        if not (f.zip or f.city or f.county):
            return []  # need an area anchor — no unbounded nationwide scans
        # ponytail: Regrid caps at 4 ANDed field filters/call; keep the first 4
        # (location wins by insertion order) and defer the rest to the filter engine.
        params: dict = {"limit": min(f.limit, 1000), **dict(list(filters.items())[:4])}
        return [self._to_record(feat) for feat in _features(self._get("/parcels/query", params))]

    def parcel_boundary(self, lat: float, lng: float) -> dict | None:
        """GeoJSON Feature (Polygon/MultiPolygon geometry intact) at a point, for
        MapLibre. Returns the raw first feature — deliberately NOT reshaped so the
        frontend hands feature.geometry straight to a geojson source."""
        params = {"lat": round(lat, 6), "lon": round(lng, 6)}
        feats = _features(self._get("/parcels/point", params))
        return feats[0] if feats else None

    def tile_url(self) -> str:
        """MapLibre vector-tile template (source-layer 'parcels'), token embedded.
        ponytail: token is in the client-visible URL as the contract's MVT scheme
        requires — proxy it or issue a scoped tile token before shipping to prod."""
        return f"{_TILES}/parcels/{{z}}/{{x}}/{{y}}.mvt?token={settings.regrid_api_token}"
