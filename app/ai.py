"""AI layer — four features the big property tools charge extra for, powered
by one BYO Anthropic key. Structured features (NL->filters, lead score) use
messages.parse() for schema-validated output; prose features (brief, outreach)
use plain messages. With no key set, nl_to_filters falls back to a rules-based
parser so AI Search still works offline; the prose features return None."""
import logging
import re
from typing import Literal

from pydantic import BaseModel

from .config import settings
from .models import SearchFilters

log = logging.getLogger("openprop")


class LeadScore(BaseModel):
    score: int          # 0-100 motivation score
    reasons: list[str]  # explainable signals


_UNSET = ""          # a field the query didn't mention
_Flag = Literal["", "yes", "no"]


class FilterExtract(BaseModel):
    """Lean subset of SearchFilters for the LLM, merged back into a full
    SearchFilters after extraction.

    Two rules here are load-bearing, not style — both were learned the hard way:

    1. NO `| None`. Structured outputs reject >16 union-typed (nullable) params
       ("too many parameters with union types ... limit: 16"). These 20 fields as
       `X | None` = 20 unions = a hard 400.
    2. NO DEFAULTS — every field is REQUIRED. A default makes a field *optional* in
       the JSON schema, and each optional field is a present/absent branch, so 20 of
       them is 2^20 shapes for the grammar compiler: the request doesn't 400, it just
       HANGS (>75s, times out) on every model, Haiku included. All-required = one
       shape = 5s.

    Either mistake lands in the same place: nl_to_filters catches, falls back to the
    rules parser, and the AI search silently drops constraints the user actually typed
    ("San Antonio", "under $400k") while still looking like it worked.

    So: sentinels, not nulls. "" / 0 mean "not mentioned". Flags are a 3-state enum
    so "not absentee" stays distinguishable from "absentee not mentioned"."""
    state: str
    city: str
    zip: str
    property_type: str
    beds_min: float
    year_built_min: int
    year_built_max: int
    value_min: int
    value_max: int
    equity_pct_min: int
    years_owned_min: int
    median_income_min: int
    absentee: _Flag
    out_of_state: _Flag
    owner_occupied: _Flag
    corporate_owned: _Flag
    high_equity: _Flag
    tax_delinquent: _Flag
    vacant: _Flag
    pre_foreclosure: _Flag

    def to_filters(self) -> SearchFilters:
        """Sentinels -> None, so unmentioned fields don't become real filters."""
        out: dict = {}
        for k, v in self.model_dump().items():
            if v in ("", 0):
                continue                      # not mentioned
            out[k] = {"yes": True, "no": False}.get(v, v) if isinstance(v, str) else v
        return SearchFilters(**out)

_MODEL = settings.llm_model


def _client():
    import anthropic
    # bounded: the SDK default is 10min, so a bad schema/outage froze the request
    # instead of degrading to the rules parser.
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)


def available() -> bool:
    return bool(settings.anthropic_api_key)


# --- 1. NL -> filters (AI Search) -------------------------------------------

_PT = {"single family": "Single Family", "single-family": "Single Family",
       "sfr": "Single Family", "condo": "Condo", "townhouse": "Townhouse",
       "multi family": "Multi-Family", "multifamily": "Multi-Family",
       "duplex": "Duplex", "mobile": "Mobile Home"}
_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}


def _rules_parse(query: str) -> SearchFilters:
    """Keyword fallback — covers the common investor-list phrasings."""
    q = query.lower()
    f = SearchFilters()
    if "absentee" in q:
        f.absentee = True
    if "out of state" in q or "out-of-state" in q:
        f.out_of_state = True
    if "owner occupied" in q or "owner-occupied" in q:
        f.owner_occupied = True
    if "vacant" in q:
        f.vacant = True
    if "corporate" in q or "llc" in q:
        f.corporate_owned = True
    if "tax delinquent" in q or "tax-delinquent" in q:
        f.tax_delinquent = True
    if "pre-foreclosure" in q or "preforeclosure" in q or "pre foreclosure" in q:
        f.pre_foreclosure = True
    if "high equity" in q:
        f.high_equity = True
    for k, v in _PT.items():
        if k in q:
            f.property_type = v
            break
    if m := re.search(r"(\d+)\s*%?\s*(?:\+|or more|plus|and up)?\s*equity", q):
        f.equity_pct_min = int(m.group(1))
    elif m := re.search(r"equity (?:over|above|of at least|>=?)\s*(\d+)", q):
        f.equity_pct_min = int(m.group(1))
    if m := re.search(r"(?:under|below|less than|<)\s*\$?([\d,]{4,})", q):
        f.value_max = int(m.group(1).replace(",", ""))
    if m := re.search(r"(?:over|above|more than|>)\s*\$?([\d,]{4,})", q):
        f.value_min = int(m.group(1).replace(",", ""))
    if m := re.search(r"\b(\d{5})\b", query):
        f.zip = m.group(1)
    # uppercase-only so the word "in" isn't read as Indiana ("... homes in TX")
    for tok in re.findall(r"\b([A-Z]{2})\b", query):
        if tok in _STATES:
            f.state = tok
            break
    return f


