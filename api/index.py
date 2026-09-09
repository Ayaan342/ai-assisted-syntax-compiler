"""Vercel entrypoint mounting the existing compiler API under /api."""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.main import app as compiler_app


app = FastAPI()
app.mount("/api", compiler_app)
