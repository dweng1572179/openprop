"""FEMA National Flood Hazard Layer — flood zone by lat/lng. FREE, no key.
Live-verified contract (2026-07-10). Landmines, all handled below:
  - geometry is LONGITUDE,LATITUDE (x,y) — reversing it silently misses
  - must send inSR=4326 or ArcGIS treats lat/lng as Web Mercator meters
  - layer 28 (polygons), not 27 (lines); legacy /gis/nfhl/ base is dead
  - empty features[] == unmapped point, NOT zone X
  - can return HTML during outages — verify JSON before trusting it"""
import httpx

from ..cache import cached

_URL = ("https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query")
_UA = {"User-Agent": "OpenProp/0.1 (self-hosted property tool)"}
_TIMEOUT = 20.0


class FemaFloodProvider:
    def flood_zone(self, lat: float, lng: float) -> str | None:
        def fetch():
            params = {
                "geometry": f"{lng},{lat}",          # x,y = lng,lat
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
                "returnGeometry": "false",
                "f": "json",
            }
            r = httpx.get(_URL, params=params, headers=_UA, timeout=_TIMEOUT)
            r.raise_for_status()
            if "json" not in r.headers.get("content-type", ""):
                raise ValueError("FEMA NFHL returned non-JSON (service outage?)")
            return r.json()

        data = cached("fema", "flood_zone", {"lat": round(lat, 6), "lng": round(lng, 6)},
                      fetch, cost_cents=0)
        feats = data.get("features") or []
        if not feats:
            return None  # unmapped point — do not assume "X"
        return (feats[0].get("attributes") or {}).get("FLD_ZONE")
