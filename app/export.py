"""CSV / XLSX export of a result set. stdlib csv for CSV; openpyxl for XLSX
(already a dependency). Column set is the fields an investor actually exports."""
import csv
import io

from .models import PropertyRecord

FIELDS = [
    "address", "city", "state", "zip", "apn", "property_type", "year_built",
    "beds", "baths", "building_sqft", "lot_sqft", "market_value", "assessed_value",
    "est_equity", "equity_pct", "tax_amount", "owner_name", "owner_mailing_addr",
    "owner_occupied", "absentee", "out_of_state", "corporate_owned", "high_equity",
    "tax_delinquent", "vacant", "pre_foreclosure", "flood_zone", "rent_estimate",
    "median_income", "source",
]


def to_csv(records: list[PropertyRecord]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in records:
        w.writerow(r.model_dump())
    return buf.getvalue().encode()


def to_xlsx(records: list[PropertyRecord]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "OpenProp export"
    ws.append(FIELDS)
    for r in records:
        d = r.model_dump()
        ws.append([d.get(f) for f in FIELDS])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
