"""HUD Fair Market Rents — rent benchmark by bedroom count for a property's area.
FREE but requires a Bearer token (register at huduser.gov/hudapi/public/register).
Verified contract:
  GET /data/{entityid}?year=YYYY   entityid = {5-digit county FIPS}99999
  response.data.basicdata is polymorphic: an object when smallarea_status==0,
  a per-ZIP array when ==1. Field names are hyphenated ("One-Bedroom")."""
import datetime

import httpx

from ..cache import cached
from ..config import settings

_BASE = "https://www.huduser.gov/hudapi/public/fmr"
_TIMEOUT = 20.0
_BEDS = {  # OpenProp bed-count key <- HUD field
    "0": "Efficiency", "1": "One-Bedroom", "2": "Two-Bedroom",
    "3": "Three-Bedroom", "4": "Four-Bedroom",
}


def _fiscal_year() -> int:
    now = datetime.date.today()
    return now.year + 1 if now.month >= 10 else now.year  # FMRs effective ~Oct 1


class HudFmrProvider:
    def fmr(self, zip: str | None, fips: str | None) -> dict[str, int] | None:
        if not fips or len(fips) != 5:
            return None
        entity = f"{fips}99999"
        year = _fiscal_year()

        def fetch():
            r = httpx.get(
                f"{_BASE}/data/{entity}",
                params={"year": year},
                headers={"Authorization": f"Bearer {settings.hud_fmr_token}"},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            return r.json()

        data = cached("hud", "fmr", {"e": entity, "y": year}, fetch, cost_cents=0)
        block = (data.get("data") or {})
        basic = block.get("basicdata")
        if isinstance(basic, list):  # Small Area FMR — pick the property's ZIP
            basic = next((b for b in basic if str(b.get("zip_code")) == str(zip)), None) \
                or (basic[0] if basic else None)
        if not isinstance(basic, dict):
            return None
        out = {k: basic[hud] for k, hud in _BEDS.items() if basic.get(hud) is not None}
        return out or None
