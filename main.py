from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from src.middleware import CorrelationIdMiddleware, LoggingMiddleware
from src.repositories.database import db
from src.routes import api as api_routes
from src.routes.system import router as system_router
from src.settings import get_settings
from src.utils.exceptions.exceptions import ApplicationError
from src.utils.logger import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init(settings.database_url)
    await db.create_tables()
    yield
    await db.close()


app = FastAPI(
    title="Hasamex Transcript Analysis API",
    description=(
        "Analyse European robotic surgery market expert-call transcripts: "
        "interview guide, exact quotes, themes, and cross-transcript Q&A."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)

app.include_router(system_router)
app.include_router(api_routes.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "status_code": 422,
            "error_code": "INVALID_INPUT",
            "message": "Validation error",
            "detail": exc.errors(),
        },
    )


@app.exception_handler(ApplicationError)
async def application_error_handler(request, exc: ApplicationError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "status_code": exc.status_code,
            "error_code": exc.error_code,
            "message": exc.message,
            "detail": None,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "status_code": 500,
            "error_code": "UNEXPECTED_ERROR",
            "message": "An unexpected error occurred",
            "detail": None,
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )