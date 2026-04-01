from .client import DivvyDiaryClient
from .estimator import DividendEstimator
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

    def serialize_histories(
        self, histories: list[EstimatedSecurityDividendHistory]
    ) -> list[dict[str, object]]:
        return [history.to_dict() for history in histories]
