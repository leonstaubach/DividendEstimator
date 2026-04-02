from __future__ import annotations

from datetime import date
from typing import Callable

from .logging_config import get_logger
from .models import EstimatedSecurityDividendHistory, ResolvedPortfolio
from .presentation import (
    DashboardView,
    MonthlyDividendRow,
    build_dashboard_view,
    estimate_total_amount,
    format_amount,
    format_currency,
    latest_historical_dividends,
    monthly_dividend_rows,
    security_code,
    sort_histories_by_value,
    surrounding_months,
    describe_month,
    event_total_amount,
    truncate,
)
from .service import PortfolioService

logger = get_logger("cli")


def run_cli(
    service: PortfolioService,
    input_func: Callable[[str], str] = input,
) -> int:
    resolved_portfolio, sorted_histories = load_portfolio_data(service)

    while True:
        view = build_dashboard_view(resolved_portfolio, sorted_histories)
        print_main_menu(view)
        selected_option = prompt_main_menu(input_func)
        if selected_option is None:
            logger.info("Goodbye.")
            return 0

        if selected_option == "1":
            print_monthly_dividend_view(sorted_histories)
            wait_for_enter(input_func)
            continue

        if selected_option == "r":
            logger.info("Clearing cached portfolio data...")
            service.clear_cache()
            resolved_portfolio, sorted_histories = load_portfolio_data(service)
            continue

        view_dividend_history(view, sorted_histories, input_func)


def load_portfolio_data(
    service: PortfolioService,
) -> tuple[ResolvedPortfolio, list[EstimatedSecurityDividendHistory]]:
    logger.info("Loading portfolio...")
    resolved_portfolio = service.get_resolved_portfolio()
    logger.info("Loaded portfolio '%s'.", resolved_portfolio.portfolio.name)
    logger.info("Loading dividend histories and calculating estimates...")
    estimated_histories = service.build_estimated_security_dividend_histories(resolved_portfolio)
    logger.info("Loaded dividend histories for %s securities.", len(estimated_histories))
    return resolved_portfolio, sort_histories_by_value(estimated_histories)


def print_main_menu(view: DashboardView) -> None:
    logger.info("")
    logger.info("Portfolio: %s", view.portfolio_name)
    logger.info("Total value: %s", format_currency(view.total_value, view.portfolio_currency))
    logger.info("")
    logger.info("Menu")
    logger.info("1. View monthly dividends")
    logger.info("2. View dividend history")
    logger.info("r. Refresh data")
    logger.info("q. Quit")
    logger.info("")


def prompt_main_menu(input_func: Callable[[str], str]) -> str | None:
    while True:
        raw_value = input_func("Choose an option: ").strip().lower()
        if raw_value in {"q", "quit", "exit"}:
            return None
        if raw_value in {"1", "2", "r"}:
            return raw_value
        logger.info("Please enter 1, 2, r, or q.")


def view_dividend_history(
    view: DashboardView,
    sorted_histories: list[EstimatedSecurityDividendHistory],
    input_func: Callable[[str], str],
) -> None:
    while True:
        print_portfolio_screen(view)
        selected_history = prompt_for_selection(sorted_histories, input_func)
        if selected_history is None:
            return

        print_security_details(selected_history)


def print_portfolio_screen(view: DashboardView) -> None:
    logger.info("")
    logger.info("Portfolio: %s", view.portfolio_name)
    logger.info("User: %s", view.user_forename)
    logger.info("Total value: %s", format_currency(view.total_value, view.portfolio_currency))
    logger.info("")
    logger.info("Current portfolio")
    logger.info("%s", "-" * 92)
    logger.info("%s", f"{'#':>2}  {'Name':<34} {'ISIN':<14} {'Code':<10} {'Value':>14} {'Portfolio %':>12}")
    logger.info("%s", "-" * 92)

    for row in view.holdings:
        logger.info(
            "%s",
            f"{row.index:>2}  "
            f"{truncate(row.name, 34):<34} "
            f"{row.isin:<14} "
            f"{truncate(row.code, 10):<10} "
            f"{format_amount(row.value):>14} "
            f"{row.portfolio_percentage:>11.2f}%",
        )

    logger.info("%s", "-" * 92)
    logger.info("")


