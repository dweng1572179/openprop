"""AI layer — four features the big property tools charge extra for, powered
by one BYO Anthropic key. Structured features (NL->filters, lead score) use
messages.parse() for schema-validated output; prose features (brief, outreach)
use plain messages. With no key set, nl_to_filters falls back to a rules-based
parser so AI Search still works offline; the prose features return None."""
import re

from pydantic import BaseModel

from .config import settings
from .models import SearchFilters


class LeadScore(BaseModel):
    score: int          # 0-100 motivation score
    reasons: list[str]  # explainable signals


class FilterExtract(BaseModel):
    """Lean subset of SearchFilters for the LLM — the fields people actually say
    in a query. Kept under structured-outputs' 24-optional-field cap (SearchFilters
    has 26); merged back into a full SearchFilters after extraction."""
    state: str | None = None
    city: str | None = None
    zip: str | None = None
    property_type: str | None = None
    beds_min: float | None = None
    year_built_min: int | None = None
    year_built_max: int | None = None
    value_min: int | None = None
    value_max: int | None = None
    equity_pct_min: int | None = None
    years_owned_min: int | None = None
    absentee: bool | None = None
    out_of_state: bool | None = None
    owner_occupied: bool | None = None
    corporate_owned: bool | None = None
    high_equity: bool | None = None
    tax_delinquent: bool | None = None
    vacant: bool | None = None
    pre_foreclosure: bool | None = None
    median_income_min: int | None = None

_MODEL = settings.llm_model


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


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
                    "filters. Only set fields the query explicitly implies; leave the rest null. "
                    "State must be a 2-letter code."),
            messages=[{"role": "user", "content": query}],
            output_format=FilterExtract,
        )
        # merge the lean extraction into a full SearchFilters (limit defaults to 100)
        return SearchFilters(**resp.parsed_output.model_dump(exclude_none=True))
    except Exception:  # noqa: BLE001 — any parse/API failure degrades to rules
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
