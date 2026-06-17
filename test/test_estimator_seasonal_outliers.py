import unittest

from divvydiary_app.estimator import DividendEstimator
from divvydiary_app.models import DividendEvent, Security, SecurityDividendHistory


class SeasonalOutlierEstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.estimator = DividendEstimator()
        self.security = Security(
            isin="VTTEST000001",
            wkn=None,
            symbol="VT",
            name="Vanguard Total World Stock ETF",
            nickname=None,
            quantity=1.0,
            price=None,
            prev_price=None,
            value=None,
            allocation=None,
            dividend_yield=None,
            dividend_frequency="quarterly",
            currency="USD",
            original_dividend_currency="USD",
            tax_rate=0.0,
            sector=None,
            cash_account=None,
        )

    def make_history(self, rows: list[tuple[str, str, float]]) -> SecurityDividendHistory:
        dividends = [
            DividendEvent(index, ex_date, pay_date, amount, "USD", False)
            for index, (pay_date, ex_date, amount) in enumerate(rows, start=1)
        ]
        return SecurityDividendHistory(security=self.security, dividends=dividends)

    def test_quarterly_outlier_filter_keeps_large_december_payment_in_same_season(self) -> None:
        history = self.make_history([
            ("2018-03-29", "2018-03-26", 0.2573),
            ("2018-06-27", "2018-06-22", 0.5511),
            ("2018-10-01", "2018-09-26", 0.3615),
            ("2018-12-28", "2018-12-24", 0.4890),
            ("2019-03-28", "2019-03-25", 0.2810),
            ("2019-06-20", "2019-06-17", 0.5508),
            ("2019-09-27", "2019-09-24", 0.4348),
            ("2019-12-27", "2019-12-23", 0.6109),
            ("2020-03-26", "2020-03-23", 0.2205),
            ("2020-06-25", "2020-06-22", 0.3600),
            ("2020-09-24", "2020-09-21", 0.4025),
            ("2020-12-24", "2020-12-21", 0.5524),
            ("2021-03-25", "2021-03-22", 0.2531),
            ("2021-06-24", "2021-06-21", 0.5049),
            ("2021-09-23", "2021-09-20", 0.4120),
            ("2021-12-23", "2021-12-20", 0.7850),
            ("2022-03-24", "2022-03-21", 0.2572),
            ("2022-06-24", "2022-06-21", 0.5978),
            ("2022-09-22", "2022-09-19", 0.4026),
            ("2022-12-22", "2022-12-19", 0.6381),
            ("2023-03-23", "2023-03-20", 0.2852),
            ("2023-06-23", "2023-06-20", 0.6504),
            ("2023-09-21", "2023-09-18", 0.4055),
            ("2023-12-21", "2023-12-18", 0.8008),
            ("2024-03-20", "2024-03-15", 0.4212),
            ("2024-06-25", "2024-06-21", 0.5779),
            ("2024-09-24", "2024-09-20", 0.4174),
            ("2024-12-24", "2024-12-20", 0.8774),
            ("2025-03-25", "2025-03-21", 0.3852),
            ("2025-06-24", "2025-06-20", 0.5947),
            ("2025-09-23", "2025-09-19", 0.4781),
            ("2025-12-23", "2025-12-19", 1.1152),
        ])

        confirmed = self.estimator._confirmed_dividends(history)
        clean, removed = self.estimator._remove_outliers(confirmed, cadence_name="quarterly")

        self.assertNotIn("2025-12-23", [event.pay_date for event in removed])
        self.assertEqual(clean[-1].pay_date, "2025-12-23")

    def test_march_forecast_explanation_uses_march_reference_after_december_history(self) -> None:
        history = self.make_history([
            ("2018-03-29", "2018-03-26", 0.2573),
            ("2018-06-27", "2018-06-22", 0.5511),
            ("2018-10-01", "2018-09-26", 0.3615),
            ("2018-12-28", "2018-12-24", 0.4890),
            ("2019-03-28", "2019-03-25", 0.2810),
            ("2019-06-20", "2019-06-17", 0.5508),
            ("2019-09-27", "2019-09-24", 0.4348),
            ("2019-12-27", "2019-12-23", 0.6109),
            ("2020-03-26", "2020-03-23", 0.2205),
            ("2020-06-25", "2020-06-22", 0.3600),
            ("2020-09-24", "2020-09-21", 0.4025),
            ("2020-12-24", "2020-12-21", 0.5524),
            ("2021-03-25", "2021-03-22", 0.2531),
            ("2021-06-24", "2021-06-21", 0.5049),
            ("2021-09-23", "2021-09-20", 0.4120),
            ("2021-12-23", "2021-12-20", 0.7850),
            ("2022-03-24", "2022-03-21", 0.2572),
            ("2022-06-24", "2022-06-21", 0.5978),
            ("2022-09-22", "2022-09-19", 0.4026),
            ("2022-12-22", "2022-12-19", 0.6381),
            ("2023-03-23", "2023-03-20", 0.2852),
            ("2023-06-23", "2023-06-20", 0.6504),
            ("2023-09-21", "2023-09-18", 0.4055),
            ("2023-12-21", "2023-12-18", 0.8008),
            ("2024-03-20", "2024-03-15", 0.4212),
            ("2024-06-25", "2024-06-21", 0.5779),
            ("2024-09-24", "2024-09-20", 0.4174),
            ("2024-12-24", "2024-12-20", 0.8774),
            ("2025-03-25", "2025-03-21", 0.3852),
            ("2025-06-24", "2025-06-20", 0.5947),
            ("2025-09-23", "2025-09-19", 0.4781),
            ("2025-12-23", "2025-12-19", 1.1152),
        ])

        estimate = self.estimator.estimate(history)
        explanation = self.estimator.explain_forecast(history, steps_ahead=1)

        self.assertEqual(estimate.next_payment_date, "2026-03-24")
        self.assertIsNotNone(explanation)
        assert explanation is not None
        self.assertEqual(explanation.predicted_pay_date, "2026-03-24")
        self.assertNotIn("2025-12-23", [event.pay_date for event in explanation.outliers_removed])
        self.assertEqual(
            [event.pay_date for event in explanation.seasonal_dividends],
            [
                "2018-03-29",
                "2019-03-28",
                "2020-03-26",
                "2021-03-25",
                "2022-03-24",
                "2023-03-23",
                "2024-03-20",
                "2025-03-25",
            ],
        )
        self.assertEqual(
            explanation.chosen_reference_dividend.pay_date if explanation.chosen_reference_dividend else None,
            "2025-03-25",
        )

    def test_quarterly_yoy_spike_is_capped_at_ten_percent_above_same_season_reference(self) -> None:
        history = self.make_history([
            ("2023-03-31", "2023-03-14", 1.00),
            ("2023-06-30", "2023-06-13", 1.00),
            ("2023-09-30", "2023-09-13", 1.00),
            ("2023-12-31", "2023-12-14", 1.00),
            ("2024-03-31", "2024-03-14", 1.00),
            ("2024-06-30", "2024-06-13", 2.00),
            ("2024-09-30", "2024-09-13", 1.00),
            ("2024-12-31", "2024-12-14", 1.00),
            ("2025-03-31", "2025-03-14", 1.00),
        ])

        estimate = self.estimator.estimate(history)
        explanation = self.estimator.explain_forecast(history, steps_ahead=1)

        self.assertEqual(estimate.basis, "quarterly_trend")
        self.assertAlmostEqual(estimate.next_payment_amount or 0.0, 2.20)
        self.assertIsNotNone(explanation)
        assert explanation is not None
        self.assertAlmostEqual(explanation.predicted_amount or 0.0, 2.20)
        self.assertIsNotNone(explanation.trend_analysis)
        assert explanation.trend_analysis is not None
        self.assertAlmostEqual(explanation.trend_analysis.growth_rate or 0.0, 0.10)

    def test_quarterly_yoy_cut_is_floored_at_ten_percent_below_same_season_reference(self) -> None:
        history = self.make_history([
            ("2023-03-31", "2023-03-14", 1.00),
            ("2023-06-30", "2023-06-13", 2.00),
            ("2023-09-30", "2023-09-13", 1.00),
            ("2023-12-31", "2023-12-14", 1.00),
            ("2024-03-31", "2024-03-14", 1.00),
            ("2024-06-30", "2024-06-13", 1.00),
            ("2024-09-30", "2024-09-13", 1.00),
            ("2024-12-31", "2024-12-14", 1.00),
            ("2025-03-31", "2025-03-14", 1.00),
        ])

        estimate = self.estimator.estimate(history)
        explanation = self.estimator.explain_forecast(history, steps_ahead=1)

        self.assertEqual(estimate.basis, "quarterly_trend")
        self.assertAlmostEqual(estimate.next_payment_amount or 0.0, 0.90)
        self.assertIsNotNone(explanation)
        assert explanation is not None
        self.assertAlmostEqual(explanation.predicted_amount or 0.0, 0.90)
        self.assertIsNotNone(explanation.trend_analysis)
        assert explanation.trend_analysis is not None
        self.assertAlmostEqual(explanation.trend_analysis.growth_rate or 0.0, -0.10)

    def test_monthly_variance_adjusted_forecasts_stay_within_latest_payment_cap(self) -> None:
        self.security.dividend_frequency = "monthly"
        history = self.make_history([
            ("2024-01-31", "2024-01-26", 0.50),
            ("2024-02-29", "2024-02-24", 1.50),
            ("2024-03-31", "2024-03-26", 0.50),
            ("2024-04-30", "2024-04-25", 1.50),
            ("2024-05-31", "2024-05-26", 0.50),
            ("2024-06-30", "2024-06-25", 1.50),
            ("2024-07-31", "2024-07-26", 0.50),
            ("2024-08-31", "2024-08-26", 1.50),
            ("2024-09-30", "2024-09-25", 0.50),
            ("2024-10-31", "2024-10-26", 1.50),
            ("2024-11-30", "2024-11-25", 0.50),
            ("2024-12-31", "2024-12-26", 1.00),
        ])

        estimate = self.estimator.estimate(history)

        self.assertEqual(len(estimate.forecast_events), 12)
        for event in estimate.forecast_events:
            self.assertIsNotNone(event.amount)
            assert event.amount is not None
            self.assertGreaterEqual(event.amount, 0.90)
            self.assertLessEqual(event.amount, 1.10)


if __name__ == "__main__":
    unittest.main()
