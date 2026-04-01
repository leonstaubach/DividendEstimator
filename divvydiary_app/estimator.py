from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from .models import DividendEstimate, DividendEvent, ForecastDividendEvent, SecurityDividendHistory


@dataclass(frozen=True)
class CadenceInfo:
    name: str
    median_gap_days: int


class DividendEstimator:
    CADENCE_BUCKETS = {
        "monthly": (25, 40),
        "quarterly": (70, 110),
        "semiannual": (150, 220),
        "annual": (330, 390),
    }
    FORECAST_EVENT_COUNTS = {
        "monthly": 12,
        "quarterly": 4,
        "semiannual": 2,
        "annual": 1,
    }

    def estimate(self, history: SecurityDividendHistory) -> DividendEstimate:
        confirmed_dividends = self._confirmed_dividends(history)
        if len(confirmed_dividends) < 2:
            return DividendEstimate(
                next_ex_date=None,
                next_payment_date=None,
                next_payment_amount=None,
                confidence="low",
                basis="insufficient_history",
                forecast_events=[],
            )

        cadence = self._detect_cadence(confirmed_dividends)
        if cadence is None:
            return DividendEstimate(
                next_ex_date=None,
                next_payment_date=None,
                next_payment_amount=None,
                confidence="low",
                basis="irregular_history",
                forecast_events=[],
            )

        forecast_events = self._forecast_events(confirmed_dividends, cadence)
        first_forecast = forecast_events[0]
        amount_basis = self._amount_basis_for_date(confirmed_dividends, cadence, first_forecast.pay_date)

        confidence = "high" if amount_basis.endswith(("same_season", "trend")) else "medium"
        return DividendEstimate(
            next_ex_date=first_forecast.ex_date,
            next_payment_date=first_forecast.pay_date,
            next_payment_amount=first_forecast.amount,
            confidence=confidence,
            basis=amount_basis,
            forecast_events=forecast_events,
        )

    def _confirmed_dividends(self, history: SecurityDividendHistory) -> list[DividendEvent]:
        confirmed = [
            dividend
            for dividend in history.dividends
            if not dividend.forecast and dividend.pay_date is not None and dividend.amount is not None
        ]
        return sorted(confirmed, key=lambda dividend: dividend.pay_date or "")

    def _detect_cadence(self, dividends: list[DividendEvent]) -> CadenceInfo | None:
        pay_dates = [self._parse_date(dividend.pay_date) for dividend in dividends if dividend.pay_date]
        gaps = [(current - previous).days for previous, current in zip(pay_dates, pay_dates[1:])]
        if len(gaps) < 1:
            return None

        matched_gaps: dict[str, list[int]] = {}
        for cadence_name, (lower, upper) in self.CADENCE_BUCKETS.items():
            matches = [gap for gap in gaps if lower <= gap <= upper]
            if matches:
                matched_gaps[cadence_name] = matches

        if not matched_gaps:
            return None

        best_name, best_matches = max(
            matched_gaps.items(),
            key=lambda item: (len(item[1]), -abs(median(item[1]) - median(gaps))),
        )
        minimum_matches = max(2, (len(gaps) + 1) // 2)
        if len(best_matches) < minimum_matches:
            return None

        return CadenceInfo(
            name=best_name,
            median_gap_days=int(median(best_matches)),
        )

    def _estimate_next_payment_date(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
        steps_ahead: int = 1,
    ) -> str | None:
        latest_pay_date = self._parse_date(dividends[-1].pay_date)
        return (latest_pay_date + timedelta(days=cadence.median_gap_days * steps_ahead)).isoformat()

    def _estimate_payment_amount(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
        payment_date: str | None,
    ) -> tuple[float | None, str]:
        latest_dividend = dividends[-1]
        if payment_date is None:
            return latest_dividend.amount, f"{cadence.name}_last_payment_fallback"

        next_pay_date = self._parse_date(payment_date)
        seasonal_dividends = self._seasonal_dividends(dividends, cadence.name, next_pay_date)
        trend_amount = self._estimate_trend_amount(seasonal_dividends)
        if trend_amount is not None:
            return trend_amount, f"{cadence.name}_trend"

        if seasonal_dividends:
            return seasonal_dividends[-1].amount, f"{cadence.name}_same_season"

        return latest_dividend.amount, f"{cadence.name}_last_payment_fallback"

    def _amount_basis_for_date(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
        payment_date: str | None,
    ) -> str:
        _, amount_basis = self._estimate_payment_amount(dividends, cadence, payment_date)
        return amount_basis

    def _estimate_next_ex_date(
        self,
        dividends: list[DividendEvent],
        next_payment_date: str | None,
    ) -> str | None:
        if next_payment_date is None:
            return None

        ex_to_pay_gaps = [
            (self._parse_date(dividend.pay_date) - self._parse_date(dividend.ex_date)).days
            for dividend in dividends
            if dividend.pay_date is not None and dividend.ex_date is not None
        ]
        if not ex_to_pay_gaps:
            return None

        next_pay_date = self._parse_date(next_payment_date)
        median_gap_days = int(median(ex_to_pay_gaps))
        return (next_pay_date - timedelta(days=median_gap_days)).isoformat()

    def _forecast_events(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
    ) -> list[ForecastDividendEvent]:
        event_count = self.FORECAST_EVENT_COUNTS[cadence.name]
        forecast_events: list[ForecastDividendEvent] = []

        for steps_ahead in range(1, event_count + 1):
            payment_date = self._estimate_next_payment_date(dividends, cadence, steps_ahead)
            amount, _ = self._estimate_payment_amount(dividends, cadence, payment_date)
            forecast_events.append(
                ForecastDividendEvent(
                    ex_date=self._estimate_next_ex_date(dividends, payment_date),
                    pay_date=payment_date,
                    amount=amount,
                    currency=dividends[-1].currency,
                    forecast=True,
                )
            )

        return forecast_events

    def _seasonal_dividends(
        self,
        dividends: list[DividendEvent],
        cadence_name: str,
        next_pay_date: date,
    ) -> list[DividendEvent]:
        if cadence_name == "monthly":
            return list(dividends)

        target_key = self._seasonal_key(cadence_name, next_pay_date)
        matches: list[DividendEvent] = []
        for dividend in dividends:
            pay_date = self._parse_date(dividend.pay_date)
            if self._seasonal_key(cadence_name, pay_date) == target_key:
                matches.append(dividend)
        return matches

    def _estimate_trend_amount(self, dividends: list[DividendEvent]) -> float | None:
        amounts = [dividend.amount for dividend in dividends if dividend.amount is not None]
        if len(amounts) < 3:
            return None

        x_values = list(range(len(amounts)))
        x_mean = sum(x_values) / len(x_values)
        y_mean = sum(amounts) / len(amounts)
        denominator = sum((x_value - x_mean) ** 2 for x_value in x_values)
        if denominator == 0:
            return None

        numerator = sum(
            (x_value - x_mean) * (amount - y_mean)
            for x_value, amount in zip(x_values, amounts)
        )
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean
        predicted_amount = intercept + slope * len(amounts)
        return max(predicted_amount, 0.0)

    def _seasonal_key(self, cadence_name: str, pay_date: date) -> int:
        if cadence_name == "quarterly":
            return (pay_date.month - 1) // 3
        if cadence_name == "semiannual":
            return 0 if pay_date.month <= 6 else 1
        if cadence_name == "annual":
            return pay_date.month
        return pay_date.month

    def _parse_date(self, value: str | None) -> date:
        if value is None:
            raise ValueError("pay_date is required for estimation")
        return date.fromisoformat(value)
