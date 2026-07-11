"""Contact-mapping + model-coercion checks for the fixes from the provider
review. No network. Run: python -m tests.test_providers"""
from app.models import PropertyRecord
from app.providers.reapi import ReapiProvider, ReapiSkipTrace
from app.providers.skiptrace import GenericSkipTrace

_BATCHDATA_PERSON = {
    "name": {"full": "Jane Q Public"},
    "age": 51,
    "phoneNumbers": [
        {"number": "512-555-0100", "type": "Mobile", "carrier": "AT&T",
         "reachable": True, "tested": True, "dnc": False, "score": 92},
        {"number": "512-555-0111", "type": "Landline", "reachable": False, "score": 40},
    ],
    "emails": [{"email": "jane@example.com", "tested": True}],
    "propertyAddress": {"street": "123 Main St", "city": "Austin", "state": "TX", "zip": "78701"},
    "mailingAddress": {"street": "500 Park Ave", "city": "New York", "state": "NY", "zip": "10022"},
}


def test_batchdata_mapping():
    c = GenericSkipTrace("batchdata")._map_contact(_BATCHDATA_PERSON)
    assert c.person_name == "Jane Q Public" and c.age == 51
    assert c.identity_score == 0.92, c.identity_score          # max phone score / 100
    ph = c.phones[0]
    assert "dnc" in ph and "tested" in ph and "carrier" in ph, ph  # keys _contact.html reads
    # both property + mailing addresses present (property was the review's must-fix)
    streets = [a.get("street") for a in c.addresses]
    assert streets == ["123 Main St", "500 Park Ave"], streets
    print("batchdata mapping OK")


_APIFY_ITEM = {  # matches the live khadinakbar/skip-trace-property-owner output schema
    "property_address": "123 Main St, Austin, TX 78701",
    "owner_full_name": "Jane Q Public",
    "owner_mailing_address": "500 Park Ave, New York, NY 10022",
    "phone_numbers": ["512-555-0100", {"number": "512-555-0111", "type": "Landline"}],
    "email_addresses": ["jane@example.com"],
    "lookup_status": "found",
}


def test_apify_mapping():
    st = GenericSkipTrace("apify")
    # not_found (empty arrays) -> None, verified live
    assert st._map_apify({"lookup_status": "not_found", "phone_numbers": [], "email_addresses": []}) is None
    r = st._map_apify(_APIFY_ITEM)
    assert r.person_name == "Jane Q Public"
    assert r.phones[0]["number"] == "512-555-0100"     # bare-string phone
    assert r.phones[1]["number"] == "512-555-0111"     # dict phone
    assert r.emails[0]["email"] == "jane@example.com"
    assert "500 Park Ave" in r.addresses[0]["street"]  # key _contact.html reads
    print("apify mapping OK")


def test_reapi_mapping():
    st = ReapiSkipTrace()
    ph = st._map_phone({"phone": "212-555-9000", "phoneType": "wireless", "phoneFtcDnc": True})
    assert ph["dnc"] is True and "doNotCall" not in ph, ph      # template reads p.dnc
    a = st._map_address({"streetAddress": "9 Elm St", "city": "Dallas", "state": "TX", "zip": "75001"})
    assert a["street"] == "9 Elm St", a                          # template reads a.street
    print("reapi mapping OK")


# A REAPI PropertySearch row is FLAT — trimmed from a live zip-90007 response.
# PropertyDetail nests the same data under propertyInfo/ownerInfo/taxInfo instead,
# and reading only those blocks silently blanked every search row.
_REAPI_SEARCH_ROW = {
    "address": {"address": "1183 W 24th St", "city": "Los Angeles", "state": "CA", "zip": "90007"},
    "apn": "5054-024-002",
    "companyName": "Bellamar Llc",
    "corporateOwned": True,
    "absenteeOwner": True,
    "assessedValue": 349965,
    "estimatedValue": 1578000,
    "estimatedEquity": 1578000,
    "equity": False,           # BOOLEAN filter bit — never the dollar amount
    "equityPercent": 100,
    "openMortgageBalance": 0,
    "squareFeet": 2100,        # NOT livingSquareFeet
    "lastSaleAmount": "5000000",
    "yearBuilt": 1923,
    "vacant": False,
    "preForeclosure": False,
}


