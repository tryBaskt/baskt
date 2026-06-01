# backend/main.py

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Allow local-package imports (core.*, services.*, etc.) in both modes:
# - running from backend/ (e.g. `uvicorn main:app`)
# - importing as backend.main from repo root
# _BACKEND_DIR = Path(__file__).resolve().parent
# if str(_BACKEND_DIR) not in sys.path:
#     sys.path.insert(0, str(_BACKEND_DIR))

from core.config import get_settings
from routes.backtest_route import router as backtest_router
from backend.routes.alpaca_broker_route import router as alpaca_router
from routes.model_portfolio_route import router as model_portfolio_router
from routes.account_lifecycle_route import router as account_lifecycle_router


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title=settings.app_name)

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
    app.include_router(alpaca_router)
    app.include_router(backtest_router)
    app.include_router(model_portfolio_router)
    app.include_router(account_lifecycle_router)

    # Health check
    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
    

app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)