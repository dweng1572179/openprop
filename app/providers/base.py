"""Provider interfaces — the whole "swap any data source" property lives here.
Each capability is one small Protocol; a concrete provider implements it and is
registered in registry.py. Every provider wraps its network calls in cache()."""
from typing import Protocol, runtime_checkable

from ..models import ContactRecord, PropertyRecord, SearchFilters


@runtime_checkable
class Geocoder(Protocol):
    def geocode(self, address: str) -> dict | None:
        """address -> {lat, lng, matched_address, state, county, fips, zip} or None."""
        ...


@runtime_checkable
class PropertyProvider(Protocol):
    def lookup(self, address: str) -> PropertyRecord | None:
        """Single-property lookup (attributes + owner + tax + value)."""
        ...

    def search(self, f: SearchFilters) -> list[PropertyRecord]:
        """Area search for the list builder. May return provider-native subset;
        the local filter engine applies the rest."""
        ...


@runtime_checkable
class SkipTraceProvider(Protocol):
    def trace(self, name: str, address: str, city: str, state: str, zip: str) -> ContactRecord | None:
        """Owner name+address -> phones/emails/addresses. Pay-per-hit; only ever
        called on explicit user action (spec §8)."""
        ...


@runtime_checkable
class RentProvider(Protocol):
    def rent_estimate(self, address: str) -> int | None: ...


@runtime_checkable
class FloodProvider(Protocol):
    def flood_zone(self, lat: float, lng: float) -> str | None: ...


@runtime_checkable
class DemographicsProvider(Protocol):
    def median_income(self, fips: str) -> int | None: ...


@runtime_checkable
class FmrProvider(Protocol):
    def fmr(self, zip: str | None, fips: str | None) -> dict[str, int] | None:
        """Fair Market Rent by bedroom count: {"0": 1200, "1": 1400, ...}."""
        ...
