from .client import DivvyDiaryClient
from .estimator import DividendEstimator, ForecastExplanation
from .models import (
    DividendEvent,
    EstimatedSecurityDividendHistory,
    ResolvedPortfolio,
    Security,
    SecurityDividendHistory,
)


class PortfolioService:
    def __init__(self, client: DivvyDiaryClient, estimator: DividendEstimator | None = None) -> None:
        self.client = client
        self.estimator = estimator or DividendEstimator()

    def get_resolved_portfolio(self) -> ResolvedPortfolio:
        return self.client.get_resolved_portfolio()

    def build_security_dividend_history(self, security: Security) -> SecurityDividendHistory:
        raw_dividends = self.client.get_symbol_dividends(security.isin)
        dividends = [DividendEvent.from_api(raw_dividend) for raw_dividend in raw_dividends]
        return SecurityDividendHistory(security=security, dividends=dividends)

    def build_security_dividend_histories(
        self, resolved_portfolio: ResolvedPortfolio
    ) -> list[SecurityDividendHistory]:
        return [
            self.build_security_dividend_history(security)
            for security in resolved_portfolio.portfolio.securities
        ]

    def build_estimated_security_dividend_history(
        self, history: SecurityDividendHistory
    ) -> EstimatedSecurityDividendHistory:
        return EstimatedSecurityDividendHistory(
            security=history.security,
            dividends=history.dividends,
            estimate=self.estimator.estimate(history),
        )

    def build_estimated_security_dividend_histories(
        self, resolved_portfolio: ResolvedPortfolio
    ) -> list[EstimatedSecurityDividendHistory]:
        histories = self.build_security_dividend_histories(resolved_portfolio)
        return [self.build_estimated_security_dividend_history(history) for history in histories]

    def load_portfolio_data(
        self,
    ) -> tuple[ResolvedPortfolio, list[EstimatedSecurityDividendHistory]]:
        resolved_portfolio = self.get_resolved_portfolio()
        return resolved_portfolio, self.build_estimated_security_dividend_histories(resolved_portfolio)

    def is_data_cached(self) -> bool:
        return self.client.is_portfolio_cached()

    def clear_cache(self) -> None:
        self.client.clear_cache()

    def explain_forecast(
        self,
        history: SecurityDividendHistory | EstimatedSecurityDividendHistory,
        steps_ahead: int = 1,
    ) -> ForecastExplanation | None:
        base_history = SecurityDividendHistory(
            security=history.security,
            dividends=history.dividends,
        )
        return self.estimator.explain_forecast(base_history, steps_ahead)
