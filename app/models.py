"""Normalized domain models. Every provider maps INTO these so the app never
sees a provider-specific shape. Distress flags follow the common investor taxonomy;
the ones we compute for free are filled locally (see flags.py)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PropertyRecord(BaseModel):
    # identity / location
    id: int | None = None
    apn: str | None = None
    address: str
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    lat: float | None = None
    lng: float | None = None
    fips: str | None = None  # from geocoder; keys ACS + county sources

    # physical
    property_type: str | None = None
    land_use: str | None = None
    year_built: int | None = None
    beds: float | None = None
    baths: float | None = None
    building_sqft: int | None = None
    lot_sqft: int | None = None

    # valuation / tax
    assessed_value: int | None = None
    market_value: int | None = None      # AVM
    est_loan_balance: int | None = None
    est_equity: int | None = None        # market_value - est_loan_balance
    equity_pct: int | None = None        # 0..100, computed
    tax_amount: int | None = None
    last_sale_date: str | None = None
    last_sale_price: int | None = None

    # owner
    owner_name: str | None = None
    owner_mailing_addr: str | None = None
    owner_occupied: bool | None = None
    years_owned: int | None = None

    # computed ownership flags (flags.py)
    absentee: bool | None = None
    out_of_state: bool | None = None
    corporate_owned: bool | None = None

    # distress — free-computed + optional paid unlock (reapi). None = unknown.
    high_equity: bool | None = None
    tax_delinquent: bool | None = None
    vacant: bool | None = None
    pre_foreclosure: bool | None = None
    foreclosure: bool | None = None
    auction: bool | None = None
    lien: bool | None = None
    probate: bool | None = None

    # enrichment
    flood_zone: str | None = None
    rent_estimate: int | None = None
    fmr_by_bed: dict[str, int] | None = None  # HUD FMR: {"0": 1200, "1": ...}
    median_income: int | None = None

    source: str | None = None  # which provider produced the base record

    # Providers hand us GIS/assessor numbers that can arrive as fractional floats
    # (e.g. Regrid's ll_gissqft); Pydantic v2 rejects those for int fields, which
    # would abort a lookup. Round them here once for every provider.
    @field_validator(
        "year_built", "building_sqft", "lot_sqft", "assessed_value", "market_value",
        "est_loan_balance", "est_equity", "tax_amount", "last_sale_price",
        "rent_estimate", "median_income", mode="before",
    )
    @classmethod
    def _round_floats_to_int(cls, v):
        # providers send numbers as floats (Regrid GIS) AND as decimal strings
        # (REAPI tax_amount "4078.92") — round both to int; leave the rest for pydantic.
        if isinstance(v, float):
            return round(v)
        if isinstance(v, str):
            try:
                return round(float(v))
            except ValueError:
                return v
        return v


class SearchFilters(BaseModel):
    """The subset of the ~87 commercial filter fields OpenProp can serve cheaply.
    Anything provider-native goes to the provider search; the rest is applied
    by the local filter engine over cached records."""
    # location
    state: str | None = None
    county: str | None = None
    city: str | None = None
    zip: str | None = None

    # physical
    property_type: str | None = None
    beds_min: float | None = None
    baths_min: float | None = None
    year_built_min: int | None = None
    year_built_max: int | None = None
    building_sqft_min: int | None = None
    lot_sqft_min: int | None = None

    # value / tax / equity
    value_min: int | None = None
    value_max: int | None = None
    assessed_value_min: int | None = None
    equity_pct_min: int | None = None
    years_owned_min: int | None = None

    # flags (locally computed or provider-native)
    absentee: bool | None = None
    out_of_state: bool | None = None
    owner_occupied: bool | None = None
    corporate_owned: bool | None = None
    high_equity: bool | None = None
    tax_delinquent: bool | None = None
    vacant: bool | None = None
    pre_foreclosure: bool | None = None

    # demographics
    median_income_min: int | None = None

    limit: int = 100


class ContactRecord(BaseModel):
    """Skip-trace result. Sensitive — stored locally only, never redistributed."""
    person_name: str | None = None
    age: int | None = None
    phones: list[dict] = Field(default_factory=list)   # {number,type,is_connected,...}
    emails: list[dict] = Field(default_factory=list)   # {email,is_validated,...}
    addresses: list[dict] = Field(default_factory=list)
    identity_score: float | None = None


class Note(BaseModel):
    id: int | None = None
    property_id: int
    body: str
    created_at: str | None = None


class SavedSearch(BaseModel):
    id: int | None = None
    name: str
    filters: SearchFilters
    created_at: str | None = None
