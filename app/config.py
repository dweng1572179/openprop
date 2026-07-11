"""Settings from .env. One source of truth; providers read keys from here."""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openprop_password: str = "changeme"
    secret_key: str = ""
    session_https_only: bool = False  # set true when serving over HTTPS (adds Secure to the cookie)

    property_provider: str = "rentcast"
    skiptrace_provider: str = ""
    apify_actor: str = "khadinakbar~skip-trace-property-owner"  # used when skiptrace_provider=apify
    geocoder: str = "census"

    rentcast_api_key: str = ""
    rentcast_fetch_avm: bool = False  # False = 1 request/lookup; True adds value+rent (3 total)
    regrid_api_token: str = ""
    reapi_api_key: str = ""
    hud_fmr_token: str = ""
    census_api_key: str = ""
    skiptrace_api_key: str = ""

    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-4-8"  # override in .env (e.g. claude-haiku-4-5 for cheaper)

    monthly_budget_cents: int = 1000
    skiptrace_cost_cents: int = 15   # per-hit estimate shown in confirm-before-spend
    db_path: str = "openprop.db"

    @field_validator("*", mode="before")
    @classmethod
    def _drop_inline_comment(cls, v, info):
        """`KEY=   # note` in .env yields the comment as the value: python-dotenv only
        strips an inline comment when the value is non-empty. Left alone, a blank
        SECRET_KEY reads as truthy and app.py never generates a random one."""
        if isinstance(v, str) and v.lstrip().startswith("#"):
            return cls.model_fields[info.field_name].default
        return v


settings = Settings()


if __name__ == "__main__":  # python -m app.config
    import os
    os.environ |= {"SECRET_KEY": "  # leave blank -> generated", "MONTHLY_BUDGET_CENTS": "250"}
    s = Settings(_env_file=None)
    assert s.secret_key == "", f"comment leaked into secret_key: {s.secret_key!r}"
    assert s.monthly_budget_cents == 250, s.monthly_budget_cents  # real values still parse
    assert Settings(_env_file=None, rentcast_api_key="abc123").rentcast_api_key == "abc123"
    print("config ok — inline comments dropped, real values preserved")
