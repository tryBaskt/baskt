# backend/main.py

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Allow local-package imports (core.*, services.*, etc.) in both modes:
# - running from backend/ (e.g. `uvicorn main:app`)
# - importing as backend.main from repo root
# _BACKEND_DIR = Path(__file__).resolve().parent
# if str(_BACKEND_DIR) not in sys.path:
#     sys.path.insert(0, str(_BACKEND_DIR))

from core.config import get_settings
from core.logging_config import configure_cloudwatch_logging
from routes.backtest_route import router as backtest_router
from routes.model_portfolio_route import router as model_portfolio_router
from routes.account_lifecycle_route import router as account_lifecycle_router
from routes.investment_analytics_route import router as investment_analytics_router
from routes.trade_execution_route import router as trade_execution_router
from routes.model_portfolios_stocks_search_route import router as model_portfolios_stocks_search_router
from routes.stock_analytics_route import router as stock_analytics_router
from routes.baskt_account_route import router as baskt_account_router


error_logger = logging.getLogger("uvicorn.error")


def _exception_traceback(error: BaseException) -> str:
    """Format an exception and its complete cause/context chain."""
    return "".join(
        traceback.format_exception(
            type(error),
            error,
            error.__traceback__,
            chain=True,
        )
    )


def _log_request_exception(
    request: Request,
    error: BaseException,
    *,
    status_code: int,
) -> None:
    """Log request context followed by the complete exception traceback."""
    error_logger.error(
        "Request failed: %s %s -> %s\n%s",
        request.method,
        request.url.path,
        status_code,
        _exception_traceback(error),
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_cloudwatch_logging(settings)

    app = FastAPI(title=settings.app_name)

    @app.exception_handler(HTTPException)
    async def log_http_exception(
        request: Request,
        error: HTTPException,
    ):
        _log_request_exception(
            request,
            error,
            status_code=error.status_code,
        )
        return await http_exception_handler(request, error)

    @app.exception_handler(RequestValidationError)
    async def log_request_validation_exception(
        request: Request,
        error: RequestValidationError,
    ):
        _log_request_exception(
            request,
            error,
            status_code=422,
        )
        return await request_validation_exception_handler(request, error)

    @app.exception_handler(Exception)
    async def log_unhandled_exception(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        _log_request_exception(request, error, status_code=500)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # CORS
    # If cors_origins == ["*"], allow everything (dev).
    # Otherwise explicitly list allowed origins.
    allow_origins = settings.cors_origins_list

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(backtest_router)
    app.include_router(model_portfolio_router)
    app.include_router(account_lifecycle_router)
    app.include_router(investment_analytics_router)
    app.include_router(trade_execution_router)
    app.include_router(model_portfolios_stocks_search_router)
    app.include_router(stock_analytics_router)
    app.include_router(baskt_account_router)

    # Health check
    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
    

app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
