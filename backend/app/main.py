import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import admin, auth, lecturer, student
from app.api.deps import write_gate
from app.config import DEV_SECRET, settings
from app.db import Session, TooManyRetries, engine, retry_stats
from app.errors import AppError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if settings.jwt_secret == DEV_SECRET:
    logging.getLogger("app").warning("USOS_JWT_SECRET nie jest ustawiony - używany jest klucz deweloperski")

app = FastAPI(title="USOSv2 - system zapisów na zajęcia", version="0.1.0",
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
for r in (auth.router, student.router, lecturer.router, admin.router):
    app.include_router(r)


def error(status: int, code: str, message: str, details=(), headers=None) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "details": list(details)}, status, headers=headers)


@app.exception_handler(AppError)
async def app_error(_: Request, e: AppError):
    retry = getattr(e, "retry_after", None)
    return error(e.status, e.code, e.message, e.details,
                 headers={"Retry-After": str(max(1, round(retry)))} if retry else None)


@app.exception_handler(TooManyRetries)
async def too_many_retries(_: Request, e: TooManyRetries):
    return error(503, "BUSY", "Grupa jest teraz bardzo oblegana - spróbuj ponownie.", headers={"Retry-After": "1"})


@app.exception_handler(RequestValidationError)
async def validation(_: Request, e: RequestValidationError):
    details = [f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in e.errors()]
    return error(422, "VALIDATION", "Niepoprawne dane.", details)


@app.get("/api/health")
async def health():
    async with Session() as s:
        await s.execute(text("SELECT 1"))
    pool = engine.pool
    return {"status": "ok", "retries": retry_stats, "gate_rejected": write_gate.rejected,
            "pool": {"size": pool.size(), "checked_out": pool.checkedout()}}
