"""Spike AI - FastAPI application entry point."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import agent, auth, bridge, chat, conversations, meta, projects, voice
from app.config import STATIC_DIR, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast if critical static assets are missing — prevents silent 404 in production
    for rel in ("css/style.css", "js/app.js", "index.html", "logo.svg"):
        p = STATIC_DIR / rel
        if not p.exists():
            import logging
            logging.getLogger("uvicorn.error").error(f"Missing static asset: {p} — build will fail")
            raise RuntimeError(f"Missing required static asset: {rel} (expected at {p})")
        if p.stat().st_size == 0:
            import logging
            logging.getLogger("uvicorn.error").warning(f"Static asset empty: {p}")
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
)

# CORS - environment based origins (no wildcard for production security)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(meta.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(agent.router)
app.include_router(projects.router)
app.include_router(bridge.router)


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Serve static files last so API routes take precedence
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
