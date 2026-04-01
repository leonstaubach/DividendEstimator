import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import AppConfig
from .models import ResolvedPortfolio, UserProfile, Portfolio


class DivvyDiaryClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def get_json(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

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
        portfolio_id = first_portfolio["id"]
        return self.get_json(f"/portfolios/{portfolio_id}")

    def get_resolved_portfolio(self) -> ResolvedPortfolio:
        payload = self.get_portfolio_payload()
        return ResolvedPortfolio(
            user=UserProfile.from_api(payload.get("user", {})),
            portfolio=Portfolio.from_api(payload.get("portfolio", {})),
        )

    def get_symbol_dividends(self, isin: str) -> list[dict[str, Any]]:
        symbol_payload = self.get_json(f"/symbols/{isin}")
        return symbol_payload.get("dividends", [])
