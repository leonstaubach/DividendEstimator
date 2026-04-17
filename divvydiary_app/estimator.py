from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median, mean, stdev

from .models import DividendEstimate, DividendEvent, ForecastDividendEvent, SecurityDividendHistory


@dataclass(frozen=True)
class CadenceInfo:
    name: str
    median_gap_days: int
    match_ratio: float


@dataclass(frozen=True)
class WeightedTrendPoint:
    pay_date: str
    amount: float
    weight: float


@dataclass(frozen=True)
class TrendAnalysis:
    points: list[WeightedTrendPoint]
    regression_prediction: float
    latest_amount: float
    blended_prediction: float
    r_squared: float
    was_capped: bool
    uncapped_prediction: float
    growth_rate: float | None


@dataclass(frozen=True)
class ForecastExplanation:
    steps_ahead: int
    cadence: CadenceInfo
    latest_pay_date: str
    predicted_pay_date: str | None
    predicted_ex_date: str | None
    predicted_amount: float | None
    confidence: str
    confidence_score: float
    basis: str
    all_confirmed_dividends: list[DividendEvent]
    seasonal_dividends: list[DividendEvent]
    latest_dividend: DividendEvent
    chosen_reference_dividend: DividendEvent | None
    trend_analysis: TrendAnalysis | None
    median_ex_to_pay_gap_days: int | None
    outliers_removed: list[DividendEvent]
    suspension_detected: bool
    history_start_date: str | None
    cadence_regime_change: bool


@dataclass(frozen=True)
class PreparedDividendHistory:
    dividends: list[DividendEvent]
    cadence: CadenceInfo | None
    outliers_removed: list[DividendEvent]
    suspension_detected: bool
    history_start_date: str | None
    cadence_regime_change: bool


