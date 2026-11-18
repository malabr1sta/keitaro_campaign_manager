from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.campaign_service import CampaignService
from app.config import Settings
from app.db import make_sessions
from app.errors import AppError
from app.keitaro_client import KeitaroClient
from app.routes import router


def create_app(settings=None, client=None):
    settings = settings or Settings()
    sessions = make_sessions(settings.database_url)
    client = client or KeitaroClient(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.close()
        sessions.kw["bind"].dispose()

    app = FastAPI(title="Keitaro Campaign Manager", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = CampaignService(client, sessions, settings)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.exception_handler(AppError)
    async def app_error(request, error):
        return JSONResponse(error.payload, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        fields = {
            str(e["loc"][-1]): "Некорректное или отсутствующее значение" for e in error.errors()
        }
        return JSONResponse(
            {
                "code": "validation",
                "message": "Проверьте заполнение полей.",
                "field_errors": fields,
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return JSONResponse(
            {"code": "internal_error", "message": "Внутренняя ошибка приложения."}, status_code=500
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Browsers may only issue writes from the app's origin. No CORS is enabled.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"code": "origin", "message": "Недопустимый источник запроса."}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    async def health():
        with sessions() as session:
            session.execute(text("SELECT id FROM creation_operations LIMIT 1"))
        return {"status": "ok"}

    return app


app = create_app()
