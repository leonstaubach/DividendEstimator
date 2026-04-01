import unittest

from datetime import date

from divvydiary_app.cli import (
    estimate_total_amount,
    latest_historical_dividends,
    monthly_dividend_rows,
    sort_histories_by_value,
    surrounding_months,
)
from divvydiary_app.estimator import DividendEstimator
from divvydiary_app.models import (
    DividendEvent,
    DividendEstimate,
    EstimatedSecurityDividendHistory,
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
            DividendEvent(1, "2024-03-14", "2024-03-29", 1.00, "USD", False),
            DividendEvent(2, "2024-06-13", "2024-06-28", 1.10, "USD", False),
            DividendEvent(3, "2024-09-15", "2024-09-30", 1.20, "USD", False),
            DividendEvent(4, "2024-12-16", "2024-12-31", 1.30, "USD", False),
            DividendEvent(5, "2025-03-16", "2025-03-31", 1.40, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(estimate.next_payment_amount, 1.10)
        self.assertEqual(estimate.basis, "quarterly_same_season")
        self.assertEqual(estimate.confidence, "high")
        self.assertEqual(estimate.next_ex_date, "2025-06-15")
        self.assertEqual(estimate.next_payment_date, "2025-06-30")
        self.assertEqual(len(estimate.forecast_events), 4)
        self.assertEqual([event.pay_date for event in estimate.forecast_events], ["2025-06-30", "2025-09-29", "2025-12-29", "2026-03-30"])

    def test_ignores_forecast_rows(self) -> None:
        history = self.make_history([
            DividendEvent(1, "2025-03-16", "2025-03-31", 1.00, "USD", False),
            DividendEvent(2, "2025-06-15", "2025-06-30", 1.10, "USD", False),
            DividendEvent(3, "2025-09-15", "2025-09-30", 1.20, "USD", False),
            DividendEvent(4, "2025-12-16", "2025-12-31", 9.99, "USD", True),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(estimate.next_payment_amount, 1.20)
        self.assertEqual(estimate.basis, "quarterly_last_payment_fallback")
        self.assertEqual(len(estimate.forecast_events), 4)

    def test_returns_none_for_insufficient_history(self) -> None:
        history = self.make_history([
            DividendEvent(1, None, "2025-03-31", 1.00, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertIsNone(estimate.next_payment_date)
        self.assertIsNone(estimate.next_payment_amount)
        self.assertEqual(estimate.confidence, "low")
        self.assertEqual(estimate.basis, "insufficient_history")
        self.assertEqual(estimate.forecast_events, [])

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
        self.assertEqual(estimate.forecast_events, [])

    def test_monthly_history_uses_previous_cycle_amount(self) -> None:
        history = self.make_history([
            DividendEvent(1, "2025-01-26", "2025-01-31", 0.50, "USD", False),
            DividendEvent(2, "2025-02-23", "2025-02-28", 0.55, "USD", False),
            DividendEvent(3, "2025-03-26", "2025-03-31", 0.60, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(estimate.next_ex_date, "2025-04-24")
        self.assertAlmostEqual(estimate.next_payment_amount or 0.0, 0.60)
        self.assertEqual(estimate.basis, "monthly_last_payment_fallback")
        self.assertEqual(len(estimate.forecast_events), 12)
        self.assertEqual(estimate.forecast_events[0].pay_date, "2025-04-29")
        self.assertEqual(estimate.forecast_events[-1].pay_date, "2026-03-14")

    def test_quarterly_history_uses_same_slot_trend_when_available(self) -> None:
        history = self.make_history([
            DividendEvent(1, "2023-03-14", "2023-03-31", 0.90, "USD", False),
            DividendEvent(2, "2023-06-13", "2023-06-30", 1.00, "USD", False),
            DividendEvent(3, "2023-09-13", "2023-09-30", 0.95, "USD", False),
            DividendEvent(4, "2023-12-14", "2023-12-31", 0.98, "USD", False),
            DividendEvent(5, "2024-03-14", "2024-03-31", 1.05, "USD", False),
            DividendEvent(6, "2024-06-13", "2024-06-30", 1.10, "USD", False),
            DividendEvent(7, "2024-09-13", "2024-09-30", 1.08, "USD", False),
            DividendEvent(8, "2024-12-14", "2024-12-31", 1.12, "USD", False),
            DividendEvent(9, "2025-03-14", "2025-03-31", 1.20, "USD", False),
            DividendEvent(10, "2025-06-13", "2025-06-30", 1.25, "USD", False),
            DividendEvent(11, "2025-09-13", "2025-09-30", 1.22, "USD", False),
            DividendEvent(12, "2025-12-14", "2025-12-31", 1.26, "USD", False),
            DividendEvent(13, "2026-03-14", "2026-03-31", 1.35, "USD", False),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(estimate.basis, "quarterly_trend")
        self.assertAlmostEqual(estimate.next_payment_amount or 0.0, 1.3360810810810813)

    def test_seasonal_slots_tolerate_small_month_boundary_shifts(self) -> None:
        dividends = [
            DividendEvent(1, "2023-09-18", "2023-10-02", 1.00, "USD", False),
            DividendEvent(2, "2024-09-19", "2024-10-03", 1.10, "USD", False),
            DividendEvent(3, "2025-09-20", "2025-09-30", 1.20, "USD", False),
        ]

        seasonal_dividends = self.estimator._seasonal_dividends(
            dividends,
            "quarterly",
            date(2026, 10, 1),
        )

        self.assertEqual(
            [dividend.pay_date for dividend in seasonal_dividends],
            ["2023-10-02", "2024-10-03", "2025-09-30"],
        )


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
                    {"id": 2, "exDate": "2024-06-13", "payDate": "2024-06-28", "amount": 1.10, "currency": "USD", "forecast": False},
                    {"id": 3, "exDate": "2024-09-15", "payDate": "2024-09-30", "amount": 1.20, "currency": "USD", "forecast": False},
                    {"id": 4, "exDate": "2024-12-16", "payDate": "2024-12-31", "amount": 1.30, "currency": "USD", "forecast": False},
                    {"id": 5, "exDate": "2025-03-16", "payDate": "2025-03-31", "amount": 1.40, "currency": "USD", "forecast": False},
                ]
            },
        )

        service = PortfolioService(fake_client)
        estimated_histories = service.build_estimated_security_dividend_histories(resolved_portfolio)

        self.assertEqual(len(estimated_histories), 1)
        self.assertEqual(estimated_histories[0].estimate.basis, "quarterly_same_season")
        self.assertEqual(estimated_histories[0].estimate.next_ex_date, "2025-06-15")
        self.assertEqual(estimated_histories[0].estimate.next_payment_date, "2025-06-30")
        self.assertEqual(estimated_histories[0].estimate.next_payment_amount, 1.10)
        self.assertEqual(len(estimated_histories[0].estimate.forecast_events), 4)


class CliHelpersTests(unittest.TestCase):
    def make_security(self, isin: str, name: str, value: float) -> Security:
        return Security(
            isin=isin,
            wkn=None,
            symbol=isin[-4:],
            name=name,
            nickname=None,
            quantity=10.0,
            price=None,
            prev_price=None,
            value=value,
            allocation=None,
            dividend_yield=None,
            dividend_frequency=None,
            currency="USD",
            original_dividend_currency="USD",
            tax_rate=0.0,
            sector=None,
            cash_account=None,
        )

    def make_estimated_history(
        self,
        security: Security,
        dividends: list[DividendEvent],
    ) -> EstimatedSecurityDividendHistory:
        return EstimatedSecurityDividendHistory(
            security=security,
            dividends=dividends,
            estimate=DividendEstimate(
                next_ex_date="2025-06-15",
                next_payment_date="2025-06-30",
                next_payment_amount=1.0,
                confidence="medium",
                basis="quarterly_last_payment_fallback",
                forecast_events=[],
            ),
        )

    def test_sort_histories_by_value_descending(self) -> None:
        first = self.make_estimated_history(self.make_security("AAA111", "A", 100.0), [])
        second = self.make_estimated_history(self.make_security("BBB222", "B", 350.0), [])
        third = self.make_estimated_history(self.make_security("CCC333", "C", 225.0), [])

        sorted_histories = sort_histories_by_value([first, second, third])

        self.assertEqual([history.security.isin for history in sorted_histories], ["BBB222", "CCC333", "AAA111"])

    def test_latest_historical_dividends_ignores_forecasts_and_keeps_last_two_years(self) -> None:
        history = self.make_estimated_history(
            self.make_security("AAA111", "A", 100.0),
            [
                DividendEvent(1, None, "2022-12-31", 0.70, "USD", False),
                DividendEvent(2, None, "2023-03-31", 0.75, "USD", False),
                DividendEvent(3, None, "2023-06-30", 0.78, "USD", False),
                DividendEvent(4, None, "2023-09-30", 0.79, "USD", False),
                DividendEvent(5, None, "2023-12-31", 0.80, "USD", False),
                DividendEvent(1, None, "2024-03-31", 0.80, "USD", False),
                DividendEvent(6, None, "2024-06-30", 0.82, "USD", False),
                DividendEvent(7, None, "2024-09-30", 0.84, "USD", False),
                DividendEvent(8, None, "2024-12-31", 0.86, "USD", False),
                DividendEvent(9, None, "2025-03-31", 0.88, "USD", False),
                DividendEvent(10, None, "2025-06-30", 0.90, "USD", True),
            ],
        )

        recent_events = latest_historical_dividends(history)

        self.assertEqual(
            [event.pay_date for event in recent_events],
            ["2025-03-31", "2024-12-31", "2024-09-30", "2024-06-30", "2024-03-31", "2023-12-31", "2023-09-30", "2023-06-30"],
        )

    def test_estimate_total_amount_multiplies_estimate_by_quantity(self) -> None:
        security = self.make_security("AAA111", "A", 100.0)
        security.quantity = 12.5
        history = self.make_estimated_history(security, [])

        total_amount = estimate_total_amount(history)

        self.assertEqual(total_amount, 12.5)

    def test_surrounding_months_returns_previous_current_and_next(self) -> None:
        months = surrounding_months(date(2026, 1, 15))

        self.assertEqual(months, [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)])

    def test_monthly_dividend_rows_include_historical_and_estimated_events(self) -> None:
        security = self.make_security("AAA111", "Alpha Income", 100.0)
        security.quantity = 5.0
        history = EstimatedSecurityDividendHistory(
            security=security,
            dividends=[
                DividendEvent(1, None, "2026-03-15", 0.40, "USD", False),
                DividendEvent(2, None, "2026-04-18", 0.45, "USD", False),
            ],
            estimate=DividendEstimate(
                next_ex_date="2026-05-05",
                next_payment_date="2026-05-20",
                next_payment_amount=0.50,
                confidence="high",
                basis="monthly_same_season",
                forecast_events=[],
            ),
        )

        april_rows = monthly_dividend_rows([history], date(2026, 4, 1))
        may_rows = monthly_dividend_rows([history], date(2026, 5, 1))

        self.assertEqual(len(april_rows), 1)
        self.assertEqual(april_rows[0].pay_date, "2026-04-18")
        self.assertEqual(april_rows[0].ex_date, "-")
        self.assertFalse(april_rows[0].is_estimated)
        self.assertEqual(april_rows[0].total_amount, 2.25)
        self.assertEqual(len(may_rows), 1)
        self.assertTrue(may_rows[0].is_estimated)
        self.assertEqual(may_rows[0].ex_date, "2026-05-05")
        self.assertEqual(may_rows[0].amount_per_share, 0.50)
        self.assertEqual(may_rows[0].total_amount, 2.50)

    def test_monthly_dividend_rows_do_not_duplicate_matching_estimate(self) -> None:
        security = self.make_security("AAA111", "Alpha Income", 100.0)
        security.quantity = 5.0
        history = EstimatedSecurityDividendHistory(
            security=security,
            dividends=[
                DividendEvent(1, None, "2026-05-20", 0.50, "USD", True),
            ],
            estimate=DividendEstimate(
                next_ex_date="2026-05-05",
                next_payment_date="2026-05-20",
                next_payment_amount=0.50,
                confidence="high",
                basis="monthly_same_season",
                forecast_events=[],
            ),
        )

        may_rows = monthly_dividend_rows([history], date(2026, 5, 1))

        self.assertEqual(len(may_rows), 1)
        self.assertTrue(may_rows[0].is_estimated)


if __name__ == "__main__":
    unittest.main()
