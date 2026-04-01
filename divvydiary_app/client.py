import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .cache import FileCache
from .config import AppConfig
from .logging_config import get_logger
from .models import Portfolio, ResolvedPortfolio, UserProfile

logger = get_logger("client")


class DivvyDiaryClient:
    def __init__(
        self,
        config: AppConfig,
        cache: FileCache | None = None,
    ) -> None:
        self.config = config
        self.cache = cache

    def get_json(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        logger.debug("DivvyDiary API call triggered: GET %s", url)

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-API-KEY": self.config.api_key,
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GET {url} failed with HTTP {exc.code}: {body}") from exc

    def get_portfolio_payload(self) -> dict[str, Any]:
        return self._get_or_fetch_cached_value(
            key=self._portfolio_cache_key(),
            data_label="Portfolio data",
            fetch_func=self._fetch_portfolio_payload,
        )

    def get_resolved_portfolio(self) -> ResolvedPortfolio:
        payload = self.get_portfolio_payload()
        return ResolvedPortfolio(
            user=UserProfile.from_api(payload.get("user", {})),
            portfolio=Portfolio.from_api(payload.get("portfolio", {})),
        )

    def get_symbol_dividends(self, isin: str) -> list[dict[str, Any]]:
        return self._get_or_fetch_cached_value(
            key=f"symbol_dividends:{isin}",
            data_label=f"Dividend history for {isin}",
            fetch_func=lambda: self.get_json(f"/symbols/{isin}").get("dividends", []),
        )

    def clear_cache(self) -> None:
        if self.cache is not None:
            self.cache.clear()

    def _portfolio_cache_key(self) -> str:
        portfolio_identifier = self.config.portfolio_id or self.config.user_id or "default"
        return f"portfolio:{portfolio_identifier}"

    def _fetch_portfolio_payload(self) -> dict[str, Any]:
        if self.config.portfolio_id:
            return self.get_json(f"/portfolios/{self.config.portfolio_id}")

        query = {"userId": self.config.user_id} if self.config.user_id else None
        listing = self.get_json("/portfolios", query)
        portfolios = listing.get("portfolios", [])

        if not portfolios:
            raise RuntimeError(
                "No portfolios were returned. Set DIVVYDIARY_USER_ID or "
                "DIVVYDIARY_PORTFOLIO_ID if your API key alone is not enough."
            )

        first_portfolio = portfolios[0]
        return self.get_json(f"/portfolios/{first_portfolio['id']}")

    def _get_or_fetch_cached_value(
        self,
        key: str,
        data_label: str,
        fetch_func: Callable[[], Any],
    ) -> Any:
        cached_value = self._cache_get(key)
        if cached_value is not None:
            logger.debug("%s: using pre-fetched cached data.", data_label)
            return cached_value

        logger.debug("%s: no valid cached data found, fetching from DivvyDiary API.", data_label)
        value = fetch_func()
        self._cache_set(key, value)
        return value

    def _cache_get(self, key: str) -> Any | None:
        if self.cache is None:
            return None
        return self.cache.get(key)

    def _cache_set(self, key: str, value: Any) -> None:
        if self.cache is None:
            return
        self.cache.set(key, value)
