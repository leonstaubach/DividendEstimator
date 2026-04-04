from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .estimator import ForecastExplanation
from .models import (
    DividendEvent,
    EstimatedSecurityDividendHistory,
    ForecastDividendEvent,
    ResolvedPortfolio,
    Security,
)


@dataclass(frozen=True)
class MonthlyDividendRow:
    isin: str
    security_name: str
    security_code: str
    quantity: float
    ex_date: str
    pay_date: str
    amount_per_share: float | None
    total_amount: float | None
    currency: str | None
    is_estimated: bool
    forecast_index: int | None


@dataclass(frozen=True)
class MonthlyTimelineSection:
    caption: str
    month_key: str
    total_amount: float | None
    currency: str | None
    rows: list[MonthlyDividendRow]
    confirmed_rows: list[MonthlyDividendRow]
    estimated_rows: list[MonthlyDividendRow]
    is_previous_month: bool
    is_current_month: bool


@dataclass(frozen=True)
class PortfolioHoldingRow:
    index: int
    name: str
    isin: str
    code: str
    value: float
    portfolio_percentage: float
    is_selected: bool


@dataclass(frozen=True)
class SecurityForecastRow:
    index: int
    ex_date: str
    pay_date: str
    amount_per_share: float | None
    total_amount: float | None
    currency: str | None


@dataclass(frozen=True)
class SecurityHistoryRow:
    pay_date: str
    ex_date: str
    amount: float | None
    currency: str | None


@dataclass(frozen=True)
class SecurityChartView:
    labels: list[str]
    pay_dates: list[str]
    historical_per_share: list[float | None]
    forecast_per_share: list[float | None]
    historical_total: list[float | None]
    forecast_total: list[float | None]
    currency: str | None


@dataclass(frozen=True)
class ForecastRelevantDividendRow:
    pay_date: str
    ex_date: str
    amount: float | None
    currency: str | None
    weight: float | None
    is_reference: bool


@dataclass(frozen=True)
class OutlierDividendRow:
    pay_date: str | None
    amount: float


@dataclass(frozen=True)
class ForecastExplanationView:
    security_name: str
    isin: str
    code: str
    currency: str | None
    forecast_index: int
    predicted_ex_date: str | None
    predicted_pay_date: str | None
    predicted_amount: float | None
    predicted_total_amount: float | None
    confidence: str
    confidence_score: float
    basis: str
    cadence_name: str
    median_gap_days: int
    latest_pay_date: str
    latest_amount: float | None
    median_ex_to_pay_gap_days: int | None
    is_trend: bool
    is_same_season: bool
    is_last_payment_fallback: bool
    summary_lines: list[str]
    all_history_rows: list[SecurityHistoryRow]
    relevant_rows: list[ForecastRelevantDividendRow]
    regression_prediction: float | None
    blended_prediction: float | None
    latest_reference_amount: float | None
    outliers_removed_count: int
    outliers_removed_rows: list[OutlierDividendRow]
    suspension_detected: bool
    history_start_date: str | None
    cadence_regime_change: bool
    was_growth_capped: bool
    uncapped_prediction: float | None
    growth_rate: float | None


@dataclass(frozen=True)
class SecurityDetailView:
    name: str
    isin: str
    code: str
    currency: str | None
    quantity: float
    position_value: float
    allocation: float | None
    dividend_yield: float | None
    dividend_frequency: str | None
    sector: str | None
    next_ex_date: str | None
    next_payment_date: str | None
    next_payment_amount: float | None
    estimated_total_amount: float | None
    estimated_annual_total_amount: float | None
    confidence: str
    confidence_score: float
    basis: str
    basis_label: str
    cadence_name: str | None
    cadence_days: int | None
    forecast_rows: list[SecurityForecastRow]
    recent_history_rows: list[SecurityHistoryRow]
    chart: SecurityChartView | None


@dataclass(frozen=True)
class MonthlySummaryView:
    caption: str
    rows: list[MonthlyDividendRow]
    total_amount: float | None
    currency: str | None