class DividendEstimator:
    SEASONAL_BOUNDARY_SHIFT_DAYS = 14
    RECENCY_WEIGHT_GROWTH = 1.5
    TREND_BLEND_WEIGHT = 0.7
    IQR_OUTLIER_FENCE = 2.5
    MAX_GROWTH_FACTOR = 1.20
    MIN_RETENTION_FACTOR = 0.60
    SUSPENSION_GAP_DAYS = 600
    REGIME_WINDOW = 3
    CADENCE_BUCKETS = {
        "monthly": (25, 40),
        "quarterly": (70, 110),
        "semiannual": (150, 220),
        "annual": (330, 390),
    }
    CADENCE_TYPICAL_DAYS: dict[str, int] = {
        "monthly": 30,
        "quarterly": 91,
        "semiannual": 182,
        "annual": 365,
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

        prepared_history = self._prepare_history(confirmed_dividends, history.security.dividend_frequency)
        cadence = prepared_history.cadence
        if cadence is None:
            return DividendEstimate(
                next_ex_date=None,
                next_payment_date=None,
                next_payment_amount=None,
                confidence="low",
                basis="irregular_history",
                forecast_events=[],
            )

        effective_dividends = prepared_history.dividends
        forecast_events = self._forecast_events(effective_dividends, cadence)
        first_forecast = forecast_events[0]
        amount, amount_basis, trend_analysis = self._estimate_payment_amount_full(
            effective_dividends, cadence, first_forecast.pay_date
        )
        confidence, confidence_score = self._score_confidence(
            effective_dividends, cadence.match_ratio, trend_analysis, amount_basis
        )
        return DividendEstimate(
            next_ex_date=first_forecast.ex_date,
            next_payment_date=first_forecast.pay_date,
            next_payment_amount=amount,
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

    def _remove_outliers(
        self,
        dividends: list[DividendEvent],
        cadence_name: str | None = None,
    ) -> tuple[list[DividendEvent], list[DividendEvent]]:
        if cadence_name is None or cadence_name == "monthly":
            return self._remove_outliers_from_group(dividends)

        grouped_dividends: dict[int, list[DividendEvent]] = {}
        for dividend in dividends:
            pay_date = self._parse_date(dividend.pay_date)
            key = self._seasonal_key(cadence_name, pay_date)
            grouped_dividends.setdefault(key, []).append(dividend)

        clean_ids: set[int] = set()
        removed_ids: set[int] = set()
        for seasonal_group in grouped_dividends.values():
            clean_group, removed_group = self._remove_outliers_from_group(seasonal_group)
            clean_ids.update(id(dividend) for dividend in clean_group)
            removed_ids.update(id(dividend) for dividend in removed_group)

        clean = [dividend for dividend in dividends if id(dividend) in clean_ids]
        removed = [dividend for dividend in dividends if id(dividend) in removed_ids]
        if len(clean) < 2:
            return dividends, []
        return clean, removed

    def _remove_outliers_from_group(
        self,
        dividends: list[DividendEvent],
    ) -> tuple[list[DividendEvent], list[DividendEvent]]:
        if len(dividends) < 4:
            return dividends, []
        amounts = [d.amount for d in dividends if d.amount is not None]
        if len(amounts) < 4:
            return dividends, []
        sorted_amounts = sorted(amounts)
        n = len(sorted_amounts)
        q1 = sorted_amounts[n // 4]
        q3 = sorted_amounts[(3 * n) // 4]
        iqr = q3 - q1
        if iqr == 0:
            return dividends, []
        med = median(amounts)
        fence = self.IQR_OUTLIER_FENCE * iqr
        clean = [d for d in dividends if d.amount is not None and abs(d.amount - med) <= fence]
        removed = [d for d in dividends if d not in clean]
        if len(clean) < 2:
            return dividends, []
        return clean, removed

    def _prepare_history(
        self,
        confirmed_dividends: list[DividendEvent],
        frequency_hint: str | None,
    ) -> PreparedDividendHistory:
        effective_dividends, suspension_detected, history_start_date = self._split_at_suspensions(
            confirmed_dividends
        )
        provisional_cadence, regime_change, effective_dividends = self._detect_cadence_with_regime(
            effective_dividends, frequency_hint
        )
        clean_dividends, outliers_removed = self._remove_outliers(
            effective_dividends,
            provisional_cadence.name if provisional_cadence is not None else None,
        )
        cadence = self._detect_cadence(clean_dividends, frequency_hint)
        return PreparedDividendHistory(
            dividends=clean_dividends,
            cadence=cadence or provisional_cadence,
            outliers_removed=outliers_removed,
            suspension_detected=suspension_detected,
            history_start_date=history_start_date,
            cadence_regime_change=regime_change,
        )

    def _split_at_suspensions(
        self, dividends: list[DividendEvent]
    ) -> tuple[list[DividendEvent], bool, str | None]:
        if len(dividends) < 2:
            return dividends, False, None
        pay_dates = [self._parse_date(d.pay_date) for d in dividends if d.pay_date]
        last_suspension_idx = -1
        for i, (prev, curr) in enumerate(zip(pay_dates, pay_dates[1:]), 1):
            if (curr - prev).days > self.SUSPENSION_GAP_DAYS:
                last_suspension_idx = i
        if last_suspension_idx == -1:
            return dividends, False, None
        post_suspension = dividends[last_suspension_idx:]
        if len(post_suspension) < 2:
            return dividends, False, None
        start_date = post_suspension[0].pay_date
        return post_suspension, True, start_date

    def _detect_cadence_with_regime(
        self,
        dividends: list[DividendEvent],
        frequency_hint: str | None = None,
    ) -> tuple[CadenceInfo | None, bool, list[DividendEvent]]:
        pay_dates = [self._parse_date(d.pay_date) for d in dividends if d.pay_date]
        gaps = [(curr - prev).days for prev, curr in zip(pay_dates, pay_dates[1:])]

        if len(gaps) >= self.REGIME_WINDOW * 2:
            recent_gaps = gaps[-self.REGIME_WINDOW:]
            older_gaps = gaps[:-self.REGIME_WINDOW]
            recent_cadence = self._best_cadence_for_gaps(recent_gaps)
            older_cadence = self._best_cadence_for_gaps(older_gaps)
            if (
                recent_cadence is not None
                and older_cadence is not None
                and recent_cadence != older_cadence
            ):
                # Regime change: trim to recent segment
                cutoff_idx = len(dividends) - self.REGIME_WINDOW - 1
                recent_dividends = dividends[max(0, cutoff_idx):]
                cadence = self._detect_cadence(recent_dividends, frequency_hint)
                return cadence, True, recent_dividends

        cadence = self._detect_cadence(dividends, frequency_hint)
        return cadence, False, dividends

    def _best_cadence_for_gaps(self, gaps: list[int]) -> str | None:
        matched: dict[str, list[int]] = {}
        for cadence_name, (lower, upper) in self.CADENCE_BUCKETS.items():
            matches = [g for g in gaps if lower <= g <= upper]
            if matches:
                matched[cadence_name] = matches
        if not matched:
            return None
        return max(matched.items(), key=lambda item: len(item[1]))[0]

    def _detect_cadence(
        self,
        dividends: list[DividendEvent],
        frequency_hint: str | None = None,
    ) -> CadenceInfo | None:
        pay_dates = [self._parse_date(d.pay_date) for d in dividends if d.pay_date]
        gaps = [(curr - prev).days for prev, curr in zip(pay_dates, pay_dates[1:])]
        if not gaps:
            return None

        matched_gaps: dict[str, list[int]] = {}
        for cadence_name, (lower, upper) in self.CADENCE_BUCKETS.items():
            matches = [gap for gap in gaps if lower <= gap <= upper]
            if matches:
                matched_gaps[cadence_name] = matches

        if not matched_gaps:
            # Fall back to API frequency hint
            if frequency_hint and frequency_hint in self.CADENCE_TYPICAL_DAYS:
                typical = self.CADENCE_TYPICAL_DAYS[frequency_hint]
                return CadenceInfo(name=frequency_hint, median_gap_days=typical, match_ratio=0.0)
            return None

        # Break ties using hint
        if frequency_hint and frequency_hint in matched_gaps:
            candidates = {k: v for k, v in matched_gaps.items() if len(v) == max(len(v2) for v2 in matched_gaps.values())}
            if frequency_hint in candidates:
                best_name = frequency_hint
                best_matches = matched_gaps[frequency_hint]
            else:
                best_name, best_matches = max(
                    matched_gaps.items(),
                    key=lambda item: (len(item[1]), -abs(median(item[1]) - median(gaps))),
                )
        else:
            best_name, best_matches = max(
                matched_gaps.items(),
                key=lambda item: (len(item[1]), -abs(median(item[1]) - median(gaps))),
            )

        minimum_matches = max(2, (len(gaps) + 1) // 2)
        if len(best_matches) < minimum_matches:
            if frequency_hint and frequency_hint in self.CADENCE_TYPICAL_DAYS:
                typical = self.CADENCE_TYPICAL_DAYS[frequency_hint]
                return CadenceInfo(name=frequency_hint, median_gap_days=typical, match_ratio=0.0)
            return None

        match_ratio = len(best_matches) / len(gaps)
        return CadenceInfo(
            name=best_name,
            median_gap_days=int(median(best_matches)),
            match_ratio=match_ratio,
        )

    def _estimate_next_payment_date(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
        steps_ahead: int = 1,
    ) -> str | None:
        latest_pay_date = self._parse_date(dividends[-1].pay_date)
        projected = latest_pay_date + timedelta(days=cadence.median_gap_days * steps_ahead)

        # Calendar anchoring for steps > 1 on non-monthly cadences
        if steps_ahead > 1 and cadence.name != "monthly":
            days = [self._parse_date(d.pay_date).day for d in dividends if d.pay_date]
            if days:
                typical_day = int(median(days))
                max_day = calendar.monthrange(projected.year, projected.month)[1]
                try:
                    projected = projected.replace(day=min(typical_day, max_day))
                except ValueError:
                    pass

        return projected.isoformat()

    def _estimate_payment_amount(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
        payment_date: str | None,
    ) -> tuple[float | None, str]:
        amount, basis, _ = self._estimate_payment_amount_full(dividends, cadence, payment_date)
        return amount, basis

    def _estimate_payment_amount_full(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
        payment_date: str | None,
    ) -> tuple[float | None, str, TrendAnalysis | None]:
        latest_dividend = dividends[-1]
        if payment_date is None:
            return latest_dividend.amount, f"{cadence.name}_last_payment_fallback", None

        # Monthly bypass: trend over all recent months, skip seasonal bucketing
        if cadence.name == "monthly":
            recent = dividends[-12:]
            trend_analysis = self._trend_analysis(recent, reference_amount=None)
            if trend_analysis is not None:
                return trend_analysis.blended_prediction, f"{cadence.name}_trend", trend_analysis
            return latest_dividend.amount, f"{cadence.name}_last_payment_fallback", None

        next_pay_date = self._parse_date(payment_date)
        seasonal_dividends = self._seasonal_dividends(dividends, cadence.name, next_pay_date)
        reference_amount = seasonal_dividends[-1].amount if seasonal_dividends else None

        # Try YoY growth rate first if we have ≥ 2 same-season data points
        if len(seasonal_dividends) >= 2:
            growth_rate = self._yoy_growth_rate(seasonal_dividends)
            if growth_rate is not None and abs(growth_rate) > 0.005:
                latest_seasonal = seasonal_dividends[-1]
                raw_predicted = (latest_seasonal.amount or 0.0) * (1 + growth_rate)
                capped, was_capped = self._apply_growth_cap(raw_predicted, reference_amount)
                # Try to build a full regression TrendAnalysis; fall back to a minimal one
                base_trend = self._trend_analysis(seasonal_dividends, reference_amount=reference_amount)
                if base_trend is not None:
                    trend_analysis = TrendAnalysis(
                        points=base_trend.points,
                        regression_prediction=base_trend.regression_prediction,
                        latest_amount=base_trend.latest_amount,
                        blended_prediction=capped,
                        r_squared=base_trend.r_squared,
                        was_capped=was_capped,
                        uncapped_prediction=raw_predicted,
                        growth_rate=growth_rate,
                    )
                else:
                    usable = [d for d in seasonal_dividends if d.amount is not None]
                    weights = [self.RECENCY_WEIGHT_GROWTH ** i for i in range(len(usable))]
                    trend_analysis = TrendAnalysis(
                        points=[
                            WeightedTrendPoint(
                                pay_date=d.pay_date or "-",
                                amount=d.amount or 0.0,
                                weight=w,
                            )
                            for d, w in zip(usable, weights)
                        ],
                        regression_prediction=capped,
                        latest_amount=latest_seasonal.amount or 0.0,
                        blended_prediction=capped,
                        r_squared=0.0,
                        was_capped=was_capped,
                        uncapped_prediction=raw_predicted,
                        growth_rate=growth_rate,
                    )
                return capped, f"{cadence.name}_trend", trend_analysis

        # Fall back to regression trend if ≥ 3 same-season points
        trend_analysis = self._trend_analysis(seasonal_dividends, reference_amount=reference_amount)
        if trend_analysis is not None:
            return trend_analysis.blended_prediction, f"{cadence.name}_trend", trend_analysis

        if seasonal_dividends:
            return seasonal_dividends[-1].amount, f"{cadence.name}_same_season", None

        return latest_dividend.amount, f"{cadence.name}_last_payment_fallback", None

    def _apply_growth_cap(
        self, predicted: float, reference_amount: float | None
    ) -> tuple[float, bool]:
        if reference_amount is None or reference_amount <= 0:
            return max(predicted, 0.0), False
        lo = reference_amount * self.MIN_RETENTION_FACTOR
        hi = reference_amount * self.MAX_GROWTH_FACTOR
        capped = max(lo, min(hi, predicted))
        was_capped = abs(capped - predicted) > 1e-9
        return capped, was_capped

    def _yoy_growth_rate(self, seasonal_dividends: list[DividendEvent]) -> float | None:
        amounts = [d.amount for d in seasonal_dividends if d.amount is not None]
        if len(amounts) < 2:
            return None
        growth_rates = [(amounts[i] / amounts[i - 1]) - 1.0 for i in range(1, len(amounts))]
        weights = [self.RECENCY_WEIGHT_GROWTH ** i for i in range(len(growth_rates))]
        weight_sum = sum(weights)
        if weight_sum == 0:
            return None
        weighted_growth = sum(r * w for r, w in zip(growth_rates, weights)) / weight_sum
        return max(-0.25, min(0.30, weighted_growth))

    def _score_confidence(
        self,
        dividends: list[DividendEvent],
        cadence_match_ratio: float,
        trend: TrendAnalysis | None,
        basis: str,
    ) -> tuple[str, float]:
        if basis in ("insufficient_history", "irregular_history"):
            return "low", 0.0

        amounts = [d.amount for d in dividends if d.amount is not None]
        count_score = min(len(amounts) / 8.0, 1.0)

        if len(amounts) >= 2 and mean(amounts) > 0:
            cv = stdev(amounts) / mean(amounts)
            cv_score = max(0.0, 1.0 - cv * 2.0)
        else:
            cv_score = 0.0

        r_squared_score = trend.r_squared if trend is not None else 0.0

        total = (
            0.35 * count_score
            + 0.30 * cv_score
            + 0.20 * cadence_match_ratio
            + 0.15 * r_squared_score
        )
        total = round(min(max(total, 0.0), 1.0), 3)

        if total >= 0.70:
            label = "high"
        elif total >= 0.40:
            label = "medium"
        else:
            label = "low"
        return label, total

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

    def _compute_monthly_variance_factors(self, dividends: list[DividendEvent]) -> list[float]:
        """Return relative factors (actual / mean) for the last ≤12 actual payments.

        Multiplying a smooth prediction by one of these factors scales it to a
        historically-plausible value while preserving the current trend level.
        For a flat asset the factors are all ~1.0; for a variable asset they span
        the same relative spread as the history.
        """
        actual = [d for d in dividends if not d.forecast and d.amount is not None]
        recent = actual[-12:]
        amounts = [d.amount for d in recent if d.amount is not None]
        if len(amounts) < 2:
            return []
        mu = mean(amounts)
        if mu <= 0:
            return []
        return [a / mu for a in amounts]

    def _make_forecast_rng(self, dividends: list[DividendEvent]) -> random.Random:
        actual = [d for d in dividends if not d.forecast and d.amount is not None]
        seed = hash(tuple(round((d.amount or 0.0) * 1_000_000) for d in actual[-6:]))
        return random.Random(seed)

    def _forecast_events(
        self,
        dividends: list[DividendEvent],
        cadence: CadenceInfo,
    ) -> list[ForecastDividendEvent]:
        event_count = self.FORECAST_EVENT_COUNTS[cadence.name]
        forecast_events: list[ForecastDividendEvent] = []
        is_monthly = cadence.name == "monthly"
        working_history = list(dividends)

        # For monthly assets: compute the anchor amount once from the original confirmed
        # history, then vary each of the 12 displayed forecasts around that anchor using
        # relative historical factors.  This avoids the feedback-loop where feeding an
        # elevated prediction back into the regression window causes subsequent predictions
        # to drift monotonically upward.  Dates still use the iterative working_history
        # approach for timeline consistency (pay_date is all that matters for dates).
        anchor_amount: float | None = None
        shuffled_factors: list[float] = []
        if is_monthly:
            anchor_pay_date = self._estimate_next_payment_date(dividends, cadence, 1)
            anchor_amount, _ = self._estimate_payment_amount(dividends, cadence, anchor_pay_date)
            factors = self._compute_monthly_variance_factors(dividends)
            if factors:
                # Tile to cover all 12 forecast steps, then shuffle once with a seeded
                # RNG.  Using a shuffle (rather than repeated rng.choice) guarantees that
                # no accidental monotonic ordering can arise from an unlucky seed — every
                # historical relative scale is used at least once across the 12 steps.
                rng = self._make_forecast_rng(dividends)
                pool = (factors * ((event_count // len(factors)) + 1))[:event_count]
                rng.shuffle(pool)
                shuffled_factors = pool

        for steps_ahead in range(1, event_count + 1):
            if is_monthly:
                payment_date = self._estimate_next_payment_date(working_history, cadence, 1)
                if shuffled_factors and anchor_amount is not None:
                    displayed_amount: float | None = max(0.0, anchor_amount * shuffled_factors[steps_ahead - 1])
                else:
                    displayed_amount = anchor_amount
            else:
                payment_date = self._estimate_next_payment_date(dividends, cadence, steps_ahead)
                displayed_amount, _ = self._estimate_payment_amount(dividends, cadence, payment_date)
            ex_date = self._estimate_next_ex_date(dividends, payment_date)
            forecast_events.append(
                ForecastDividendEvent(
                    ex_date=ex_date,
                    pay_date=payment_date,
                    amount=displayed_amount,
                    currency=dividends[-1].currency,
                    forecast=True,
                )
            )
            if is_monthly:
                working_history.append(
                    DividendEvent(
                        id=-steps_ahead,
                        ex_date=ex_date,
                        pay_date=payment_date,
                        amount=displayed_amount,
                        currency=dividends[-1].currency,
                        forecast=True,
                    )
                )

        return forecast_events

    def explain_forecast(
        self,
        history: SecurityDividendHistory,
        steps_ahead: int = 1,
    ) -> ForecastExplanation | None:
        confirmed_dividends = self._confirmed_dividends(history)
        if len(confirmed_dividends) < 2:
            return None

        prepared_history = self._prepare_history(confirmed_dividends, history.security.dividend_frequency)
        cadence = prepared_history.cadence
        if cadence is None:
            return None
        effective_dividends = prepared_history.dividends
        outliers_removed = prepared_history.outliers_removed
        suspension_detected = prepared_history.suspension_detected
        history_start_date = prepared_history.history_start_date
        regime_change = prepared_history.cadence_regime_change

        monthly_display_dividends = effective_dividends
        # For monthly, iterate like _forecast_events so each step feeds into the next.
        # This gives the explanation for step N the same prior-forecast context that
        # produced the actual forecast event shown in the UI.
        if cadence.name == "monthly" and steps_ahead >= 1:
            # Mirror _forecast_events(): compute anchor + shuffled factors from the
            # original confirmed history so prior-step amounts are varianced (not smooth),
            # matching the bars already shown in the timeline view.
            anchor_pay_date = self._estimate_next_payment_date(effective_dividends, cadence, 1)
            anchor_amount, _ = self._estimate_payment_amount(effective_dividends, cadence, anchor_pay_date)
            factors = self._compute_monthly_variance_factors(effective_dividends)
            shuffled_factors: list[float] = []
            if factors:
                rng = self._make_forecast_rng(effective_dividends)
                pool = (factors * ((steps_ahead // len(factors)) + 1))[:steps_ahead]
                rng.shuffle(pool)
                shuffled_factors = pool

            working_history = list(effective_dividends)
            for step in range(1, steps_ahead + 1):
                step_pay_date = self._estimate_next_payment_date(working_history, cadence, 1)
                step_amount, step_basis, step_trend = self._estimate_payment_amount_full(
                    working_history, cadence, step_pay_date
                )
                step_ex_date = self._estimate_next_ex_date(working_history, step_pay_date)
                # Use the varianced amount for both the prior-step context and the final
                # predicted_amount so the modal chart matches the timeline view exactly.
                if shuffled_factors and anchor_amount is not None:
                    varianced_amount: float | None = max(0.0, anchor_amount * shuffled_factors[step - 1])
                else:
                    varianced_amount = step_amount
                if step < steps_ahead:
                    working_history.append(
                        DividendEvent(
                            id=-step,
                            ex_date=step_ex_date,
                            pay_date=step_pay_date,
                            amount=varianced_amount,
                            currency=working_history[-1].currency,
                            forecast=True,
                        )
                    )
            monthly_display_dividends = working_history
            payment_date = step_pay_date
            ex_date = step_ex_date
            predicted_amount = varianced_amount
            basis = step_basis
            trend_analysis = step_trend
        else:
            payment_date = self._estimate_next_payment_date(effective_dividends, cadence, steps_ahead)
            ex_date = self._estimate_next_ex_date(effective_dividends, payment_date)
            predicted_amount, basis, trend_analysis = self._estimate_payment_amount_full(
                effective_dividends, cadence, payment_date
            )
        confidence, confidence_score = self._score_confidence(
            effective_dividends, cadence.match_ratio, trend_analysis, basis
        )

        latest_dividend = effective_dividends[-1]
        seasonal_dividends: list[DividendEvent] = []
        chosen_reference_dividend: DividendEvent | None = None

        if payment_date is not None and cadence.name != "monthly":
            next_pay_date = self._parse_date(payment_date)
            seasonal_dividends = self._seasonal_dividends(effective_dividends, cadence.name, next_pay_date)
            if trend_analysis is not None and seasonal_dividends:
                chosen_reference_dividend = seasonal_dividends[-1]
            elif basis.endswith("_same_season") and seasonal_dividends:
                chosen_reference_dividend = seasonal_dividends[-1]
            elif basis.endswith("_last_payment_fallback"):
                chosen_reference_dividend = latest_dividend
        elif cadence.name == "monthly":
            # For monthly, "seasonal" = all recent dividends used for the trend,
            # including any prior forecast steps leading up to this one. There is
            # no single "reference" payment under the iterative trend model.
            seasonal_dividends = monthly_display_dividends[-12:]

        median_ex_to_pay_gap_days = self._median_ex_to_pay_gap_days(effective_dividends)

        return ForecastExplanation(
            steps_ahead=steps_ahead,
            cadence=cadence,
            latest_pay_date=latest_dividend.pay_date or "",
            predicted_pay_date=payment_date,
            predicted_ex_date=ex_date,
            predicted_amount=predicted_amount,
            confidence=confidence,
            confidence_score=confidence_score,
            basis=basis,
            all_confirmed_dividends=effective_dividends,
            seasonal_dividends=seasonal_dividends,
            latest_dividend=latest_dividend,
            chosen_reference_dividend=chosen_reference_dividend,
            trend_analysis=trend_analysis,
            median_ex_to_pay_gap_days=median_ex_to_pay_gap_days,
            outliers_removed=outliers_removed,
            suspension_detected=suspension_detected,
            history_start_date=history_start_date,
            cadence_regime_change=regime_change,
        )

    def _seasonal_dividends(
        self,
        dividends: list[DividendEvent],
        cadence_name: str,
        next_pay_date: date,
    ) -> list[DividendEvent]:
        target_key = self._seasonal_key(cadence_name, next_pay_date)
        matches: list[DividendEvent] = []
        for dividend in dividends:
            pay_date = self._parse_date(dividend.pay_date)
            if self._seasonal_key(cadence_name, pay_date) == target_key:
                matches.append(dividend)
        return matches

    def _trend_analysis(
        self,
        dividends: list[DividendEvent],
        reference_amount: float | None = None,
    ) -> TrendAnalysis | None:
        amounts = [dividend.amount for dividend in dividends if dividend.amount is not None]
        if len(amounts) < 3:
            return None

        x_values = list(range(len(amounts)))
        weights = [self.RECENCY_WEIGHT_GROWTH ** index for index in range(len(amounts))]
        weight_sum = sum(weights)
        if weight_sum == 0:
            return None

        x_mean = sum(w * x for w, x in zip(weights, x_values)) / weight_sum
        y_mean = sum(w * y for w, y in zip(weights, amounts)) / weight_sum
        denominator = sum(w * (x - x_mean) ** 2 for w, x in zip(weights, x_values))
        if denominator == 0:
            return None

        numerator = sum(
            w * (x - x_mean) * (y - y_mean)
            for w, x, y in zip(weights, x_values, amounts)
        )
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean
        regression_prediction = intercept + slope * len(amounts)

        r_squared = self._compute_r_squared(x_values, amounts, weights, slope, intercept)

        latest_amount = amounts[-1]
        raw_blended = (
            self.TREND_BLEND_WEIGHT * regression_prediction
            + (1 - self.TREND_BLEND_WEIGHT) * latest_amount
        )
        raw_blended = max(raw_blended, 0.0)

        capped, was_capped = self._apply_growth_cap(raw_blended, reference_amount)

        usable_dividends = [d for d in dividends if d.amount is not None]
        return TrendAnalysis(
            points=[
                WeightedTrendPoint(
                    pay_date=dividend.pay_date or "-",
                    amount=dividend.amount or 0.0,
                    weight=weight,
                )
                for dividend, weight in zip(usable_dividends, weights)
            ],
            regression_prediction=max(regression_prediction, 0.0),
            latest_amount=latest_amount,
            blended_prediction=capped,
            r_squared=r_squared,
            was_capped=was_capped,
            uncapped_prediction=raw_blended,
            growth_rate=None,
        )

    def _compute_r_squared(
        self,
        x_values: list[int],
        y_values: list[float],
        weights: list[float],
        slope: float,
        intercept: float,
    ) -> float:
        weight_sum = sum(weights)
        if weight_sum == 0:
            return 0.0
        y_mean = sum(w * y for w, y in zip(weights, y_values)) / weight_sum
        ss_res = sum(w * (y - (intercept + slope * x)) ** 2 for w, x, y in zip(weights, x_values, y_values))
        ss_tot = sum(w * (y - y_mean) ** 2 for w, y in zip(weights, y_values))
        if ss_tot == 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - ss_res / ss_tot))

    def _median_ex_to_pay_gap_days(self, dividends: list[DividendEvent]) -> int | None:
        ex_to_pay_gaps = [
            (self._parse_date(dividend.pay_date) - self._parse_date(dividend.ex_date)).days
            for dividend in dividends
            if dividend.pay_date is not None and dividend.ex_date is not None
        ]
        if not ex_to_pay_gaps:
            return None
        return int(median(ex_to_pay_gaps))

    def _seasonal_key(self, cadence_name: str, pay_date: date) -> int:
        normalized_date = self._normalize_seasonal_date(pay_date)
        if cadence_name == "quarterly":
            return (normalized_date.month - 1) // 3
        if cadence_name == "semiannual":
            return 0 if normalized_date.month <= 6 else 1
        if cadence_name == "annual":
            return normalized_date.month
        return normalized_date.month

    def _normalize_seasonal_date(self, pay_date: date) -> date:
        return pay_date - timedelta(days=self.SEASONAL_BOUNDARY_SHIFT_DAYS)

    def _parse_date(self, value: str | None) -> date:
        if value is None:
            raise ValueError("pay_date is required for estimation")
        return date.fromisoformat(value)
