"""Skip-trace client — OpenProp's pluggable owner-contact provider. Two vendors:

  batchdata — BatchData Property Skip Trace API (Bearer auth, sync JSON).
      POST https://api.batchdata.com/api/v1/property/skip-trace
  apify — an Apify skip-trace *actor* run synchronously (token in query param).
      POST https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items
      Default actor khadinakbar~skip-trace-property-owner: input = property
      address(es), output = owner name + phone_numbers[] + email_addresses[].
      Verified live: returns {owner_full_name, phone_numbers[], email_addresses[],
      owner_mailing_address, lookup_status, ...}.

SENSITIVE DATA: every result is PII returned under a DPPA/GLBA permissible-use
attestation. Stored locally only, never redistributed; the route enforces
confirm-before-spend before this is ever called (spec §8).

Per-hit cost = settings.skiptrace_cost_cents (also shown in the confirm dialog).
ponytail: misses are charged the full per-hit rate — a conservative upper bound
that keeps the budget guardrail protective."""
from datetime import datetime

import httpx

from ..cache import cached
from ..config import settings
from ..models import ContactRecord

_BATCHDATA_URL = "https://api.batchdata.com/api/v1/property/skip-trace"
_APIFY_BASE = "https://api.apify.com/v2/acts"
_TIMEOUT = 25.0
_APIFY_TIMEOUT = 240.0  # ponytail: Apify runs the actor synchronously (1-3 min);
#                         a long block is fine for occasional single-user use.


def _split_name(name: str) -> tuple[str, str] | tuple[None, None]:
    """last token = last name, the rest = first. Blank name -> (None, None)."""
    parts = (name or "").split()
    if not parts:
        return None, None
    return " ".join(parts[:-1]), parts[-1]


class GenericSkipTrace:
    def __init__(self, vendor: str):
        self._vendor = vendor

    def trace(self, name: str, address: str, city: str, state: str, zip: str) -> ContactRecord | None:
        if self._vendor == "batchdata":
            return self._trace_batchdata(name, address, city, state, zip)
        if self._vendor == "apify":
            return self._trace_apify(name, address, city, state, zip)
        raise NotImplementedError(
            f"skip-trace vendor {self._vendor!r} not supported; use 'batchdata' or 'apify'."
        )

    # --- BatchData -----------------------------------------------------------

    def _build_request(self, name, address, city, state, zip) -> dict:
        entry = {"propertyAddress": {"street": address, "city": city, "state": state, "zip": zip}}
        first, last = _split_name(name)
        if first or last:
            entry["name"] = {"first": first, "last": last}
        return {
            "requests": [entry],
            "options": {"skipTraceMatchType": "specific", "includeTCPABlacklistedPhones": False},
        }

    def _map_contact(self, person: dict) -> ContactRecord:
        nm = person.get("name") or {}
        person_name = nm.get("full") or " ".join(p for p in (nm.get("first"), nm.get("last")) if p) or None
        age = person.get("age")
        if age is None:
            year = (person.get("dob") or {}).get("year")
            if year:
                age = datetime.now().year - year
        phones = [
            {"number": p.get("number"), "type": p.get("type"), "carrier": p.get("carrier"),
             "is_connected": p.get("reachable"), "tested": p.get("tested"),
             "dnc": p.get("dnc"), "score": p.get("score")}
            for p in (person.get("phoneNumbers") or [])
        ]
        emails = [{"email": e.get("email"), "is_validated": e.get("tested")}
                  for e in (person.get("emails") or [])]
        addresses = [a for a in (person.get("propertyAddress"), person.get("mailingAddress")) if a]
        scores = [p["score"] for p in (person.get("phoneNumbers") or []) if p.get("score") is not None]
        identity_score = max(scores) / 100 if scores else None
        return ContactRecord(person_name=person_name, age=age, phones=phones, emails=emails,
                             addresses=addresses, identity_score=identity_score)

    def _trace_batchdata(self, name, address, city, state, zip) -> ContactRecord | None:
        req = self._build_request(name, address, city, state, zip)
        headers = {"Authorization": f"Bearer {settings.skiptrace_api_key}",
                   "Content-Type": "application/json", "Accept": "application/json"}

        def fetch():
            r = httpx.post(_BATCHDATA_URL, json=req, headers=headers, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()

        raw = cached("skiptrace", "batchdata", req, fetch, cost_cents=settings.skiptrace_cost_cents)
        persons = ((raw.get("results") or {}).get("persons")) or []
        return self._map_contact(persons[0]) if persons else None

    # --- Apify (actor run) ---------------------------------------------------

    @staticmethod
    def _one(v):
        """Apify phone/email arrays may hold bare strings or dicts — normalize."""
        return v if isinstance(v, dict) else {"value": v}

    def _map_apify(self, item: dict) -> ContactRecord | None:
        if not (item.get("owner_full_name") or item.get("phone_numbers") or item.get("email_addresses")):
            return None  # lookup_status "not_found" -> no match
        phones = [
            {"number": p} if isinstance(p, str)
            else {"number": p.get("number") or p.get("phone"), "type": p.get("type"), "dnc": p.get("dnc")}
            for p in (item.get("phone_numbers") or [])
        ]
        emails = [
            {"email": e} if isinstance(e, str) else {"email": e.get("email"), "is_validated": e.get("valid")}
            for e in (item.get("email_addresses") or [])
        ]
        ma = item.get("owner_mailing_address")
        addresses = []
        if ma:
            addresses.append(ma if isinstance(ma, dict) else {"street": ma})
        return ContactRecord(person_name=item.get("owner_full_name"), phones=phones,
                             emails=emails, addresses=addresses, identity_score=None)

    def _trace_apify(self, name, address, city, state, zip) -> ContactRecord | None:
        full = ", ".join(x for x in [address, city, f"{state} {zip}".strip()] if x and x.strip())
        body = {"addresses": [full], "includePhone": True, "includeEmail": True, "maxResults": 5}
        actor = settings.apify_actor

        def fetch():
            r = httpx.post(
                f"{_APIFY_BASE}/{actor}/run-sync-get-dataset-items",
                params={"token": settings.skiptrace_api_key},
                json=body, timeout=_APIFY_TIMEOUT,
            )
            r.raise_for_status()
            return r.json()

        items = cached("skiptrace", f"apify:{actor}", body, fetch, cost_cents=settings.skiptrace_cost_cents)
        return self._map_apify(items[0]) if items else None