@dataclass(frozen=True)
class DashboardView:
    portfolio_name: str
    user_forename: str
    portfolio_currency: str | None
    total_value: float
    holdings: list[PortfolioHoldingRow]
    monthly_summaries: list[MonthlySummaryView]
    selected_security: SecurityDetailView | None


@dataclass(frozen=True)
class MonthlyTimelineView:
    portfolio_name: str
    portfolio_currency: str | None
    total_value: float
    month_sections: list[MonthlyTimelineSection]


def build_dashboard_view(
    resolved_portfolio: ResolvedPortfolio,
    histories: list[EstimatedSecurityDividendHistory],
    selected_isin: str | None = None,
    reference_date: date | None = None,
) -> DashboardView:
    sorted_histories = sort_histories_by_value(histories)
    total_value = calculate_total_value(sorted_histories)
    selected_history = select_history(sorted_histories, selected_isin)

    return DashboardView(
        portfolio_name=resolved_portfolio.portfolio.name,
        user_forename=resolved_portfolio.user.forename,
        portfolio_currency=resolved_portfolio.portfolio.currency,
        total_value=total_value,
        holdings=build_holding_rows(sorted_histories, total_value, selected_history),
        monthly_summaries=build_monthly_summary_views(sorted_histories, reference_date),
        selected_security=(
            build_security_detail_view(selected_history, total_portfolio_value=total_value)
            if selected_history is not None else None
        ),
    )


def build_holding_rows(
    histories: list[EstimatedSecurityDividendHistory],
    total_value: float,
    selected_history: EstimatedSecurityDividendHistory | None,
) -> list[PortfolioHoldingRow]:
    return [
        PortfolioHoldingRow(
            index=index,
            name=history.security.name,
            isin=history.security.isin,
            code=security_code(history.security),
            value=security_value(history.security),
            portfolio_percentage=portfolio_percentage(security_value(history.security), total_value),
            is_selected=selected_history is not None and history.security.isin == selected_history.security.isin,
        )
        for index, history in enumerate(histories, start=1)
    ]


def build_monthly_summary_views(
    histories: list[EstimatedSecurityDividendHistory],
    reference_date: date | None = None,
) -> list[MonthlySummaryView]:
    active_date = reference_date or date.today()
    summaries: list[MonthlySummaryView] = []
    for month_date in surrounding_months(active_date):
        rows = monthly_dividend_rows(histories, month_date)
        summaries.append(
            MonthlySummaryView(
                caption=describe_month(month_date, active_date),
                rows=rows,
                total_amount=sum_total_amount(rows),
                currency=month_currency(rows),
            )
        )
    return summaries


def build_monthly_timeline_view(
    resolved_portfolio: ResolvedPortfolio,
    histories: list[EstimatedSecurityDividendHistory],
    reference_date: date | None = None,
    forward_months: int = 12,
) -> MonthlyTimelineView:
    active_date = reference_date or date.today()
    current_month = active_date.replace(day=1)
    month_sections: list[MonthlyTimelineSection] = []

    for month_date in monthly_timeline_range(current_month, forward_months):
        rows = monthly_dividend_rows(histories, month_date, include_all_forecasts=True)
        confirmed_rows = [row for row in rows if not row.is_estimated]
        estimated_rows = [row for row in rows if row.is_estimated]
        month_sections.append(
            MonthlyTimelineSection(
                caption=month_date.strftime("%B %Y"),
                month_key=month_date.isoformat(),
                total_amount=sum_total_amount(rows),
                currency=month_currency(rows) or resolved_portfolio.portfolio.currency,
                rows=rows,
                confirmed_rows=confirmed_rows,
                estimated_rows=estimated_rows,
                is_previous_month=month_date == shift_month(current_month, -1),
                is_current_month=month_date == current_month,
            )
        )

    return MonthlyTimelineView(
        portfolio_name=resolved_portfolio.portfolio.name,
        portfolio_currency=resolved_portfolio.portfolio.currency,
        total_value=calculate_total_value(histories),
        month_sections=month_sections,
    )


