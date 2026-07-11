"""US Census — geocoding + ACS demographics. Both FREE (no key needed at low
volume). Geocoder returns coordinates + FIPS geographies; ACS gives median
household income by county. Verified live in the provider-research pass."""
import httpx

from ..cache import cached
from ..config import settings

_GEO = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
_ACS = "https://api.census.gov/data/2022/acs/acs5"
_UA = {"User-Agent": "OpenProp/0.1 (self-hosted property tool)"}
_TIMEOUT = 20.0


class CensusGeocoder:
    """address -> {lat, lng, matched_address, state, city, zip, county_fips, tract_geoid}."""

    def geocode(self, address: str) -> dict | None:
        def fetch():
            params = {
                "address": address,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "format": "json",
            }
            r = httpx.get(_GEO, params=params, headers=_UA, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()

        data = cached("census", "geocode", {"a": address}, fetch, cost_cents=0)
        matches = (data.get("result") or {}).get("addressMatches") or []
        if not matches:
            return None
        m = matches[0]
        c = m.get("coordinates") or {}
        comp = m.get("addressComponents") or {}
        geos = m.get("geographies") or {}
        county = (geos.get("Counties") or [{}])[0]
        tract = (geos.get("Census Tracts") or [{}])[0]
        county_fips = None
        if county.get("STATE") and county.get("COUNTY"):
            county_fips = f"{county['STATE']}{county['COUNTY']}"
        return {
            "matched_address": m.get("matchedAddress"),
            "lat": c.get("y"),
            "lng": c.get("x"),
            "state": comp.get("state"),
            "city": comp.get("city"),
            "zip": comp.get("zip"),
            "county_fips": county_fips,
            "tract_geoid": tract.get("GEOID"),
        }


class CensusAcs:
    """Median household income by 5-digit county FIPS (ACS5 B19013_001E)."""

    def median_income(self, county_fips: str | None) -> int | None:
        # ACS now 302-redirects to missing_key.html without a key — skip the call.
        if not settings.census_api_key or not county_fips or len(county_fips) != 5:
            return None
        state, county = county_fips[:2], county_fips[2:]

        def fetch():
            params = {
                "get": "B19013_001E", "for": f"county:{county}",
                "in": f"state:{state}", "key": settings.census_api_key,
            }
            r = httpx.get(_ACS, params=params, headers=_UA, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()

        rows = cached("census", "acs_income", {"f": county_fips}, fetch, cost_cents=0)
        try:
            val = int(rows[1][0])
            return val if val > 0 else None  # ACS uses negative sentinels for N/A
        except (IndexError, ValueError, TypeError):
            return None
