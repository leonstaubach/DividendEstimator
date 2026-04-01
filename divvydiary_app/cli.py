from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from .models import DividendEvent, EstimatedSecurityDividendHistory
from .service import PortfolioService


@dataclass(frozen=True)
class MonthlyDividendRow:
    security_name: str
    security_code: str
    ex_date: str
    pay_date: str
    amount_per_share: float | None
    total_amount: float | None
    currency: str | None
    is_estimated: bool


def run_cli(
    service: PortfolioService,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> int:
    output_func("Loading portfolio...")
    resolved_portfolio = service.get_resolved_portfolio()
    output_func(f"Loaded portfolio '{resolved_portfolio.portfolio.name}'.")
    output_func("Loading dividend histories and calculating estimates...")
    estimated_histories = service.build_estimated_security_dividend_histories(resolved_portfolio)
    output_func(f"Loaded dividend histories for {len(estimated_histories)} securities.")
    sorted_histories = sort_histories_by_value(estimated_histories)

    while True:
        print_main_menu(
            resolved_portfolio.portfolio.name,
            resolved_portfolio.user.forename,
            resolved_portfolio.portfolio.currency,
            sorted_histories,
            output_func,
        )
        selected_option = prompt_main_menu(input_func, output_func)
        if selected_option is None:
            output_func("Goodbye.")
            return 0

        if selected_option == "1":
            print_monthly_dividend_view(sorted_histories, output_func=output_func)
            wait_for_enter(input_func, output_func)
            continue

        view_dividend_history(
            resolved_portfolio.portfolio.name,
            resolved_portfolio.user.forename,
            resolved_portfolio.portfolio.currency,
            sorted_histories,
            input_func,
            output_func,
        )


def print_main_menu(
    portfolio_name: str,
    user_forename: str,
    portfolio_currency: str | None,
    sorted_histories: list[EstimatedSecurityDividendHistory],
    output_func: Callable[[str], None],
) -> None:
    output_func("")
    output_func(f"Portfolio: {portfolio_name}")
    output_func(f"Total value: {format_currency(calculate_total_value(sorted_histories), portfolio_currency)}")
    output_func("")
    output_func("Menu")
    output_func("1. View monthly dividends")
    output_func("2. View dividend history")
    output_func("q. Quit")
    output_func("")


def prompt_main_menu(
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> str | None:
    while True:
        raw_value = input_func("Choose an option: ").strip().lower()
        if raw_value in {"q", "quit", "exit"}:
            return None
        if raw_value in {"1", "2"}:
            return raw_value
        output_func("Please enter 1, 2, or q.")


def view_dividend_history(
    portfolio_name: str,
    user_forename: str,
    portfolio_currency: str | None,
    sorted_histories: list[EstimatedSecurityDividendHistory],
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> None:
    while True:
        print_portfolio_screen(
            portfolio_name,
            user_forename,
            portfolio_currency,
            sorted_histories,
            output_func,
        )
        selected_history = prompt_for_selection(sorted_histories, input_func, output_func)
        if selected_history is None:
            return

        print_security_details(selected_history, output_func)


def print_portfolio_screen(
    portfolio_name: str,
    user_forename: str,
    portfolio_currency: str | None,
    sorted_histories: list[EstimatedSecurityDividendHistory],
    output_func: Callable[[str], None],
) -> None:
    output_func("")
    output_func(f"Portfolio: {portfolio_name}")
    output_func(f"User: {user_forename}")
    output_func(f"Total value: {format_currency(calculate_total_value(sorted_histories), portfolio_currency)}")
    output_func("")
    output_func("Current portfolio")
    output_func("-" * 92)
    output_func(f"{'#':>2}  {'Name':<34} {'ISIN':<14} {'Code':<10} {'Value':>14} {'Portfolio %':>12}")
    output_func("-" * 92)

    for index, history in enumerate(sorted_histories, start=1):
        security = history.security
        value = security_value(security)
        output_func(
            f"{index:>2}  "
            f"{truncate(security.name, 34):<34} "
            f"{security.isin:<14} "
            f"{truncate(security_code(security), 10):<10} "
            f"{format_amount(value):>14} "
            f"{portfolio_percentage(value, sorted_histories):>11.2f}%"
        )

    output_func("-" * 92)
    output_func("")


def print_monthly_dividend_view(
    histories: list[EstimatedSecurityDividendHistory],
    reference_date: date | None = None,
    output_func: Callable[[str], None] = print,
) -> None:
    active_date = reference_date or date.today()
    output_func("")
    output_func("Monthly dividends")

    for month_date in surrounding_months(active_date):
        rows = monthly_dividend_rows(histories, month_date)
        month_caption = describe_month(month_date, active_date)
        output_func("")
        output_func(month_caption)
        output_func("-" * 107)
        output_func(
            f"{'Ex date':<12} {'Pay date':<12} {'Name':<26} {'Code':<10} {'Per share':>14} {'Total':>14} {'Est.':<6}"
        )
        output_func("-" * 107)
        if not rows:
            output_func("No dividend events found.")
            continue

        for row in rows:
            output_func(
                f"{row.ex_date:<12} "
                f"{row.pay_date:<12} "
                f"{truncate(row.security_name, 26):<26} "
                f"{truncate(row.security_code, 10):<10} "
                f"{format_currency(row.amount_per_share, row.currency):>14} "
                f"{format_currency(row.total_amount, row.currency):>14} "
                f"{'yes' if row.is_estimated else 'no':<6}"
            )

        output_func("-" * 107)
        output_func(
            f"{'':<12} "
            f"{'':<12} "
            f"{'Total':<26} "
            f"{'':<10} "
            f"{'':>14} "
            f"{format_currency(sum_total_amount(rows), month_currency(rows)):>14} "
            f"{'':<6}"
        )


def surrounding_months(reference_date: date) -> list[date]:
    return [
        shift_month(reference_date, -1),
        reference_date.replace(day=1),
        shift_month(reference_date, 1),
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


def monthly_dividend_rows(
    histories: list[EstimatedSecurityDividendHistory],
    month_date: date,
) -> list[MonthlyDividendRow]:
    rows: list[MonthlyDividendRow] = []

    for history in histories:
        seen_keys: set[tuple[str, float | None]] = set()
        for event in history.dividends:
            if event.pay_date is None or not is_same_month(event.pay_date, month_date):
                continue

            row = MonthlyDividendRow(
                security_name=history.security.name,
                security_code=security_code(history.security),
                ex_date=event.ex_date or "-",
                pay_date=event.pay_date,
                amount_per_share=event.amount,
                total_amount=event_total_amount(event.amount, history.security.quantity),
                currency=event.currency or history.security.currency,
                is_estimated=event.forecast,
            )
            rows.append(row)
            seen_keys.add((event.pay_date, event.amount))

        estimated_row = estimated_monthly_dividend_row(history, month_date)
        if estimated_row is not None and (estimated_row.pay_date, estimated_row.amount_per_share) not in seen_keys:
            rows.append(estimated_row)

    return sorted(rows, key=lambda row: (row.pay_date, row.security_name))


def estimated_monthly_dividend_row(
    history: EstimatedSecurityDividendHistory,
    month_date: date,
) -> MonthlyDividendRow | None:
    estimate = history.estimate
    if estimate.next_payment_date is None or not is_same_month(estimate.next_payment_date, month_date):
        return None

    return MonthlyDividendRow(
        security_name=history.security.name,
        security_code=security_code(history.security),
        ex_date=estimate.next_ex_date or "-",
        pay_date=estimate.next_payment_date,
        amount_per_share=estimate.next_payment_amount,
        total_amount=estimate_total_amount(history),
        currency=history.security.currency,
        is_estimated=True,
    )


def is_same_month(iso_date: str, month_date: date) -> bool:
    parsed = date.fromisoformat(iso_date)
    return parsed.year == month_date.year and parsed.month == month_date.month


def sort_histories_by_value(
    histories: list[EstimatedSecurityDividendHistory],
) -> list[EstimatedSecurityDividendHistory]:
    return sorted(histories, key=lambda history: security_value(history.security), reverse=True)


def calculate_total_value(histories: list[EstimatedSecurityDividendHistory]) -> float:
    return sum(security_value(history.security) for history in histories)


def security_value(security: object) -> float:
    value = getattr(security, "value", None)
    if value is not None:
        return float(value)

    quantity = getattr(security, "quantity", 0.0) or 0.0
    price = getattr(security, "price", None)
    if price is not None:
        return float(quantity) * float(price)

    return 0.0


def security_code(security: object) -> str:
    symbol = getattr(security, "symbol", None)
    wkn = getattr(security, "wkn", None)
    return symbol or wkn or "-"


def portfolio_percentage(
    security_position_value: float,
    histories: list[EstimatedSecurityDividendHistory],
) -> float:
    total_value = calculate_total_value(histories)
    if total_value == 0:
        return 0.0
    return (security_position_value / total_value) * 100


def prompt_for_selection(
    histories: list[EstimatedSecurityDividendHistory],
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> EstimatedSecurityDividendHistory | None:
    if not histories:
        return None

    while True:
        raw_value = input_func("Choose a security number for dividend details (or 'q' to return): ").strip()
        if raw_value.lower() in {"q", "quit", "exit"}:
            return None

        if raw_value.isdigit():
            selected_index = int(raw_value)
            if 1 <= selected_index <= len(histories):
                return histories[selected_index - 1]

        output_func(f"Please enter a number between 1 and {len(histories)}, or 'q' to return.")


def print_security_details(
    history: EstimatedSecurityDividendHistory,
    output_func: Callable[[str], None] = print,
) -> None:
    security = history.security
    estimate = history.estimate
    estimated_total_amount = estimate_total_amount(history)
    output_func("")
    output_func(f"Security: {security.name}")
    output_func(f"ISIN: {security.isin}")
    output_func(f"Code: {security_code(security)}")
    output_func("")
    output_func("Next dividend estimate")
    output_func(f"Ex date: {estimate.next_ex_date or 'n/a'}")
    output_func(f"Date: {estimate.next_payment_date or 'n/a'}")
    output_func(f"Amount: {format_currency(estimate.next_payment_amount, security.currency, decimals=4)}")
    output_func(f"Estimated total amount: {format_currency(estimated_total_amount, security.currency)}")
    output_func(f"Confidence: {estimate.confidence}")
    output_func(f"Basis: {estimate.basis}")
    output_func("")
    output_func("Upcoming 12-month forecast")
    output_func("-" * 82)
    output_func(f"{'Ex date':<12} {'Pay date':<12} {'Per share':>14} {'Total':>14} {'Currency':<10}")
    output_func("-" * 82)

    if not estimate.forecast_events:
        output_func("No forecast events available.")
    else:
        for event in estimate.forecast_events:
            output_func(
                f"{(event.ex_date or '-'): <12} "
                f"{(event.pay_date or '-'): <12} "
                f"{format_amount(event.amount, decimals=4):>14} "
                f"{format_amount(event_total_amount(event.amount, security.quantity)):>14} "
                f"{(event.currency or '-'): <10}"
            )

    output_func("")
    output_func("Historical dividend events from the last 2 years")
    output_func("-" * 68)
    output_func(f"{'Pay date':<12} {'Ex date':<12} {'Amount':>14} {'Currency':<10}")
    output_func("-" * 68)

    recent_events = latest_historical_dividends(history)
    if not recent_events:
        output_func("No historical dividend events found.")
        return

    for event in recent_events:
        output_func(
            f"{(event.pay_date or '-'): <12} "
            f"{(event.ex_date or '-'): <12} "
            f"{format_amount(event.amount, decimals=4):>14} "
            f"{(event.currency or '-'): <10}"
        )


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
        if (event_date(event) is not None and event_date(event) >= cutoff_date)
    ]


def dividend_sort_key(event: DividendEvent) -> str:
    return event.pay_date or event.ex_date or ""


def event_date(event: DividendEvent) -> date | None:
    raw_date = event.pay_date or event.ex_date
    if raw_date is None:
        return None
    return date.fromisoformat(raw_date)


def estimate_total_amount(history: EstimatedSecurityDividendHistory) -> float | None:
    if history.estimate.next_payment_amount is None:
        return None
    return history.estimate.next_payment_amount * history.security.quantity


def event_total_amount(amount: float | None, quantity: float) -> float | None:
    if amount is None:
        return None
    return amount * quantity


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


def wait_for_enter(
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> None:
    output_func("")
    input_func("Press Enter to return to the menu...")


def format_currency(amount: float | None, currency: str | None, decimals: int = 2) -> str:
    if amount is None:
        return "n/a"
    if currency:
        return f"{amount:,.{decimals}f} {currency}"
    return format_amount(amount, decimals=decimals)


def format_amount(amount: float | None, decimals: int = 2) -> str:
    if amount is None:
        return "n/a"
    return f"{amount:,.{decimals}f}"


def truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return f"{value[: width - 3]}..."