def build_security_detail_view(
    history: EstimatedSecurityDividendHistory,
    total_portfolio_value: float | None = None,
    explanation: ForecastExplanation | None = None,
) -> SecurityDetailView:
    forecast_rows = [
        SecurityForecastRow(
            index=index,
            ex_date=event.ex_date or "-",
            pay_date=event.pay_date or "-",
            amount_per_share=event.amount,
            total_amount=event_total_amount(event.amount, history.security.quantity),
            currency=event.currency or history.security.currency,
        )
        for index, event in enumerate(security_forecast_events(history), start=1)
    ]
    recent_history_rows = [
        SecurityHistoryRow(
            pay_date=event.pay_date or "-",
            ex_date=event.ex_date or "-",
            amount=event.amount,
            currency=event.currency or history.security.currency,
        )
        for event in latest_historical_dividends(history)
    ]
    position_value = security_value(history.security)

    return SecurityDetailView(
        name=history.security.name,
        isin=history.security.isin,
        code=security_code(history.security),
        currency=history.security.currency,
        quantity=history.security.quantity,
        position_value=position_value,
        allocation=(
            portfolio_percentage(position_value, total_portfolio_value)
            if total_portfolio_value is not None
            else None
        ),
        dividend_yield=history.security.dividend_yield,
        dividend_frequency=format_frequency_label(history.security.dividend_frequency),
        sector=history.security.sector,
        next_ex_date=history.estimate.next_ex_date,
        next_payment_date=history.estimate.next_payment_date,
        next_payment_amount=history.estimate.next_payment_amount,
        estimated_total_amount=estimate_total_amount(history),
        estimated_annual_total_amount=estimate_annual_total_amount(history),
        confidence=history.estimate.confidence,
        confidence_score=(
            explanation.confidence_score if explanation is not None else confidence_score_from_label(history.estimate.confidence)
        ),
        basis=history.estimate.basis,
        basis_label=describe_estimate_basis(history.estimate.basis),
        cadence_name=(
            explanation.cadence.name.title()
            if explanation is not None
            else format_frequency_label(history.security.dividend_frequency)
        ),
        cadence_days=explanation.cadence.median_gap_days if explanation is not None else None,
        forecast_rows=forecast_rows,
        recent_history_rows=recent_history_rows,
        chart=build_security_chart_view(history),
    )


