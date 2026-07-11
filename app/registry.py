"""Capability -> active provider, chosen by .env. Lazy: a provider only imports
when first requested, so the app boots (and non-provider routes work) even
before a given provider or its key is configured. Returns None when a capability
has no usable provider — callers degrade gracefully."""
from functools import lru_cache

from .config import settings


def reset() -> None:
    """Drop every cached provider instance — called after settings change so the
    next access rebuilds with the current keys/provider selection."""
    for fn in (geocoder, property_provider, skiptrace_provider, flood_provider,
               fmr_provider, demographics_provider, distress_provider):
        fn.cache_clear()


@lru_cache
def geocoder():
    if settings.geocoder == "census":
        from .providers.census import CensusGeocoder
        return CensusGeocoder()
    if settings.geocoder == "nominatim":
        from .providers.nominatim import NominatimGeocoder
        return NominatimGeocoder()
    return None


@lru_cache
def property_provider():
    name = settings.property_provider
    if name == "rentcast" and settings.rentcast_api_key:
        from .providers.rentcast import RentcastProvider
        return RentcastProvider()
    if name == "regrid" and settings.regrid_api_token:
        from .providers.regrid import RegridProvider
        return RegridProvider()
    if name == "reapi" and settings.reapi_api_key:
        from .providers.reapi import ReapiProvider
        return ReapiProvider()
    return None


@lru_cache
def skiptrace_provider():
    name = settings.skiptrace_provider
    if not name:
        return None
    if name == "reapi" and settings.reapi_api_key:
        from .providers.reapi import ReapiSkipTrace
        return ReapiSkipTrace()
    if settings.skiptrace_api_key:
        from .providers.skiptrace import GenericSkipTrace
        return GenericSkipTrace(vendor=name)
    return None


@lru_cache
def flood_provider():
    from .providers.fema import FemaFloodProvider
    return FemaFloodProvider()  # free, no key


@lru_cache
def fmr_provider():
    if settings.hud_fmr_token:
        from .providers.hud import HudFmrProvider
        return HudFmrProvider()
    return None


@lru_cache
def demographics_provider():
    from .providers.census import CensusAcs
    return CensusAcs()  # free (optional key raises rate limit)


@lru_cache
def distress_provider():
    """Optional paid unlock for foreclosure/lien/probate (spec §3)."""
    if settings.reapi_api_key:
        from .providers.reapi import ReapiProvider
        return ReapiProvider()
    return None
