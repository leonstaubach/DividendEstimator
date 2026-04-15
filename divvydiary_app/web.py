from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .bootstrap import AppRuntime, build_runtime
from .config import AppConfig
from .logging_config import configure_logging, get_logger
from .models import ResolvedPortfolio
from .presentation import (
    ForecastExplanationView,
    SecurityDetailView,
    build_backtest_explanation_view,
    build_dashboard_view,
    build_forecast_explanation_view,
    build_monthly_timeline_view,
    build_security_detail_view,
    calculate_total_value,
    format_amount,
    format_currency,
    format_display_date,
    format_quantity,
)

logger = get_logger("web")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals["format_amount"] = format_amount
templates.env.globals["format_currency"] = format_currency
templates.env.globals["format_display_date"] = format_display_date
templates.env.globals["format_quantity"] = format_quantity

_MISSING_API_KEY_MESSAGE = "Please set DIVVYDIARY_API_KEY in the .env file before starting the web app."
_MODAL_API_KEY_ERROR = f'<p class="modal-error">{_MISSING_API_KEY_MESSAGE}</p>'


@lru_cache(maxsize=1)
def get_runtime() -> AppRuntime:
    config = AppConfig.from_env()
    configure_logging(config.log_level)
    return build_runtime(config)


@dataclass(frozen=True)
class PageGuard:
    """Per-page metadata used by the common guard + context helpers."""

    template_name: str
    active_page: str
    extra_defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastPageContext:
    resolved_portfolio: ResolvedPortfolio
    security_view: SecurityDetailView
    explanation_view: ForecastExplanationView


def _page_context(guard: PageGuard, **overrides: Any) -> dict[str, Any]:
    """Standard template context for page routes: common keys + page-specific defaults."""
    ctx: dict[str, Any] = {
        "active_page": guard.active_page,
        "selected_security": None,
        "is_loading": False,
        "error_message": None,
    }
    ctx.update(guard.extra_defaults)
    ctx.update(overrides)
    return ctx


def _guard_page(request: Request, active_runtime: AppRuntime, guard: PageGuard):
    """Return a TemplateResponse for missing api_key / loading states, else None."""
    if not active_runtime.config.api_key:
        return templates.TemplateResponse(
            request,
            guard.template_name,
            _page_context(guard, error_message=_MISSING_API_KEY_MESSAGE),
            status_code=500,
        )
    if not active_runtime.service.is_data_cached():
        return templates.TemplateResponse(
            request,
            guard.template_name,
            _page_context(guard, is_loading=True),
        )
    return None


def _guard_modal(active_runtime: AppRuntime) -> HTMLResponse | None:
    if not active_runtime.config.api_key:
        return HTMLResponse(_MODAL_API_KEY_ERROR, status_code=500)
    return None


