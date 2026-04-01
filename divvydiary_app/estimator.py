from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from .models import DividendEstimate, DividendEvent, SecurityDividendHistory


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

    def estimate(self, history: SecurityDividendHistory) -> DividendEstimate:
        confirmed_dividends = self._confirmed_dividends(history)
        if len(confirmed_dividends) < 2:
            return DividendEstimate(
                next_payment_date=None,
                next_payment_amount=None,
                confidence="low",
                basis="insufficient_history",
            )

        cadence = self._detect_cadence(confirmed_dividends)
        if cadence is None:
            return DividendEstimate(
                next_payment_date=None,
                next_payment_amount=None,
                confidence="low",
                basis="irregular_history",
            )

        next_payment_date = self._estimate_next_payment_date(confirmed_dividends, cadence)
        next_payment_amount, amount_basis = self._estimate_next_payment_amount(
            confirmed_dividends,
            cadence,
            next_payment_date,
        )

        confidence = "high" if amount_basis.endswith("same_season") else "medium"
        return DividendEstimate(
            next_payment_date=next_payment_date,
            next_payment_amount=next_payment_amount,
            confidence=confidence,
            basis=amount_basis,
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
    ) -> str | None:
        latest_pay_date = self._parse_date(dividends[-1].pay_date)
        return (latest_pay_date + timedelta(days=cadence.median_gap_days)).isoformat()

    def _estimate_next_payment_amount(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
        next_payment_date: str | None,
    ) -> tuple[float | None, str]:
        latest_dividend = dividends[-1]
        if next_payment_date is None:
            return latest_dividend.amount, f"{cadence.name}_last_payment_fallback"

        next_pay_date = self._parse_date(next_payment_date)
        seasonal_match = self._find_same_season_match(dividends[:-1], cadence.name, next_pay_date)
        if seasonal_match is not None:
            return seasonal_match.amount, f"{cadence.name}_same_season"

        return latest_dividend.amount, f"{cadence.name}_last_payment_fallback"

    def _find_same_season_match(
        self,
        dividends: list[DividendEvent],
        cadence_name: str,
        next_pay_date: date,
    ) -> DividendEvent | None:
        if cadence_name == "monthly":
            return dividends[-1] if dividends else None

        target_key = self._seasonal_key(cadence_name, next_pay_date)
        for dividend in reversed(dividends):
            pay_date = self._parse_date(dividend.pay_date)
            if self._seasonal_key(cadence_name, pay_date) == target_key:
                return dividend
        return None

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
