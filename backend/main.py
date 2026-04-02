from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .routers import settings, exes, chat, upload, create

app = FastAPI(title="忘不掉的她 Web", version="1.0.0")

app.include_router(settings.router)
app.include_router(exes.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(create.router)

STATIC_DIR = Path(__file__).parent / "static"

# Serve React build from /static, fallback index.html for SPA routing
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/")
    def serve_index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Don't intercept API routes
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        return FileResponse(str(STATIC_DIR / "index.html"))
