import unittest

from divvydiary_app.estimator import DividendEstimator
from divvydiary_app.models import (
    DividendEvent,
    Portfolio,
    ResolvedPortfolio,
    Security,
    SecurityDividendHistory,
    UserProfile,
)
from divvydiary_app.service import PortfolioService


class FakeClient:
    def __init__(self, resolved_portfolio: ResolvedPortfolio, dividends_by_isin: dict[str, list[dict]]):
        self._resolved_portfolio = resolved_portfolio
        self._dividends_by_isin = dividends_by_isin

    def get_resolved_portfolio(self) -> ResolvedPortfolio:
        return self._resolved_portfolio

    def get_symbol_dividends(self, isin: str) -> list[dict]:
        return self._dividends_by_isin[isin]


class DividendEstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.estimator = DividendEstimator()
        self.security = Security(
            isin="TESTISIN0001",
            wkn=None,
            symbol="TEST",
            name="Test Security",
            nickname=None,
            quantity=10.0,
            price=None,
            prev_price=None,
            value=None,
            allocation=None,
            dividend_yield=None,
            dividend_frequency=None,
            currency="USD",
            original_dividend_currency="USD",
            tax_rate=0.0,
            sector=None,
            cash_account=None,
        )

    def make_history(self, dividends: list[DividendEvent]) -> SecurityDividendHistory:
        return SecurityDividendHistory(security=self.security, dividends=dividends)

    def test_quarterly_same_season_estimate(self) -> None:
        history = self.make_history([
            DividendEvent(1, None, "2024-03-29", 1.00, "USD", False),
            DividendEvent(2, None, "2024-06-28", 1.10, "USD", False),
            DividendEvent(3, None, "2024-09-30", 1.20, "USD", False),
            DividendEvent(4, None, "2024-12-31", 1.30, "USD", False),
            DividendEvent(5, None, "2025-03-31", 1.40, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(estimate.next_payment_amount, 1.10)
        self.assertEqual(estimate.basis, "quarterly_same_season")
        self.assertEqual(estimate.confidence, "high")
        self.assertEqual(estimate.next_payment_date, "2025-06-30")

    def test_ignores_forecast_rows(self) -> None:
        history = self.make_history([
            DividendEvent(1, None, "2025-03-31", 1.00, "USD", False),
            DividendEvent(2, None, "2025-06-30", 1.10, "USD", False),
            DividendEvent(3, None, "2025-09-30", 1.20, "USD", False),
            DividendEvent(4, None, "2025-12-31", 9.99, "USD", True),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(estimate.next_payment_amount, 1.20)
        self.assertEqual(estimate.basis, "quarterly_last_payment_fallback")

    def test_returns_none_for_insufficient_history(self) -> None:
        history = self.make_history([
            DividendEvent(1, None, "2025-03-31", 1.00, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertIsNone(estimate.next_payment_date)
        self.assertIsNone(estimate.next_payment_amount)
        self.assertEqual(estimate.confidence, "low")
        self.assertEqual(estimate.basis, "insufficient_history")

    def test_returns_none_for_irregular_history(self) -> None:
        history = self.make_history([
            DividendEvent(1, None, "2024-01-15", 1.00, "USD", False),
            DividendEvent(2, None, "2024-03-01", 1.10, "USD", False),
            DividendEvent(3, None, "2024-07-19", 1.20, "USD", False),
            DividendEvent(4, None, "2025-02-11", 1.30, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertIsNone(estimate.next_payment_date)
        self.assertIsNone(estimate.next_payment_amount)
        self.assertEqual(estimate.basis, "irregular_history")

    def test_monthly_history_uses_previous_cycle_amount(self) -> None:
        history = self.make_history([
            DividendEvent(1, None, "2025-01-31", 0.50, "USD", False),
            DividendEvent(2, None, "2025-02-28", 0.55, "USD", False),
            DividendEvent(3, None, "2025-03-31", 0.60, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(estimate.next_payment_amount, 0.55)
        self.assertEqual(estimate.basis, "monthly_same_season")


class PortfolioServiceEstimatorIntegrationTests(unittest.TestCase):
    def test_service_returns_estimated_histories(self) -> None:
        security = Security(
            isin="TESTISIN0001",
            wkn=None,
            symbol="TEST",
            name="Test Security",
            nickname=None,
            quantity=10.0,
            price=None,
            prev_price=None,
            value=None,
            allocation=None,
            dividend_yield=None,
            dividend_frequency=None,
            currency="USD",
            original_dividend_currency="USD",
            tax_rate=0.0,
            sector=None,
            cash_account=None,
        )
        resolved_portfolio = ResolvedPortfolio(
            user=UserProfile(id=1, forename="Test"),
            portfolio=Portfolio(id=1, name="Portfolio", currency="USD", acronym="P", securities=[security]),
        )
        fake_client = FakeClient(
            resolved_portfolio,
            {
                "TESTISIN0001": [
                    {"id": 1, "payDate": "2024-03-29", "amount": 1.00, "currency": "USD", "forecast": False},
                    {"id": 2, "payDate": "2024-06-28", "amount": 1.10, "currency": "USD", "forecast": False},
                    {"id": 3, "payDate": "2024-09-30", "amount": 1.20, "currency": "USD", "forecast": False},
                    {"id": 4, "payDate": "2024-12-31", "amount": 1.30, "currency": "USD", "forecast": False},
                    {"id": 5, "payDate": "2025-03-31", "amount": 1.40, "currency": "USD", "forecast": False},
                ]
            },
        )

        service = PortfolioService(fake_client)
        estimated_histories = service.build_estimated_security_dividend_histories(resolved_portfolio)

        self.assertEqual(len(estimated_histories), 1)
        self.assertEqual(estimated_histories[0].estimate.basis, "quarterly_same_season")
        self.assertEqual(estimated_histories[0].estimate.next_payment_date, "2025-06-30")
        self.assertEqual(estimated_histories[0].estimate.next_payment_amount, 1.10)


if __name__ == "__main__":
    unittest.main()
