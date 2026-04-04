import asyncio
import unittest

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from divvydiary_app.bootstrap import AppRuntime
from divvydiary_app.cache import FileCache
from divvydiary_app.config import AppConfig
from divvydiary_app.models import (
    DividendEvent,
    DividendEstimate,
    EstimatedSecurityDividendHistory,
    ForecastDividendEvent,
    Portfolio,
    ResolvedPortfolio,
    Security,
    UserProfile,
)
from divvydiary_app.presentation import (
    build_dashboard_view,
    build_monthly_timeline_view,
    build_security_detail_view,
)
from divvydiary_app.service import PortfolioService

try:
    from fastapi import FastAPI
    from starlette.requests import Request
    from divvydiary_app.web import create_app

    FASTAPI_AVAILABLE = True
except ModuleNotFoundError:
    FASTAPI_AVAILABLE = False
    FastAPI = None
    Request = None
    create_app = None


class FakeClient:
    def __init__(self, resolved_portfolio: ResolvedPortfolio, dividends_by_isin: dict[str, list[dict]]):
        self._resolved_portfolio = resolved_portfolio
        self._dividends_by_isin = dividends_by_isin
        self.clear_cache_calls = 0

    def get_resolved_portfolio(self) -> ResolvedPortfolio:
        return self._resolved_portfolio

    def get_symbol_dividends(self, isin: str) -> list[dict]:
        return self._dividends_by_isin[isin]

    def clear_cache(self) -> None:
        self.clear_cache_calls += 1


