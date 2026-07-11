"""Contact-mapping + model-coercion checks for the fixes from the provider
review. No network. Run: python -m tests.test_providers"""
from app.models import PropertyRecord
from app.providers.reapi import ReapiSkipTrace
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


def test_float_to_int_coercion():
    # Regrid GIS sqft arrives fractional; PropertyRecord must not choke
    r = PropertyRecord(address="1 X", lot_sqft=1234.7, market_value=399999.4)
    assert r.lot_sqft == 1235 and r.market_value == 399999, (r.lot_sqft, r.market_value)
    print("float->int coercion OK")


if __name__ == "__main__":
    test_batchdata_mapping()
    test_apify_mapping()
    test_reapi_mapping()
    test_float_to_int_coercion()
    print("providers test OK")