def build_forecast_explanation_view(
    history: EstimatedSecurityDividendHistory,
    explanation: ForecastExplanation,
) -> ForecastExplanationView:
    basis_key = explanation.basis.split("_", 1)[1] if "_" in explanation.basis else explanation.basis
    relevant_rows: list[ForecastRelevantDividendRow] = []
    trend_points_by_date = {
        point.pay_date: point.weight
        for point in explanation.trend_analysis.points
    } if explanation.trend_analysis is not None else {}

    for event in explanation.seasonal_dividends:
        relevant_rows.append(
            ForecastRelevantDividendRow(
                pay_date=event.pay_date or "-",
                ex_date=event.ex_date or "-",
                amount=event.amount,
                currency=event.currency or history.security.currency,
                weight=trend_points_by_date.get(event.pay_date or ""),
                is_reference=(
                    explanation.chosen_reference_dividend is not None
                    and event.id == explanation.chosen_reference_dividend.id
                ),
            )
        )

    if basis_key == "last_payment_fallback" and not relevant_rows:
        event = explanation.latest_dividend
        relevant_rows.append(
            ForecastRelevantDividendRow(
                pay_date=event.pay_date or "-",
                ex_date=event.ex_date or "-",
                amount=event.amount,
                currency=event.currency or history.security.currency,
                weight=None,
                is_reference=True,
            )
        )

    trend = explanation.trend_analysis
    return ForecastExplanationView(
        security_name=history.security.name,
        isin=history.security.isin,
        code=security_code(history.security),
        currency=history.security.currency,
        forecast_index=explanation.steps_ahead,
        predicted_ex_date=explanation.predicted_ex_date,
        predicted_pay_date=explanation.predicted_pay_date,
        predicted_amount=explanation.predicted_amount,
        predicted_total_amount=event_total_amount(explanation.predicted_amount, history.security.quantity),
        confidence=explanation.confidence,
        confidence_score=explanation.confidence_score,
        basis=explanation.basis,
        cadence_name=explanation.cadence.name,
        median_gap_days=explanation.cadence.median_gap_days,
        latest_pay_date=explanation.latest_pay_date,
        latest_amount=explanation.latest_dividend.amount,
        median_ex_to_pay_gap_days=explanation.median_ex_to_pay_gap_days,
        is_trend=explanation.basis.endswith("_trend"),
        is_same_season=explanation.basis.endswith("_same_season"),
        is_last_payment_fallback=explanation.basis.endswith("_last_payment_fallback"),
        summary_lines=forecast_summary_lines(explanation),
        all_history_rows=[
            SecurityHistoryRow(
                pay_date=event.pay_date or "-",
                ex_date=event.ex_date or "-",
                amount=event.amount,
                currency=event.currency or history.security.currency,
            )
            for event in explanation.all_confirmed_dividends
        ],
        relevant_rows=relevant_rows,
        regression_prediction=trend.regression_prediction if trend else None,
        blended_prediction=trend.blended_prediction if trend else None,
        latest_reference_amount=(
            trend.latest_amount
            if trend is not None
            else explanation.chosen_reference_dividend.amount if explanation.chosen_reference_dividend is not None else None
        ),
        outliers_removed_count=len(explanation.outliers_removed),
        outliers_removed_rows=[
            OutlierDividendRow(pay_date=d.pay_date, amount=d.amount)
            for d in explanation.outliers_removed
            if d.amount is not None
        ],
        suspension_detected=explanation.suspension_detected,
        history_start_date=explanation.history_start_date,
        cadence_regime_change=explanation.cadence_regime_change,
        was_growth_capped=trend.was_capped if trend else False,
        uncapped_prediction=trend.uncapped_prediction if trend and trend.was_capped else None,
        growth_rate=trend.growth_rate if trend else None,
    )


def select_history(
    histories: list[EstimatedSecurityDividendHistory],
    selected_isin: str | None,
) -> EstimatedSecurityDividendHistory | None:
    if not histories:
        return None
    if selected_isin is None:
        return histories[0]

    for history in histories:
        if history.security.isin == selected_isin:
            return history
    return histories[0]


def monthly_dividend_rows(
    histories: list[EstimatedSecurityDividendHistory],
    month_date: date,
    include_all_forecasts: bool = False,
) -> list[MonthlyDividendRow]:
    rows: list[MonthlyDividendRow] = []

    for history in histories:
        seen_keys: set[tuple[str, float | None]] = set()
        for event in history.dividends:
            if event.pay_date is None or not is_same_month(event.pay_date, month_date):
                continue

            row = MonthlyDividendRow(
                isin=history.security.isin,
                security_name=history.security.name,
                security_code=security_code(history.security),
                quantity=history.security.quantity,
                ex_date=event.ex_date or "-",
                pay_date=event.pay_date,
                amount_per_share=event.amount,
                total_amount=event_total_amount(event.amount, history.security.quantity),
                currency=event.currency or history.security.currency,
                is_estimated=event.forecast,
                forecast_index=None,
            )
            rows.append(row)
            seen_keys.add((event.pay_date, event.amount))

        estimated_rows = estimated_monthly_dividend_rows(
            history,
            month_date,
            include_all_forecasts=include_all_forecasts,
        )
        for estimated_row in estimated_rows:
            if (estimated_row.pay_date, estimated_row.amount_per_share) not in seen_keys:
                rows.append(estimated_row)
                seen_keys.add((estimated_row.pay_date, estimated_row.amount_per_share))

    return sorted(rows, key=lambda row: (row.pay_date, row.security_name, row.security_code))


