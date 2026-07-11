"""Local filter engine — applies SearchFilters over already-cached records. This
is how OpenProp serves the ~30 cheap filters the paid tools charge for: the provider
search returns a coarse area set, and we refine it here for free (spec §2, §6).

Convention: when a filter constrains a field the record doesn't know (None), the
record is EXCLUDED — a lead list should not contain unverified matches."""
from .models import PropertyRecord, SearchFilters

_BOOL_FIELDS = [
    "absentee", "out_of_state", "owner_occupied", "corporate_owned",
    "high_equity", "tax_delinquent", "vacant", "pre_foreclosure",
]
_EQ_FIELDS = ["state", "county", "city", "zip"]


def _eq(a, b) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def matches(rec: PropertyRecord, f: SearchFilters) -> bool:
    r = rec.model_dump()

    for field in _EQ_FIELDS:
        want = getattr(f, field)
        if want is not None and (r.get(field) is None or not _eq(r[field], want)):
            return False

    if f.property_type is not None:
        pt = r.get("property_type")
        if pt is None or f.property_type.lower() not in pt.lower():
            return False

    # numeric min/max — unknown record value fails a set filter
    mins = {
        "beds": f.beds_min, "baths": f.baths_min, "year_built": f.year_built_min,
        "building_sqft": f.building_sqft_min, "lot_sqft": f.lot_sqft_min,
        "market_value": f.value_min, "assessed_value": f.assessed_value_min,
        "equity_pct": f.equity_pct_min, "years_owned": f.years_owned_min,
        "median_income": f.median_income_min,
    }
    for field, lo in mins.items():
        if lo is not None and (r.get(field) is None or r[field] < lo):
            return False

    maxes = {"year_built": f.year_built_max, "market_value": f.value_max}
    for field, hi in maxes.items():
        if hi is not None and (r.get(field) is None or r[field] > hi):
            return False

    for field in _BOOL_FIELDS:
        want = getattr(f, field)
        if want is not None and r.get(field) is not want:
            return False

    return True


def _completeness(rec: PropertyRecord) -> int:
    """How usable a row is as a lead. A coarse area listing mixes full assessor
    records with unit-level rows carrying nothing but an address (RentCast zip
    90007: only 73 of 500 rows have an owner). Truncating an unranked list at
    f.limit buries the usable ones, so rank before we cut."""
    return sum(bool(getattr(rec, k)) for k in
               ("owner_name", "assessed_value", "market_value", "year_built"))


def apply_filters(records: list[PropertyRecord], f: SearchFilters) -> list[PropertyRecord]:
    out = [r for r in records if matches(r, f)]
    out.sort(key=_completeness, reverse=True)  # stable: ties keep provider order
    return out[: f.limit]


def demo() -> None:
    recs = [
        PropertyRecord(address="1 A", state="TX", market_value=300_000, equity_pct=60,
                       absentee=True, property_type="Single Family"),
        PropertyRecord(address="2 B", state="TX", market_value=150_000, equity_pct=20,
                       absentee=False, property_type="Single Family"),
        PropertyRecord(address="3 C", state="CA", market_value=900_000, equity_pct=80,
                       absentee=True, property_type="Condo"),
        PropertyRecord(address="4 D", state="TX", absentee=True),  # unknown value/equity
    ]
    # absentee TX SFR with 50%+ equity, value <= 500k -> only "1 A"
    f = SearchFilters(state="TX", absentee=True, equity_pct_min=50, value_max=500_000,
                      property_type="single family")
    got = [r.address for r in apply_filters(recs, f)]
    assert got == ["1 A"], got

    # unknown-value record excluded by a value filter, kept without one
    assert [r.address for r in apply_filters(recs, SearchFilters(state="TX", absentee=True))] \
        == ["1 A", "4 D"]

    # explicit absentee=False selects only the owner-occupied one
    assert [r.address for r in apply_filters(recs, SearchFilters(absentee=False))] == ["2 B"]

    # limit truncates — and keeps the rows with data over the empty ones
    assert len(apply_filters(recs, SearchFilters(limit=2))) == 2
    thin = [PropertyRecord(address=f"empty {i}") for i in range(5)]
    rich = PropertyRecord(address="rich", owner_name="A Owner", assessed_value=100_000)
    assert [r.address for r in apply_filters(thin + [rich], SearchFilters(limit=1))] == ["rich"]
    print("filter_engine.demo OK")


if __name__ == "__main__":
    demo()
