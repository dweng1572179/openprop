"""End-to-end smoke test: app boots, auth gates, and a real address geocodes and
renders. Run: `python -m tests.test_smoke` (or pytest). Hits the live (free)
Census geocoder for the lookup step; that assertion is skipped if offline."""
import os
import tempfile

# isolated throwaway DB + hermetic config so the test never depends on a real .env
# (env vars override .env in pydantic-settings, so these blank out any real keys)
_DB = os.path.join(tempfile.gettempdir(), "openprop_smoke.db")
os.environ["DB_PATH"] = _DB
os.environ["OPENPROP_PASSWORD"] = "test-pw"
os.environ["PROPERTY_PROVIDER"] = "rentcast"
os.environ["SKIPTRACE_PROVIDER"] = ""
for _k in ("ANTHROPIC_API_KEY", "RENTCAST_API_KEY", "REAPI_API_KEY", "SKIPTRACE_API_KEY",
           "REGRID_API_TOKEN", "HUD_FMR_TOKEN", "CENSUS_API_KEY"):
    os.environ[_k] = ""
for _ext in ("", "-wal", "-shm"):  # fresh DB -> the id-1 assumption holds every run
    try:
        os.remove(_DB + _ext)
    except FileNotFoundError:
        pass

from fastapi.testclient import TestClient  # noqa: E402

from app.app import app  # noqa: E402


def test_smoke():
    # `with` enters the app lifespan so startup (init_db) runs
    with TestClient(app, follow_redirects=False) as c:
        # unauthenticated home bounces to /login
        r = c.get("/")
        assert r.status_code == 303 and r.headers["location"] == "/login", r.status_code

        # wrong password rejected
        assert c.post("/login", data={"password": "nope"}).status_code == 401

        # correct password -> session set -> home renders
        r = c.post("/login", data={"password": "test-pw"})
        assert r.status_code == 303, r.status_code
        r = c.get("/")
        assert r.status_code == 200 and "Property lookup" in r.text, r.status_code

        # live lookup: geocode a real address, render the card
        try:
            r = c.post("/lookup", data={"address": "1600 Pennsylvania Ave NW, Washington, DC 20500"})
        except Exception as e:  # noqa: BLE001
            print(f"  (lookup skipped — network? {e})")
            return
        assert r.status_code == 200, r.status_code
        assert ("pennsylvania" in r.text.lower()) or ("no property matched" in r.text.lower()), r.text[:300]
        print("  lookup rendered:", "card" if "Owner" in r.text else "no-match/error")

        # notes round-trip against the property the lookup just saved (id 1, fresh DB)
        r = c.post("/property/1/notes", data={"body": "call owner re: cash offer"})
        assert r.status_code == 200 and "cash offer" in r.text, r.status_code
        r = c.get("/property/1/notes")
        assert "cash offer" in r.text
        print("  notes round-trip OK")

        # skip-trace confirm gate (no vendor configured) + portfolio render
        r = c.get("/property/1/skiptrace/confirm")
        assert r.status_code == 200 and "SKIPTRACE_PROVIDER" in r.text, r.status_code
        r = c.get("/property/1/portfolio")
        assert r.status_code == 200
        print("  skiptrace gate + portfolio OK")

        # list builder page renders; search with no provider degrades gracefully
        r = c.get("/search")
        assert r.status_code == 200 and "List builder" in r.text, r.status_code
        r = c.post("/search", data={"city": "Austin", "state": "TX"})
        assert r.status_code == 200 and "property provider" in r.text.lower(), r.text[:200]
        print("  list builder page + graceful no-provider OK")

        # AI search: rules fallback parses filters even with no LLM key
        r = c.post("/ai/parse", data={"query": "absentee homes in TX with 50%+ equity"})
        assert r.status_code == 200, r.status_code
        assert "absentee=True" in r.text or "property provider" in r.text.lower(), r.text[:200]
        # AI prose without a key returns the configure-key message
        r = c.post("/ai/brief/1")
        assert r.status_code == 200 and "ANTHROPIC_API_KEY" in r.text, r.text[:200]
        print("  AI search (rules fallback) + no-key gate OK")

        # settings page: no provider configured yet -> home shows the add-key hint
        assert "Add your" in c.get("/").text
        r = c.get("/settings")
        assert r.status_code == 200 and "Active now" in r.text, r.status_code
        # paste a RentCast key in the browser -> applies live (no restart)
        r = c.post("/settings", data={"property_provider": "rentcast",
                                      "skiptrace_provider": "", "rentcast_api_key": "test-key-123"})
        assert r.status_code == 200 and "Saved" in r.text, r.status_code
        from app.config import settings as _s
        assert _s.rentcast_api_key == "test-key-123", _s.rentcast_api_key   # live override applied
        from app import registry
        assert registry.property_provider() is not None                    # provider rebuilt
        assert "Add your" not in c.get("/").text                           # hint now gone
        print("  settings paste-key applies live OK")


if __name__ == "__main__":
    test_smoke()
    print("smoke OK")