def create_app(runtime: AppRuntime | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime or get_runtime()
        logger.info("Application started")
        yield
        logger.debug("Application shutting down")

    app = FastAPI(title="Leon's Dividend Estimator", version="1.0.0", lifespan=lifespan)

    def active() -> AppRuntime:
        return runtime or get_runtime()

    def load_forecast_context(active_runtime: AppRuntime, isin: str, forecast_index: int) -> ForecastPageContext:
        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        selected_history = next((h for h in estimated_histories if h.security.isin == isin), None)
        if selected_history is None:
            raise HTTPException(status_code=404, detail="Security not found")

        if forecast_index < 1 or forecast_index > len(selected_history.estimate.forecast_events):
            raise HTTPException(status_code=404, detail="Forecast event not found")

        explanation = active_runtime.service.explain_forecast(
            history=selected_history,
            steps_ahead=forecast_index,
        )
        if explanation is None:
            raise HTTPException(status_code=404, detail="Forecast explanation unavailable")

        security_view = build_security_detail_view(
            selected_history,
            total_portfolio_value=calculate_total_value(estimated_histories),
            explanation=active_runtime.service.explain_forecast(selected_history, steps_ahead=1),
        )
        return ForecastPageContext(
            resolved_portfolio=resolved_portfolio,
            security_view=security_view,
            explanation_view=build_forecast_explanation_view(selected_history, explanation),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        active_runtime = active()
        guard = PageGuard("dashboard.html", "dashboard", {"dashboard": None})
        if (response := _guard_page(request, active_runtime, guard)) is not None:
            return response

        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        dashboard_view = build_dashboard_view(resolved_portfolio, estimated_histories)
        return templates.TemplateResponse(
            request,
            guard.template_name,
            _page_context(guard, dashboard=dashboard_view),
        )

    @app.get("/monthly", response_class=HTMLResponse)
    async def monthly_view(request: Request):
        active_runtime = active()
        guard = PageGuard("monthly.html", "monthly", {"monthly_view": None})
        if (response := _guard_page(request, active_runtime, guard)) is not None:
            return response

        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        timeline = build_monthly_timeline_view(
            resolved_portfolio,
            estimated_histories,
            backtest_fn=active_runtime.service.backtest_dividend,
        )
        return templates.TemplateResponse(
            request,
            guard.template_name,
            _page_context(guard, monthly_view=timeline),
        )

    @app.get("/security/{isin}", response_class=HTMLResponse)
    async def security_detail(request: Request, isin: str):
        active_runtime = active()
        guard = PageGuard("security_detail.html", "security", {"security": None})
        if (response := _guard_page(request, active_runtime, guard)) is not None:
            return response

        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        selected_history = next((h for h in estimated_histories if h.security.isin == isin), None)
        if selected_history is None:
            raise HTTPException(status_code=404, detail="Security not found")

        security_view = build_security_detail_view(
            selected_history,
            total_portfolio_value=calculate_total_value(estimated_histories),
            explanation=active_runtime.service.explain_forecast(selected_history, steps_ahead=1),
        )
        return templates.TemplateResponse(
            request,
            guard.template_name,
            _page_context(
                guard,
                selected_security=security_view,
                security=security_view,
                portfolio_name=resolved_portfolio.portfolio.name,
            ),
        )

    @app.get("/security/{isin}/forecast/{forecast_index}", response_class=HTMLResponse)
    async def forecast_explanation(request: Request, isin: str, forecast_index: int):
        active_runtime = active()
        guard = PageGuard(
            "forecast_explanation.html",
            "security",
            {"security": None, "explanation": None},
        )
        if (response := _guard_page(request, active_runtime, guard)) is not None:
            return response

        context = load_forecast_context(active_runtime, isin, forecast_index)
        return templates.TemplateResponse(
            request,
            guard.template_name,
            _page_context(
                guard,
                selected_security=context.security_view,
                security=context.security_view,
                explanation=context.explanation_view,
                portfolio_name=context.resolved_portfolio.portfolio.name,
            ),
        )

    @app.get("/security/{isin}/forecast/{forecast_index}/modal", response_class=HTMLResponse)
    async def forecast_explanation_modal(request: Request, isin: str, forecast_index: int):
        active_runtime = active()
        if (response := _guard_modal(active_runtime)) is not None:
            return response

        context = load_forecast_context(active_runtime, isin, forecast_index)
        return templates.TemplateResponse(
            request,
            "forecast_explanation_modal.html",
            {"explanation": context.explanation_view},
        )

    @app.get("/security/{isin}/backtest/{event_id}/modal", response_class=HTMLResponse)
    async def backtest_explanation_modal(request: Request, isin: str, event_id: int):
        active_runtime = active()
        if (response := _guard_modal(active_runtime)) is not None:
            return response

        _, estimated_histories = active_runtime.service.load_portfolio_data()
        history = next((h for h in estimated_histories if h.security.isin == isin), None)
        if history is None:
            raise HTTPException(status_code=404, detail="Security not found")

        result = active_runtime.service.backtest_explanation(history, event_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest explanation unavailable")

        actual_event, forecast_explanation = result
        backtest_view = build_backtest_explanation_view(history, actual_event, forecast_explanation)
        return templates.TemplateResponse(
            request,
            "backtest_explanation_modal.html",
            {"backtest": backtest_view},
        )

    @app.post("/actions/refresh-cache")
    async def refresh_cache() -> RedirectResponse:
        logger.info("Clearing cached portfolio data from web action.")
        active().service.clear_cache()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/fetch-data")
    async def fetch_data() -> JSONResponse:
        logger.info("Background fetch triggered from loading state.")
        active().service.load_portfolio_data()
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