def test_reapi_search_row_is_flat():
    rec = ReapiProvider.__new__(ReapiProvider)._to_record(_REAPI_SEARCH_ROW)
    assert rec.owner_name == "Bellamar Llc", rec.owner_name
    assert rec.assessed_value == 349965 and rec.market_value == 1578000
    assert rec.building_sqft == 2100 and rec.year_built == 1923
    assert rec.apn == "5054-024-002" and rec.corporate_owned is True
    # the $0-equity bug: `equity` is False here, so reading it as the amount gave 0
    assert rec.est_equity == 1578000, rec.est_equity
    assert rec.equity_pct == 100
    assert rec.last_sale_price == 5000000, rec.last_sale_price
    print("reapi flat search-row mapping OK")


def test_reapi_nested_detail_still_maps():
    """The PropertyDetail shape must keep working — the flat fallbacks are additive."""
    detail = {
        "propertyInfo": {"address": {"label": "9 Elm St", "city": "Dallas", "state": "TX", "zip": "75001"},
                         "yearBuilt": 1998, "bedrooms": 3, "livingSquareFeet": 1800},
        "ownerInfo": {"owner1FullName": "Jane Q Public", "corporateOwned": False},
        "taxInfo": {"assessedValue": 250000},
        "estimatedValue": 400000, "estimatedEquity": 150000, "equityPercent": 37.5,
    }
    rec = ReapiProvider.__new__(ReapiProvider)._to_record(detail)
    assert rec.owner_name == "Jane Q Public" and rec.address == "9 Elm St"
    assert rec.year_built == 1998 and rec.beds == 3 and rec.building_sqft == 1800
    assert rec.assessed_value == 250000 and rec.est_equity == 150000
    assert rec.equity_pct == 38, rec.equity_pct  # rounded
    print("reapi nested detail mapping OK")


def test_reapi_search_body_uses_real_filter_keys():
    """Every key here was probed against the live API. `tax_delinquent` is NOT a
    REAPI key — sending it 400s ('tax_delinquent is not allowed') and takes the
    whole search down, so the filter must go out as `tax_lien`."""
    from app.models import SearchFilters
    body = ReapiProvider.__new__(ReapiProvider)._search_body(
        SearchFilters(state="TX", city="San Antonio", tax_delinquent=True,
                      pre_foreclosure=True, vacant=True, equity_pct_min=40, limit=5))
    assert "tax_delinquent" not in body, "tax_delinquent is a 400 — must map to tax_lien"
    assert body["tax_lien"] is True
    # the rest of the keys, as accepted by the live endpoint
    assert body["equity_percent_min"] == 40 and body["pre_foreclosure"] is True
    assert body["size"] == 5
    print("reapi search-body filter keys OK")


def test_float_to_int_coercion():
    # Regrid GIS sqft arrives fractional; PropertyRecord must not choke
    r = PropertyRecord(address="1 X", lot_sqft=1234.7, market_value=399999.4)
    assert r.lot_sqft == 1235 and r.market_value == 399999, (r.lot_sqft, r.market_value)
    print("float->int coercion OK")




def test_filter_extract_schema_is_grammar_safe():
    """Pins the two rules that make structured outputs work — both were real bugs
    that silently degraded every AI search to the rules parser:
      1. >16 union-typed (nullable) params -> hard 400.
      2. any OPTIONAL param (a field with a default) -> 2^N grammar shapes -> the
         request HANGS past the timeout instead of erroring.
    No network: this reads the JSON schema the SDK would send."""
    from app.ai import FilterExtract
    s = FilterExtract.model_json_schema()
    props, required = s["properties"], set(s.get("required") or [])

    unions = [k for k, v in props.items() if "anyOf" in v or isinstance(v.get("type"), list)]
    assert not unions, f"union/nullable params 400 the API (limit 16): {unions}"

    optional = [k for k in props if k not in required]
    assert not optional, f"optional params explode grammar compilation -> hang: {optional}"
    print("FilterExtract schema is grammar-safe OK")


if __name__ == "__main__":
    test_batchdata_mapping()
    test_apify_mapping()
    test_reapi_mapping()
    test_reapi_search_row_is_flat()
    test_reapi_nested_detail_still_maps()
    test_reapi_search_body_uses_real_filter_keys()
    test_float_to_int_coercion()
    test_filter_extract_schema_is_grammar_safe()
    print("providers test OK")
