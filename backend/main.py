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
    # Warn if critical static assets are missing — don't crash, but log so 404 is visible
    for rel in ("css/style.css", "js/app.js", "index.html", "logo.svg"):
        p = STATIC_DIR / rel
        if not p.exists():
            import logging
            logging.getLogger("uvicorn.error").warning(f"Missing static asset: {p} — will serve fallback or 404")
        elif p.stat().st_size == 0:
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


# Explicit fallback for critical assets — ensures 200 even if mount misbehaves or cache is stale
@app.get("/static/css/style.css")
async def _serve_css():
    p = STATIC_DIR / "css" / "style.css"
    if p.exists():
        return FileResponse(str(p), media_type="text/css", headers={"Cache-Control": "public, max-age=3600"})
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "style.css not found"}, status_code=404)


@app.get("/static/js/app.js")
async def _serve_js():
    p = STATIC_DIR / "js" / "app.js"
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "app.js not found"}, status_code=404)


@app.get("/static/js/marked.min.js")
async def _serve_marked():
    p = STATIC_DIR / "js" / "marked.min.js"
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "marked.min.js not found"}, status_code=404)


# Serve static files last so API routes take precedence
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
