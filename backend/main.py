"""
NextRole FastAPI application entry point (FR-011).

Run locally with:
    uvicorn backend.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.db.database import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="NextRole API",
    description="Local multi-agent resume tailoring and interview prep pipeline.",
    version="0.1.0",
    lifespan=lifespan,
)

# React frontend runs as a separate local dev server (scope.md Assumptions).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
