from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .bootstrap import AppRuntime, build_runtime
from .config import AppConfig
from .logging_config import configure_logging, get_logger
from .presentation import (
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


@lru_cache(maxsize=1)
def get_runtime() -> AppRuntime:
    config = AppConfig.from_env()
    configure_logging(config.log_level)
    return build_runtime(config)


def create_app(runtime: AppRuntime | None = None) -> FastAPI:
    app = FastAPI(title="Dividend Viewer", version="1.0.0")

    def load_forecast_explanation_context(active_runtime: AppRuntime, isin: str, forecast_index: int):
        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        selected_history = next((history for history in estimated_histories if history.security.isin == isin), None)
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
        explanation_view = build_forecast_explanation_view(selected_history, explanation)
        return resolved_portfolio, security_view, explanation_view

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        active_runtime = runtime or get_runtime()
        if not active_runtime.config.api_key:
            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {
                    "request": request,
                    "active_page": "dashboard",
                    "selected_security": None,
                    "error_message": "Please set DIVVYDIARY_API_KEY in the .env file before starting the web app.",
                    "dashboard": None,
                    "is_loading": False,
                },
                status_code=500,
            )

        if not active_runtime.service.is_data_cached():
            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {
                    "request": request,
                    "active_page": "dashboard",
                    "selected_security": None,
                    "dashboard": None,
                    "is_loading": True,
                    "error_message": None,
                },
            )

        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        dashboard_view = build_dashboard_view(resolved_portfolio, estimated_histories)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "active_page": "dashboard",
                "selected_security": None,
                "dashboard": dashboard_view,
                "is_loading": False,
                "error_message": None,
            },
        )

    @app.get("/monthly", response_class=HTMLResponse)
    async def monthly_view(request: Request):
        active_runtime = runtime or get_runtime()
        if not active_runtime.config.api_key:
            return templates.TemplateResponse(
                request,
                "monthly.html",
                {
                    "request": request,
                    "active_page": "monthly",
                    "selected_security": None,
                    "error_message": "Please set DIVVYDIARY_API_KEY in the .env file before starting the web app.",
                    "monthly_view": None,
                    "is_loading": False,
                },
                status_code=500,
            )

        if not active_runtime.service.is_data_cached():
            return templates.TemplateResponse(
                request,
                "monthly.html",
                {
                    "request": request,
                    "active_page": "monthly",
                    "selected_security": None,
                    "monthly_view": None,
                    "is_loading": True,
                    "error_message": None,
                },
            )

        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        monthly_timeline = build_monthly_timeline_view(resolved_portfolio, estimated_histories)
        return templates.TemplateResponse(
            request,
            "monthly.html",
            {
                "request": request,
                "active_page": "monthly",
                "selected_security": None,
                "monthly_view": monthly_timeline,
                "is_loading": False,
                "error_message": None,
            },
        )

    @app.get("/security/{isin}", response_class=HTMLResponse)
    async def security_detail(request: Request, isin: str):
        active_runtime = runtime or get_runtime()
        if not active_runtime.config.api_key:
            return templates.TemplateResponse(
                request,
                "security_detail.html",
                {
                    "request": request,
                    "active_page": "security",
                    "selected_security": None,
                    "error_message": "Please set DIVVYDIARY_API_KEY in the .env file before starting the web app.",
                    "security": None,
                    "is_loading": False,
                },
                status_code=500,
            )

        if not active_runtime.service.is_data_cached():
            return templates.TemplateResponse(
                request,
                "security_detail.html",
                {
                    "request": request,
                    "active_page": "security",
                    "selected_security": None,
                    "security": None,
                    "is_loading": True,
                    "error_message": None,
                },
            )

        resolved_portfolio, estimated_histories = active_runtime.service.load_portfolio_data()
        selected_history = next((history for history in estimated_histories if history.security.isin == isin), None)
        if selected_history is None:
            raise HTTPException(status_code=404, detail="Security not found")
        security_view = build_security_detail_view(
            selected_history,
            total_portfolio_value=calculate_total_value(estimated_histories),
            explanation=active_runtime.service.explain_forecast(selected_history, steps_ahead=1),
        )
        return templates.TemplateResponse(
            request,
            "security_detail.html",
            {
                "request": request,
                "active_page": "security",
                "selected_security": security_view,
                "security": security_view,
                "portfolio_name": resolved_portfolio.portfolio.name,
                "is_loading": False,
                "error_message": None,
            },
        )

    @app.get("/security/{isin}/forecast/{forecast_index}", response_class=HTMLResponse)
    async def forecast_explanation(request: Request, isin: str, forecast_index: int):
        active_runtime = runtime or get_runtime()
        if not active_runtime.config.api_key:
            return templates.TemplateResponse(
                request,
                "forecast_explanation.html",
                {
                    "request": request,
                    "active_page": "security",
                    "selected_security": None,
                    "security": None,
                    "explanation": None,
                    "is_loading": False,
                    "error_message": "Please set DIVVYDIARY_API_KEY in the .env file before starting the web app.",
                },
                status_code=500,
            )

        if not active_runtime.service.is_data_cached():
            return templates.TemplateResponse(
                request,
                "forecast_explanation.html",
                {
                    "request": request,
                    "active_page": "security",
                    "selected_security": None,
                    "security": None,
                    "explanation": None,
                    "is_loading": True,
                    "error_message": None,
                },
            )

        resolved_portfolio, security_view, explanation_view = load_forecast_explanation_context(
            active_runtime,
            isin,
            forecast_index,
        )
        return templates.TemplateResponse(
            request,
            "forecast_explanation.html",
            {
                "request": request,
                "active_page": "security",
                "selected_security": security_view,
                "security": security_view,
                "explanation": explanation_view,
                "portfolio_name": resolved_portfolio.portfolio.name,
                "is_loading": False,
                "error_message": None,
            },
        )

    @app.get("/security/{isin}/forecast/{forecast_index}/modal", response_class=HTMLResponse)
    async def forecast_explanation_modal(request: Request, isin: str, forecast_index: int):
        active_runtime = runtime or get_runtime()
        if not active_runtime.config.api_key:
            return HTMLResponse(
                '<p class="modal-error">Please set DIVVYDIARY_API_KEY in the .env file before starting the web app.</p>',
                status_code=500,
            )

        _, _, explanation_view = load_forecast_explanation_context(
            active_runtime,
            isin,
            forecast_index,
        )
        return templates.TemplateResponse(
            request,
            "forecast_explanation_modal.html",
            {
                "request": request,
                "explanation": explanation_view,
            },
        )

    @app.post("/actions/refresh-cache")
    async def refresh_cache() -> RedirectResponse:
        active_runtime = runtime or get_runtime()
        logger.info("Clearing cached portfolio data from web action.")
        active_runtime.service.clear_cache()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/fetch-data")
    async def fetch_data() -> JSONResponse:
        active_runtime = runtime or get_runtime()
        logger.info("Background fetch triggered from loading state.")
        active_runtime.service.load_portfolio_data()
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
