from datetime import date

from .estimator import DividendEstimator, ForecastExplanation
from .models import (
    DividendEvent,
    EstimatedSecurityDividendHistory,
    ResolvedPortfolio,
    Security,
    SecurityDividendHistory,
)
from .presentation import BacktestResult
from .source import PortfolioDataSource


class PortfolioService:
    def __init__(self, source: PortfolioDataSource, estimator: DividendEstimator | None = None) -> None:
        self.source = source
        self.estimator = estimator or DividendEstimator()

    def get_resolved_portfolio(self) -> ResolvedPortfolio:
        return self.source.get_resolved_portfolio()

    def build_security_dividend_history(self, security: Security) -> SecurityDividendHistory:
        dividends = self.source.get_symbol_dividends(security.isin)
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
        return self.source.is_portfolio_cached()

    def clear_cache(self) -> None:
        self.source.clear_cache()

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

    def backtest_explanation(
        self,
        history: EstimatedSecurityDividendHistory,
        event_id: int,
    ) -> tuple[DividendEvent, ForecastExplanation] | None:
        target = next((e for e in history.dividends if e.id == event_id), None)
        if target is None or target.forecast or not target.pay_date:
            return None

        truncated_dividends = [
            e for e in history.dividends
            if e.forecast or not e.pay_date or e.pay_date < target.pay_date
        ]
        confirmed_before = [
            e for e in truncated_dividends
            if not e.forecast and e.pay_date and e.amount is not None
        ]
        if len(confirmed_before) < 2:
            return None

        truncated_history = SecurityDividendHistory(
            security=history.security,
            dividends=truncated_dividends,
        )
        explanation = self.estimator.explain_forecast(truncated_history, steps_ahead=1)
        if explanation is None or explanation.predicted_amount is None:
            return None

        return target, explanation

    def backtest_dividend(
        self,
        history: EstimatedSecurityDividendHistory,
        target: DividendEvent,
    ) -> BacktestResult | None:
        # Keep all events that are either forecasts (estimator will filter them)
        # or confirmed payments strictly before the target pay date.
        truncated_dividends = [
            e for e in history.dividends
            if e.forecast or not e.pay_date or e.pay_date < target.pay_date
        ]
        confirmed_before = [
            e for e in truncated_dividends
            if not e.forecast and e.pay_date and e.amount is not None
        ]
        if len(confirmed_before) < 2:
            return None

        truncated_history = SecurityDividendHistory(
            security=history.security,
            dividends=truncated_dividends,
        )
        explanation = self.estimator.explain_forecast(truncated_history, steps_ahead=1)
        if explanation is None or explanation.predicted_amount is None:
            return None

        amount_error_pct: float | None = None
        if target.amount is not None and target.amount != 0:
            amount_error_pct = (explanation.predicted_amount - target.amount) / target.amount * 100

        date_error_days: int | None = None
        if explanation.predicted_pay_date and target.pay_date:
            predicted = date.fromisoformat(explanation.predicted_pay_date)
            actual = date.fromisoformat(target.pay_date)
            date_error_days = (predicted - actual).days

        return BacktestResult(
            predicted_amount=explanation.predicted_amount,
            predicted_pay_date=explanation.predicted_pay_date,
            amount_error_pct=amount_error_pct,
            date_error_days=date_error_days,
            basis=explanation.basis,
        )