class PresentationParityTests(unittest.TestCase):
    def make_security(self, isin: str, name: str, value: float) -> Security:
        return Security(
            isin=isin,
            wkn=None,
            symbol=isin[-4:],
            name=name,
            nickname=None,
            quantity=5.0,
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

    def test_dashboard_view_uses_expected_selected_security_and_monthly_rows(self) -> None:
        alpha = self.make_security("AAA111", "Alpha Income", 100.0)
        alpha.quantity = 5.0
        beta = self.make_security("BBB222", "Beta Growth", 250.0)
        beta.quantity = 10.0
        resolved_portfolio = ResolvedPortfolio(
            user=UserProfile(id=1, forename="Ada"),
            portfolio=Portfolio(id=1, name="Main", currency="USD", acronym="M", securities=[alpha, beta]),
        )
        histories = [
            EstimatedSecurityDividendHistory(
                security=alpha,
                dividends=[DividendEvent(1, "2026-04-01", "2026-04-18", 0.5, "USD", False)],
                estimate=DividendEstimate(
                    next_ex_date="2026-05-05",
                    next_payment_date="2026-05-20",
                    next_payment_amount=0.55,
                    confidence="high",
                    basis="monthly_same_season",
                    forecast_events=[],
                ),
            ),
            EstimatedSecurityDividendHistory(
                security=beta,
                dividends=[DividendEvent(2, "2026-04-02", "2026-04-25", 0.3, "USD", False)],
                estimate=DividendEstimate(
                    next_ex_date="2026-06-01",
                    next_payment_date="2026-06-15",
                    next_payment_amount=0.32,
                    confidence="medium",
                    basis="quarterly_last_payment_fallback",
                    forecast_events=[],
                ),
            ),
        ]

        dashboard = build_dashboard_view(
            resolved_portfolio,
            histories,
            selected_isin="AAA111",
            reference_date=date(2026, 5, 10),
        )

        self.assertEqual(dashboard.selected_security.isin if dashboard.selected_security else None, "AAA111")
        self.assertEqual(dashboard.holdings[0].isin, "BBB222")
        self.assertEqual(len(dashboard.monthly_summaries), 3)
        self.assertEqual(dashboard.monthly_summaries[1].caption, "May 2026 (current month)")
        self.assertEqual(dashboard.monthly_summaries[1].rows[0].pay_date, "2026-05-20")

    def test_monthly_timeline_view_starts_with_previous_month_and_spans_year_ahead(self) -> None:
        alpha = self.make_security("AAA111", "Alpha Income", 100.0)
        alpha.quantity = 5.0
        resolved_portfolio = ResolvedPortfolio(
            user=UserProfile(id=1, forename="Ada"),
            portfolio=Portfolio(id=1, name="Main", currency="USD", acronym="M", securities=[alpha]),
        )
        histories = [
            EstimatedSecurityDividendHistory(
                security=alpha,
                dividends=[DividendEvent(1, "2026-04-01", "2026-04-18", 0.5, "USD", False)],
                estimate=DividendEstimate(
                    next_ex_date="2026-05-05",
                    next_payment_date="2026-05-20",
                    next_payment_amount=0.55,
                    confidence="high",
                    basis="monthly_same_season",
                    forecast_events=[],
                ),
            ),
        ]

        monthly_view = build_monthly_timeline_view(
            resolved_portfolio,
            histories,
            reference_date=date(2026, 5, 10),
        )

        self.assertEqual(len(monthly_view.month_sections), 13)
        self.assertEqual(monthly_view.month_sections[0].caption, "April 2026")
        self.assertTrue(monthly_view.month_sections[0].is_previous_month)
        self.assertEqual(monthly_view.month_sections[1].caption, "May 2026")
        self.assertEqual(monthly_view.month_sections[1].estimated_rows[0].pay_date, "2026-05-20")

    def test_security_detail_view_includes_dashboard_metadata_and_chart(self) -> None:
        alpha = self.make_security("AAA111", "Alpha Income", 100.0)
        alpha.quantity = 5.0
        alpha.dividend_frequency = "monthly"
        alpha.sector = "Utilities"
        histories = EstimatedSecurityDividendHistory(
            security=alpha,
            dividends=[
                DividendEvent(1, "2026-03-01", "2026-03-15", 0.45, "USD", False),
                DividendEvent(2, "2026-04-01", "2026-04-15", 0.50, "USD", False),
            ],
            estimate=DividendEstimate(
                next_ex_date="2026-05-05",
                next_payment_date="2026-05-20",
                next_payment_amount=0.55,
                confidence="high",
                basis="monthly_trend",
                forecast_events=[
                    ForecastDividendEvent("2026-05-05", "2026-05-20", 0.55, "USD"),
                    ForecastDividendEvent("2026-06-05", "2026-06-20", 0.60, "USD"),
                ],
            ),
        )

        detail = build_security_detail_view(histories, total_portfolio_value=500.0)

        self.assertEqual(detail.quantity, 5.0)
        self.assertAlmostEqual(detail.position_value, 100.0)
        self.assertAlmostEqual(detail.allocation or 0.0, 20.0)
        self.assertEqual(detail.dividend_frequency, "Monthly")
        self.assertEqual(detail.sector, "Utilities")
        self.assertEqual(detail.estimated_annual_total_amount, 5.75)
        self.assertEqual(detail.basis_label, "Trend blend")
        self.assertIsNotNone(detail.chart)
        self.assertEqual(detail.chart.labels[-1], "Jun 2026")


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is not installed in this interpreter")
class FastAPIAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        cache = FileCache(Path(self.temp_dir.name) / "cache.json", ttl_seconds=3600)
        security = Security(
            isin="AAA111",
            wkn=None,
            symbol="ALPHA",
            name="Alpha Income",
            nickname=None,
            quantity=10.0,
            price=None,
            prev_price=None,
            value=250.0,
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
            user=UserProfile(id=1, forename="Ada"),
            portfolio=Portfolio(id=1, name="Local Portfolio", currency="USD", acronym="LP", securities=[security]),
        )
        fake_client = FakeClient(
            resolved_portfolio,
            {
                "AAA111": [
                    {"id": 1, "exDate": "2025-03-16", "payDate": "2025-03-31", "amount": 1.4, "currency": "USD", "forecast": False},
                    {"id": 2, "exDate": "2025-06-15", "payDate": "2025-06-30", "amount": 1.1, "currency": "USD", "forecast": False},
                    {"id": 3, "exDate": "2025-09-15", "payDate": "2025-09-30", "amount": 1.2, "currency": "USD", "forecast": False},
                    {"id": 4, "exDate": "2025-12-16", "payDate": "2025-12-31", "amount": 1.3, "currency": "USD", "forecast": False},
                ]
            },
        )
        service = PortfolioService(fake_client)
        runtime = AppRuntime(
            config=AppConfig(
                api_key="token",
                user_id="",
                portfolio_id="",
                cache_file=Path(self.temp_dir.name) / "cache.json",
            ),
            cache=cache,
            client=fake_client,  # type: ignore[arg-type]
            service=service,
        )
        self.fake_client = fake_client
        self.app = create_app(runtime)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def get_route(self, path: str, method: str):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route
        raise AssertionError(f"Route not found: {method} {path}")

    def make_request(self, path: str = "/", method: str = "GET") -> Request:
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "app": self.app,
            "router": self.app.router,
            "extensions": {},
        }
        return Request(scope)

    def test_health_route_returns_ok(self) -> None:
        route = self.get_route("/health", "GET")
        response = asyncio.run(route.endpoint())

        self.assertEqual(response, {"status": "ok"})

    def test_dashboard_renders_portfolio_holdings(self) -> None:
        route = self.get_route("/", "GET")
        response = asyncio.run(route.endpoint(self.make_request("/")))

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("Local Portfolio", body)
        self.assertIn("Alpha Income", body)
        self.assertIn("Portfolio Holdings", body)
        self.assertIn("What this tool does", body)
        self.assertIn("pulls portfolio and dividend history data from DivvyDiary", body)
        self.assertIn("/security/AAA111", body)

    def test_monthly_page_renders_monthly_summaries(self) -> None:
        route = self.get_route("/monthly", "GET")
        response = asyncio.run(route.endpoint(self.make_request("/monthly")))

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("Monthly View", body)
        self.assertIn("Previous month", body)

    def test_security_page_renders_security_detail(self) -> None:
        route = self.get_route("/security/{isin}", "GET")
        response = asyncio.run(route.endpoint(self.make_request("/security/AAA111"), "AAA111"))

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("Security Insight", body)
        self.assertIn("Alpha Income", body)
        self.assertIn("Dividend Timeline", body)
        self.assertIn("Upcoming Forecasted Dividends", body)
        self.assertIn("Recent Confirmed Dividends", body)
        self.assertIn("Explain Next Forecast", body)
        self.assertIn("security-detail-chart", body)

    def test_forecast_explanation_page_renders_reasoning_sections(self) -> None:
        route = self.get_route("/security/{isin}/forecast/{forecast_index}", "GET")
        response = asyncio.run(route.endpoint(self.make_request("/security/AAA111/forecast/1"), "AAA111", 1))

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("Forecast Explanation", body)
        self.assertIn("Relevant Dividend Events Used For The Prediction", body)
        self.assertIn("Calculation Breakdown", body)
        self.assertIn("All Historical Confirmed Dividends", body)

    def test_forecast_explanation_modal_renders_condensed_content(self) -> None:
        route = self.get_route("/security/{isin}/forecast/{forecast_index}/modal", "GET")
        response = asyncio.run(route.endpoint(self.make_request("/security/AAA111/forecast/1/modal"), "AAA111", 1))

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("Calculation Breakdown", body)
        self.assertIn("Relevant Dividend Events Used For The Prediction", body)
        self.assertNotIn("All Historical Confirmed Dividends", body)
        self.assertNotIn("Why this forecast?", body)

    def test_refresh_cache_action_clears_cache_and_redirects(self) -> None:
        route = self.get_route("/actions/refresh-cache", "POST")
        response = asyncio.run(route.endpoint())

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        self.assertEqual(self.fake_client.clear_cache_calls, 1)


if __name__ == "__main__":
    unittest.main()