def nl_to_filters(query: str) -> SearchFilters:
    if not available():
        return _rules_parse(query)
    try:
        resp = _client().messages.parse(
            model=_MODEL, max_tokens=1024,
            system=("Convert the user's plain-English real-estate search into structured "
                    "filters. Every field is required: use \"\" for text/flags and 0 for "
                    "numbers the query does not mention. Set a flag to \"yes\"/\"no\" only "
                    "when the query says so. State must be a 2-letter code."),
            messages=[{"role": "user", "content": query}],
            output_format=FilterExtract,
        )
        # merge the lean extraction into a full SearchFilters (limit defaults to 100)
        return resp.parsed_output.to_filters()
    except Exception as e:  # noqa: BLE001 — any parse/API failure degrades to rules
        # LOUDLY: a silent fallback here hid a 400 for the entire life of the app and
        # made every AI search quietly drop half the user's query. Degrade, but say so.
        log.warning("AI filter extraction failed (%s) — falling back to the rules parser, "
                    "which understands far less of the query: %s", type(e).__name__, e)
        return _rules_parse(query)


# --- 2. Property brief · 3. lead score · 4. outreach ------------------------

def _facts(p: dict) -> str:
    keep = ["address", "city", "state", "property_type", "year_built", "beds", "baths",
            "market_value", "est_equity", "equity_pct", "owner_name", "owner_occupied",
            "absentee", "out_of_state", "corporate_owned", "high_equity", "tax_delinquent",
            "vacant", "pre_foreclosure", "years_owned", "rent_estimate", "flood_zone"]
    return "\n".join(f"{k}: {p[k]}" for k in keep if p.get(k) is not None)


def brief(p: dict) -> str | None:
    if not available():
        return None
    resp = _client().messages.create(
        model=_MODEL, max_tokens=400,
        system="You are a real-estate investment analyst. Write ONE plain-English paragraph "
               "triaging this property + owner for a wholesaler: situation, motivation signals, "
               "and whether it's worth a call. No preamble.",
        messages=[{"role": "user", "content": _facts(p)}],
    )
    return next((b.text for b in resp.content if b.type == "text"), None)


def score_lead(p: dict) -> dict | None:
    if not available():
        return None
    try:
        resp = _client().messages.parse(
            model=_MODEL, max_tokens=512,
            system="Score this property owner's likely motivation to sell, 0-100 (higher = more "
                   "motivated), from distress/equity/absentee/ownership-length signals. Give a "
                   "short explainable reason list.",
            messages=[{"role": "user", "content": _facts(p)}],
            output_format=LeadScore,
        )
        return resp.parsed_output.model_dump()
    except Exception:  # noqa: BLE001
        return None


def outreach(p: dict, channel: str = "letter") -> str | None:
    if not available():
        return None
    resp = _client().messages.create(
        model=_MODEL, max_tokens=600,
        system=f"Draft a brief, warm first-touch {channel} from a real-estate investor to this "
               f"property owner expressing interest in buying. Compliant tone, no pressure, no "
               f"false urgency. The user sends it themselves (TCPA/CAN-SPAM apply).",
        messages=[{"role": "user", "content": _facts(p)}],
    )
    return next((b.text for b in resp.content if b.type == "text"), None)


def demo() -> None:
    # rules fallback works with no key
    f = _rules_parse("vacant absentee single family homes in TX with 50%+ equity under $400,000")
    assert f.vacant and f.absentee and f.state == "TX", f
    assert f.property_type == "Single Family" and f.equity_pct_min == 50 and f.value_max == 400000, f

    # structured outputs cap optional params at 24 — the LLM extraction schema must
    # stay under it or messages.parse 400s (SearchFilters itself has 26, hence the split).
    assert len(FilterExtract.model_fields) <= 24, len(FilterExtract.model_fields)
    print("ai.demo (rules fallback) OK")


if __name__ == "__main__":
    demo()
