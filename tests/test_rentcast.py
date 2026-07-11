"""RentCast mapping check — canned JSON, no network/key. Verifies the tricky bits:
latest-year tax extraction, owner-array join, org->corporate, and the 3-call
value/rent merge inside lookup(). Run: python -m tests.test_rentcast"""
from app.providers.rentcast import RentcastProvider, _latest

_PROPERTY = {
    "assessorID": "R12345",
    "formattedAddress": "123 Main St, Austin, TX 78701",
    "city": "Austin", "state": "TX", "zipCode": "78701",
    "latitude": 30.26, "longitude": -97.74,
    "propertyType": "Single Family", "zoning": "SF-3", "yearBuilt": 1998,
    "bedrooms": 3, "bathrooms": 2, "squareFootage": 1800, "lotSize": 6000,
    "taxAssessments": {"2022": {"value": 250000}, "2023": {"value": 300000}},
    "propertyTaxes": {"2022": {"total": 5000}, "2023": {"total": 5500}},
    "lastSaleDate": "2019-05-01", "lastSalePrice": 220000,
    "owner": {
        "names": ["ACME HOLDINGS LLC"], "type": "Organization",
        "mailingAddress": {"formattedAddress": "500 Park Ave, New York, NY 10022"},
    },
    "ownerOccupied": False,
}
_FAKE = {
    "/properties": [_PROPERTY],
    "/avm/value": {"price": 330000, "priceRangeLow": 300000, "comparables": [{"id": "c1"}]},
    "/avm/rent/long-term": {"rent": 2100, "rentRangeLow": 1900, "comparables": []},
}


def test_rentcast_mapping():
    assert _latest({"2022": {"value": 1}, "2023": {"value": 2}}, "value") == 2
    assert _latest(None, "value") is None

    from app.config import settings

    p = RentcastProvider()
    p._get = lambda path, params: _FAKE[path]  # bypass cache + network

    # default: AVM off -> 1 request, core record only (no market_value/rent) — spend-safe
    settings.rentcast_fetch_avm = False
    base = p.lookup("123 Main St, Austin, TX 78701")
    assert base.owner_name == "ACME HOLDINGS LLC" and base.assessed_value == 300000
    assert base.market_value is None and base.rent_estimate is None, "AVM must be opt-in"

    # AVM on -> value + rent merged from the 2 extra calls
    settings.rentcast_fetch_avm = True
    rec = p.lookup("123 Main St, Austin, TX 78701")
    settings.rentcast_fetch_avm = False  # restore default
    assert rec.apn == "R12345", rec.apn
    assert rec.corporate_owned is True and rec.owner_occupied is False
    assert rec.tax_amount == 5500
    assert rec.market_value == 330000                          # from /avm/value
    assert rec.rent_estimate == 2100                           # from /avm/rent
    assert rec.est_equity is None                              # honest gap: no loan data
    assert rec.building_sqft == 1800 and rec.year_built == 1998
    print("rentcast mapping OK (AVM opt-in + on)")


if __name__ == "__main__":
    test_rentcast_mapping()
    print("rentcast test OK")
