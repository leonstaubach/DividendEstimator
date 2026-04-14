from __future__ import annotations

from dataclasses import dataclass

from .cache import FileCache, GCSCache, _CacheBase
from .client import DivvyDiaryClient
from .config import AppConfig
from .service import PortfolioService
from .source import PortfolioDataSource


@dataclass(frozen=True)
class AppRuntime:
    config: AppConfig
    cache: _CacheBase
    source: PortfolioDataSource
    service: PortfolioService


def build_runtime(config: AppConfig | None = None) -> AppRuntime:
    active_config = config or AppConfig.from_env()

    if active_config.gcs_bucket:
        gcs_cache = GCSCache(
            bucket_name=active_config.gcs_bucket,
            blob_name=active_config.gcs_blob_name,
            ttl_seconds=active_config.cache_ttl_seconds,
            credentials_file=active_config.gcs_credentials_file,
        )
        gcs_cache.probe()
        cache: _CacheBase = gcs_cache
    else:
        cache = FileCache(active_config.cache_file, ttl_seconds=active_config.cache_ttl_seconds)

    client = DivvyDiaryClient(active_config, cache=cache)
    service = PortfolioService(client)
    return AppRuntime(
        config=active_config,
        cache=cache,
        source=client,
        service=service,
    )