def print_monthly_dividend_view(
    histories: list[EstimatedSecurityDividendHistory],
) -> None:
    active_date = date.today()
    logger.info("")
    logger.info("Monthly dividends")

    for month_date in surrounding_months(active_date):
        rows = monthly_dividend_rows(histories, month_date)
        logger.info("")
        logger.info("%s", describe_month(month_date, active_date))
        logger.info("%s", "-" * 107)
        logger.info(
            "%s",
            f"{'Ex date':<12} {'Pay date':<12} {'Name':<26} {'Code':<10} {'Per share':>14} {'Total':>14} {'Est.':<6}",
        )
        logger.info("%s", "-" * 107)
        if not rows:
            logger.info("No dividend events found.")
            continue

        for row in rows:
            print_monthly_row(row)

        logger.info("%s", "-" * 107)
        total_amount = sum_total_amount(rows)
        logger.info(
            "%s",
            f"{'':<12} "
            f"{'':<12} "
            f"{'Total':<26} "
            f"{'':<10} "
            f"{'':>14} "
            f"{format_currency(total_amount, month_currency(rows)):>14} "
            f"{'':<6}",
        )


def print_monthly_row(row: MonthlyDividendRow) -> None:
    logger.info(
        "%s",
        f"{row.ex_date:<12} "
        f"{row.pay_date:<12} "
        f"{truncate(row.security_name, 26):<26} "
        f"{truncate(row.security_code, 10):<10} "
        f"{format_currency(row.amount_per_share, row.currency):>14} "
        f"{format_currency(row.total_amount, row.currency):>14} "
        f"{'yes' if row.is_estimated else 'no':<6}",
    )


def prompt_for_selection(
    histories: list[EstimatedSecurityDividendHistory],
    input_func: Callable[[str], str],
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

        logger.info("Please enter a number between 1 and %s, or 'q' to return.", len(histories))


def print_security_details(history: EstimatedSecurityDividendHistory) -> None:
    security = history.security
    estimate = history.estimate
    estimated_total_amount = estimate_total_amount(history)
    logger.info("")
    logger.info("Security: %s", security.name)
    logger.info("ISIN: %s", security.isin)
    logger.info("Code: %s", security_code(security))
    logger.info("")
    logger.info("Next dividend estimate")
    logger.info("Ex date: %s", estimate.next_ex_date or "n/a")
    logger.info("Date: %s", estimate.next_payment_date or "n/a")
    logger.info("Amount: %s", format_currency(estimate.next_payment_amount, security.currency, decimals=4))
    logger.info("Estimated total amount: %s", format_currency(estimated_total_amount, security.currency))
    logger.info("Confidence: %s", estimate.confidence)
    logger.info("Basis: %s", estimate.basis)
    logger.info("")
    logger.info("Upcoming 12-month forecast")
    logger.info("%s", "-" * 82)
    logger.info("%s", f"{'Ex date':<12} {'Pay date':<12} {'Per share':>14} {'Total':>14} {'Currency':<10}")
    logger.info("%s", "-" * 82)

    if not estimate.forecast_events:
        logger.info("No forecast events available.")
    else:
        for event in estimate.forecast_events:
            logger.info(
                "%s",
                f"{(event.ex_date or '-'): <12} "
                f"{(event.pay_date or '-'): <12} "
                f"{format_amount(event.amount, decimals=4):>14} "
                f"{format_amount(event_total_amount(event.amount, security.quantity)):>14} "
                f"{(event.currency or '-'): <10}",
            )

    logger.info("")
    logger.info("Historical dividend events from the last 2 years")
    logger.info("%s", "-" * 68)
    logger.info("%s", f"{'Pay date':<12} {'Ex date':<12} {'Amount':>14} {'Currency':<10}")
    logger.info("%s", "-" * 68)

    recent_events = latest_historical_dividends(history)
    if not recent_events:
        logger.info("No historical dividend events found.")
        return

    for event in recent_events:
        logger.info(
            "%s",
            f"{(event.pay_date or '-'): <12} "
            f"{(event.ex_date or '-'): <12} "
            f"{format_amount(event.amount, decimals=4):>14} "
            f"{(event.currency or '-'): <10}",
        )


def sum_total_amount(rows: list[MonthlyDividendRow]) -> float | None:
    return sum(row.total_amount for row in rows if row.total_amount is not None) if any(
        row.total_amount is not None for row in rows
    ) else None


def month_currency(rows: list[MonthlyDividendRow]) -> str | None:
    for row in rows:
        if row.currency:
            return row.currency
    return None


def wait_for_enter(input_func: Callable[[str], str]) -> None:
    logger.info("")
    input_func("Press Enter to return to the menu...")
