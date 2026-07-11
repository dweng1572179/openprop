"""Computed distress/ownership flags — the free half of the commercial flag set
(spec §3, principle #1). Pure functions over a normalized record. The paid-only
flags (foreclosure, lien, probate) come from a distress provider, not here."""
import re

_CORP = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|CO|COMPANY|LP|LLP|LTD|TRUST|HOLDINGS?|"
    r"PROPERTIES|PARTNERS|ASSOCIATES|ENTERPRISES|GROUP|CAPITAL|INVESTMENTS?)\b",
    re.I,
)
_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def owner_key(owner_name: str | None, owner_mailing: str | None) -> str | None:
    """Stable key for grouping an owner's portfolio across records. Requires a
    mailing address — a name alone would falsely merge distinct people who share
    a name (two "John Smith"s with no mailing become one portfolio)."""
    if not owner_name or not owner_mailing:
        return None
    return f"{_norm(owner_name)}|{_norm(owner_mailing)}"


def _state_from(addr: str | None) -> str | None:
    if not addr:
        return None
    # last 2-letter token that is a real state code (state usually precedes zip)
    for tok in reversed(re.findall(r"[A-Za-z]{2}", addr.upper())):
        if tok in _STATES:
            return tok
    return None


def compute_flags(rec: dict) -> dict:
    """Fill absentee / out_of_state / corporate_owned / equity_pct / high_equity
    from the fields a property provider gives us. Leaves a flag None when the
    inputs needed to decide it are missing (unknown != False)."""
    owner_occ = rec.get("owner_occupied")
    prop_addr, mail_addr = rec.get("address"), rec.get("owner_mailing_addr")

    if owner_occ is not None:
        rec["absentee"] = not owner_occ
    elif mail_addr and prop_addr:
        rec["absentee"] = _norm(mail_addr).find(_norm(prop_addr)) == -1

    prop_state = rec.get("state") or _state_from(prop_addr)
    mail_state = _state_from(mail_addr)
    if prop_state and mail_state:
        rec["out_of_state"] = mail_state != prop_state

    # regex is a fallback; an authoritative provider signal (e.g. owner.type) wins
    if rec.get("corporate_owned") is None and rec.get("owner_name"):
        rec["corporate_owned"] = bool(_CORP.search(rec["owner_name"]))

    mv, eq = rec.get("market_value"), rec.get("est_equity")
    if mv and eq is not None and mv > 0:
        rec["equity_pct"] = round(eq / mv * 100)
    if rec.get("equity_pct") is not None:
        rec["high_equity"] = rec["equity_pct"] >= 50

    rec["owner_key"] = owner_key(rec.get("owner_name"), mail_addr)
    return rec


def demo() -> None:
    # absentee via mailing-address mismatch + out-of-state + corporate + equity
    r = compute_flags({
        "address": "123 Main St", "city": "Austin", "state": "TX", "zip": "78701",
        "owner_name": "ACME HOLDINGS LLC",
        "owner_mailing_addr": "500 Park Ave, New York, NY 10022",
        "market_value": 400_000, "est_equity": 300_000,
    })
    assert r["absentee"] is True, r
    assert r["out_of_state"] is True, r
    assert r["corporate_owned"] is True, r
    assert r["equity_pct"] == 75 and r["high_equity"] is True, r

    # owner-occupied signal wins; individual owner; low equity
    r = compute_flags({
        "address": "9 Elm St", "state": "TX", "owner_occupied": True,
        "owner_name": "Jane Q Public", "owner_mailing_addr": "9 Elm St, Austin, TX 78701",
        "market_value": 200_000, "est_equity": 20_000,
    })
    assert r["absentee"] is False, r
    assert r["corporate_owned"] is False, r
    assert r["out_of_state"] is False, r
    assert r["equity_pct"] == 10 and r["high_equity"] is False, r

    # unknowns stay unknown, not False
    r = compute_flags({"address": "1 X", "owner_name": None})
    assert r.get("absentee") is None and r.get("out_of_state") is None, r
    print("flags.demo OK")


if __name__ == "__main__":
    demo()
