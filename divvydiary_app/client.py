import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from collections.abc import Callable

from .cache import FileCache
from .config import AppConfig
from .models import ResolvedPortfolio, UserProfile, Portfolio


class DivvyDiaryClient:
    def __init__(
        self,
        config: AppConfig,
        cache: FileCache | None = None,
        log_func: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.cache = cache
        self.log_func = log_func

    def get_json(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        self._log(f"DivvyDiary API call triggered: GET {url}")

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
        cache_key = self._portfolio_cache_key()
        cached_payload = self._cache_get(cache_key)
        if cached_payload is not None:
            self._log("Portfolio data: using pre-fetched cached data.")
            return cached_payload

        self._log("Portfolio data: no valid cached data found, fetching from DivvyDiary API.")

        if self.config.portfolio_id:
            payload = self.get_json(f"/portfolios/{self.config.portfolio_id}")
            self._cache_set(cache_key, payload)
            return payload

        query = {"userId": self.config.user_id} if self.config.user_id else None
        listing = self.get_json("/portfolios", query)
        portfolios = listing.get("portfolios", [])

        if not portfolios:
            raise RuntimeError(
                "No portfolios were returned. Set DIVVYDIARY_USER_ID or "
                "DIVVYDIARY_PORTFOLIO_ID if your API key alone is not enough."
            )

        first_portfolio = portfolios[0]
        portfolio_id = first_portfolio["id"]
        payload = self.get_json(f"/portfolios/{portfolio_id}")
        self._cache_set(cache_key, payload)
        return payload

    def get_resolved_portfolio(self) -> ResolvedPortfolio:
        payload = self.get_portfolio_payload()
        return ResolvedPortfolio(
            user=UserProfile.from_api(payload.get("user", {})),
            portfolio=Portfolio.from_api(payload.get("portfolio", {})),
        )

    def get_symbol_dividends(self, isin: str) -> list[dict[str, Any]]:
        cache_key = f"symbol_dividends:{isin}"
        cached_dividends = self._cache_get(cache_key)
        if cached_dividends is not None:
            self._log(f"Dividend history for {isin}: using pre-fetched cached data.")
            return cached_dividends

        self._log(f"Dividend history for {isin}: no valid cached data found, fetching from DivvyDiary API.")

        symbol_payload = self.get_json(f"/symbols/{isin}")
        dividends = symbol_payload.get("dividends", [])
        self._cache_set(cache_key, dividends)
        return dividends

    def clear_cache(self) -> None:
        if self.cache is not None:
            self.cache.clear()

    def _portfolio_cache_key(self) -> str:
        portfolio_identifier = self.config.portfolio_id or self.config.user_id or "default"
        return f"portfolio:{portfolio_identifier}"

    def _cache_get(self, key: str) -> Any | None:
        if self.cache is None:
            return None
        return self.cache.get(key)

    def _cache_set(self, key: str, value: Any) -> None:
        if self.cache is None:
            return
        self.cache.set(key, value)

    def _log(self, message: str) -> None:
        if self.log_func is not None:
            self.log_func(message)
