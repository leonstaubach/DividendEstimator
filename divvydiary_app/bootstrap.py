from __future__ import annotations

from dataclasses import dataclass

from .cache import FileCache
from .client import DivvyDiaryClient
from .config import AppConfig
from .service import PortfolioService


@dataclass(frozen=True)
class AppRuntime:
    config: AppConfig
    cache: FileCache
    client: DivvyDiaryClient
    service: PortfolioService


def build_runtime(config: AppConfig | None = None) -> AppRuntime:
    active_config = config or AppConfig.from_env()
    cache = FileCache(active_config.cache_file, ttl_seconds=active_config.cache_ttl_seconds)
    client = DivvyDiaryClient(active_config, cache=cache)
    service = PortfolioService(client)
    return AppRuntime(
        config=active_config,
        cache=cache,
        client=client,
        service=service,
    )
