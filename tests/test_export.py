"""Export check — CSV header/rows + XLSX is a real workbook. python -m tests.test_export"""
from app.export import FIELDS, to_csv, to_xlsx
from app.models import PropertyRecord


def test_export():
    recs = [
        PropertyRecord(address="1 A St", city="Austin", state="TX", market_value=300000,
                       owner_name="ACME LLC", absentee=True),
        PropertyRecord(address="2 B St", city="Dallas", state="TX", market_value=None),
    ]
    csv_bytes = to_csv(recs)
    text = csv_bytes.decode()
    assert text.splitlines()[0] == ",".join(FIELDS)          # header
    assert "1 A St" in text and "ACME LLC" in text and "2 B St" in text
    assert len(text.splitlines()) == 3                        # header + 2 rows

    xlsx = to_xlsx(recs)
    assert xlsx[:2] == b"PK"                                  # xlsx == zip container
    assert len(xlsx) > 500
    print("export OK")


if __name__ == "__main__":
    test_export()
    print("export test OK")