def estimated_monthly_dividend_rows(
    history: EstimatedSecurityDividendHistory,
    month_date: date,
    include_all_forecasts: bool = False,
) -> list[MonthlyDividendRow]:
    if history.estimate.forecast_events:
        forecast_events = history.estimate.forecast_events if include_all_forecasts else history.estimate.forecast_events[:1]
    elif history.estimate.next_payment_date is not None:
        forecast_events = [
            DividendEvent(
                id=0,
                ex_date=history.estimate.next_ex_date,
                pay_date=history.estimate.next_payment_date,
                amount=history.estimate.next_payment_amount,
                currency=history.security.currency,
                forecast=True,
            )
        ]
    else:
        forecast_events = []

    rows: list[MonthlyDividendRow] = []

    for forecast_index, event in enumerate(forecast_events, start=1):
        if event.pay_date is None or not is_same_month(event.pay_date, month_date):
            continue

        rows.append(
            MonthlyDividendRow(
                isin=history.security.isin,
                security_name=history.security.name,
                security_code=security_code(history.security),
                quantity=history.security.quantity,
                ex_date=event.ex_date or "-",
                pay_date=event.pay_date,
                amount_per_share=event.amount,
                total_amount=event_total_amount(event.amount, history.security.quantity),
                currency=event.currency or history.security.currency,
                is_estimated=True,
                forecast_index=forecast_index if history.estimate.forecast_events else None,
            )
        )

    return rows


def latest_historical_dividends(
    history: EstimatedSecurityDividendHistory,
) -> list[DividendEvent]:
    historical_events = sorted(
        [event for event in history.dividends if not event.forecast],
        key=dividend_sort_key,
        reverse=True,
    )
    if not historical_events:
        return []

    latest_event_date = event_date(historical_events[0])
    if latest_event_date is None:
        return historical_events

    cutoff_date = latest_event_date - timedelta(days=365 * 2)
    return [
        event
        for event in historical_events
        if event_date(event) is not None and event_date(event) >= cutoff_date
    ]
def forecast_summary_lines(explanation: ForecastExplanation) -> list[str]:
    cadence_label = explanation.cadence.name.capitalize()
    lines = [
        f"The estimator detected a {cadence_label.lower()} cadence using a median gap of {explanation.cadence.median_gap_days} days between confirmed payments.",
        f"The predicted pay date is {explanation.predicted_pay_date or 'n/a'}, starting from the latest confirmed pay date of {explanation.latest_pay_date}.",
    ]

    if explanation.median_ex_to_pay_gap_days is not None:
        lines.append(
            f"The ex date is estimated by subtracting the median ex-to-pay gap of {explanation.median_ex_to_pay_gap_days} days."
        )

    if explanation.outliers_removed:
        amounts_str = ", ".join(f"{d.amount:.4f}" for d in explanation.outliers_removed if d.amount is not None)
        lines.append(
            f"{len(explanation.outliers_removed)} outlier dividend(s) were excluded from the analysis as likely special payments (amounts: {amounts_str})."
        )

    if explanation.suspension_detected and explanation.history_start_date:
        lines.append(
            f"A dividend suspension was detected. Only post-resumption history from {explanation.history_start_date} onward is used."
        )

    if explanation.cadence_regime_change:
        lines.append(
            "The payment cadence appears to have changed recently. Only the most recent payments are used for the forecast."
        )

    trend = explanation.trend_analysis
    if explanation.basis.endswith("_trend"):
        if trend is not None and trend.growth_rate is not None:
            pct = trend.growth_rate * 100
            lines.append(
                f"The amount was predicted using a weighted year-over-year growth rate of {pct:+.1f}% applied to the latest matching seasonal payment."
            )
        else:
            lines.append(
                "The amount comes from a weighted trend line across matching seasonal dividends, then blends that trend with the latest matching seasonal payment."
            )
        if trend is not None and trend.was_capped:
            lines.append(
                f"The raw prediction was capped to the allowed growth range (−40% / +20% of the reference payment). Uncapped value was {trend.uncapped_prediction:.4f}."
            )
    elif explanation.basis.endswith("_same_season"):
        lines.append(
            "The amount reuses the latest dividend from the same seasonal slot because there was not enough same-slot history for a stable trend fit."
        )
    elif explanation.basis.endswith("_last_payment_fallback"):
        lines.append(
            "The amount falls back to the latest confirmed dividend because there was no stronger seasonal signal available."
        )

    return lines


