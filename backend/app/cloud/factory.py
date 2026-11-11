from __future__ import annotations

from ..core.clock import Clock
from ..core.config import Settings
from .base import CloudProvider


def build_provider(settings: Settings, clock: Clock) -> CloudProvider:
    if settings.cloud_provider == "local":
        from .local.provider import LocalCloudProvider

        return LocalCloudProvider(clock, seed=settings.simulation_seed, tick_seconds=settings.tick_seconds)
    if settings.cloud_provider == "aws":
        from .aws import AWSProvider

        return AWSProvider.from_settings(settings, clock)
    raise ValueError(
        f"unsupported CLOUD_PROVIDER '{settings.cloud_provider}' (supported: local, aws; azure/gcp planned)"
    )
