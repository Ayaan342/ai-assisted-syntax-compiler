"""FastAPI application factory and safe transport-level exception handling."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .dependencies import ModelUnavailableError, get_groq_fallback, get_predictor
from .routes.analysis import router as analysis_router
from .routes.correction import router as correction_router
from .schemas import HealthResponse


DEVELOPMENT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


app = FastAPI(
    title="AI-Assisted Mini-C Compiler API",
    version="1.0.0",
    description="Thin API adapter for compiler analysis and validated AI-assisted correction.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEVELOPMENT_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
app.include_router(analysis_router)
app.include_router(correction_router)


@app.exception_handler(ModelUnavailableError)
async def model_unavailable_handler(
    request: Request, exc: ModelUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected backend error occurred"},
    )


@app.get("/health", response_model=HealthResponse, tags=["system"], summary="Check readiness")
def health() -> HealthResponse:
    try:
        get_predictor()
        model_loaded = True
    except ModelUnavailableError:
        model_loaded = False
    return HealthResponse(
        status="ok",
        ml_model_loaded=model_loaded,
        groq_configured=get_groq_fallback().available,
    )


@app.get("/", tags=["system"], summary="Describe the API")
def root() -> dict[str, str]:
    return {
        "name": "AI-Assisted Mini-C Compiler API",
        "documentation": "/docs",
    }