def surrounding_months(reference_date: date) -> list[date]:
    return [
        shift_month(reference_date, -1),
        reference_date.replace(day=1),
        shift_month(reference_date, 1),
    ]


def monthly_timeline_range(reference_month: date, forward_months: int) -> list[date]:
    return [shift_month(reference_month, -1)] + [
        shift_month(reference_month, month_offset)
        for month_offset in range(forward_months)
    ]


def shift_month(reference_date: date, month_offset: int) -> date:
    month_index = (reference_date.year * 12 + reference_date.month - 1) + month_offset
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def describe_month(month_date: date, active_date: date) -> str:
    current_month = active_date.replace(day=1)
    if month_date == shift_month(current_month, -1):
        suffix = "previous month"
    elif month_date == current_month:
        suffix = "current month"
    else:
        suffix = "next month"
    return f"{month_date.strftime('%B %Y')} ({suffix})"


def is_same_month(iso_date: str, month_date: date) -> bool:
    parsed = date.fromisoformat(iso_date)
    return parsed.year == month_date.year and parsed.month == month_date.month


def sort_histories_by_value(
    histories: list[EstimatedSecurityDividendHistory],
) -> list[EstimatedSecurityDividendHistory]:
    return sorted(histories, key=lambda history: security_value(history.security), reverse=True)


def calculate_total_value(histories: list[EstimatedSecurityDividendHistory]) -> float:
    return sum(security_value(history.security) for history in histories)


def security_value(security: Security) -> float:
    if security.value is not None:
        return float(security.value)

    if security.price is not None:
        return float(security.quantity) * float(security.price)

    return 0.0


def security_code(security: Security) -> str:
    return security.symbol or security.wkn or "-"


def portfolio_percentage(
    security_position_value: float,
    total_value: float,
) -> float:
    if total_value == 0:
        return 0.0
    return (security_position_value / total_value) * 100


def dividend_sort_key(event: DividendEvent) -> str:
    return event.pay_date or event.ex_date or ""


def event_date(event: DividendEvent) -> date | None:
    raw_date = event.pay_date or event.ex_date
    if raw_date is None:
        return None
    return date.fromisoformat(raw_date)


def estimate_total_amount(history: EstimatedSecurityDividendHistory) -> float | None:
    return event_total_amount(history.estimate.next_payment_amount, history.security.quantity)


def estimate_annual_total_amount(history: EstimatedSecurityDividendHistory) -> float | None:
    totals = [
        event_total_amount(event.amount, history.security.quantity)
        for event in security_forecast_events(history)
        if event.amount is not None
    ]
    if totals:
        return sum(totals)
    return estimate_total_amount(history)


def event_total_amount(amount: float | None, quantity: float) -> float | None:
    if amount is None:
        return None
    return amount * quantity


def security_forecast_events(
    history: EstimatedSecurityDividendHistory,
) -> list[ForecastDividendEvent]:
    if history.estimate.forecast_events:
        return history.estimate.forecast_events
    if history.estimate.next_payment_date is None:
        return []
    return [
        ForecastDividendEvent(
            ex_date=history.estimate.next_ex_date,
            pay_date=history.estimate.next_payment_date,
            amount=history.estimate.next_payment_amount,
            currency=history.security.currency,
        )
    ]


def build_security_chart_view(history: EstimatedSecurityDividendHistory) -> SecurityChartView | None:
    confirmed_events = latest_historical_dividends(history)[-12:]
    forecast_events = security_forecast_events(history)
    if not confirmed_events and not forecast_events:
        return None

    labels: list[str] = []
    pay_dates: list[str] = []
    historical_per_share: list[float | None] = []
    forecast_per_share: list[float | None] = []
    historical_total: list[float | None] = []
    forecast_total: list[float | None] = []

    for event in confirmed_events:
        pay_date = event.pay_date or event.ex_date or "-"
        labels.append(chart_axis_label(pay_date))
        pay_dates.append(pay_date)
        historical_per_share.append(event.amount)
        forecast_per_share.append(None)
        historical_total.append(event_total_amount(event.amount, history.security.quantity))
        forecast_total.append(None)

    for event in forecast_events:
        pay_date = event.pay_date or event.ex_date or "-"
        labels.append(chart_axis_label(pay_date))
        pay_dates.append(pay_date)
        historical_per_share.append(None)
        forecast_per_share.append(event.amount)
        historical_total.append(None)
        forecast_total.append(event_total_amount(event.amount, history.security.quantity))

    return SecurityChartView(
        labels=labels,
        pay_dates=pay_dates,
        historical_per_share=historical_per_share,
        forecast_per_share=forecast_per_share,
        historical_total=historical_total,
        forecast_total=forecast_total,
        currency=history.security.currency,
    )


def sum_total_amount(rows: list[MonthlyDividendRow]) -> float | None:
    amounts = [row.total_amount for row in rows if row.total_amount is not None]
    if not amounts:
        return None
    return sum(amounts)


def month_currency(rows: list[MonthlyDividendRow]) -> str | None:
    for row in rows:
        if row.currency:
            return row.currency
    return None


def format_currency(amount: float | None, currency: str | None, decimals: int = 2) -> str:
    if amount is None:
        return "n/a"
    if currency:
        return f"{amount:,.{decimals}f} {currency}"
    return format_amount(amount, decimals=decimals)


def format_display_date(iso_date: str | None, include_weekday: bool = True) -> str:
    if not iso_date or iso_date == "-":
        return "n/a"
    parsed = date.fromisoformat(iso_date)
    if include_weekday:
        return parsed.strftime("%A, %-d %B %Y")
    return parsed.strftime("%-d %B %Y")


def format_quantity(quantity: float | None) -> str:
    if quantity is None:
        return "n/a"
    if float(quantity).is_integer():
        return f"{int(quantity):,}"
    return f"{quantity:,.4f}".rstrip("0").rstrip(".")


def format_amount(amount: float | None, decimals: int = 2) -> str:
    if amount is None:
        return "n/a"
    return f"{amount:,.{decimals}f}"


def confidence_score_from_label(confidence: str | None) -> float:
    mapping = {
        "low": 0.35,
        "medium": 0.62,
        "high": 0.84,
    }
    if confidence is None:
        return 0.0
    return mapping.get(confidence.lower(), 0.0)


def format_frequency_label(frequency: str | None) -> str | None:
    if not frequency:
        return None
    return frequency.replace("_", " ").title()


def describe_estimate_basis(basis: str | None) -> str:
    if not basis:
        return "Forecast estimate"

    cadence_prefixes = {"monthly", "quarterly", "semiannual", "annual"}
    parts = basis.split("_", 1)
    if len(parts) == 2 and parts[0] in cadence_prefixes:
        key = parts[1]
    else:
        key = basis

    mapping = {
        "trend": "Trend blend",
        "same_season": "Seasonal match",
        "last_payment_fallback": "Last payment fallback",
        "insufficient_history": "Insufficient history",
        "irregular_history": "Irregular history",
    }
    return mapping.get(key, key.replace("_", " ").title())


def chart_axis_label(iso_date: str | None) -> str:
    if not iso_date or iso_date == "-":
        return "n/a"
    parsed = date.fromisoformat(iso_date)
    return parsed.strftime("%b %Y")


def truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return f"{value[: width - 3]}..."
