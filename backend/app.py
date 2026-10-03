"""Composition root. start.cmd still launches backend.app:app."""
from contextlib import asynccontextmanager
import os
import tempfile
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.config import ROOT, Settings
from backend.domain.models import StudyError
from backend.dp.database import initialize, SQLiteLibraryRepository
from backend.dp.files import LocalFileStore
from backend.dp.parsers import LocalDocumentParser
from backend.dp.demo import DemoAnswerProvider
from backend.service.library import LibraryService
from backend.api.routes import router
from backend.api.middleware import UploadBodyLimit

def create_app(data_dir=None, service=None, settings=None):
    settings = settings or Settings.load(data_dir)
    temp = settings.cache_dir / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP=str(temp), TMP=str(temp))
    tempfile.tempdir = str(temp)

    @asynccontextmanager
    async def lifespan(application):
        if service is None:
            database = initialize(settings.data_dir)
            application.state.library = LibraryService(
                SQLiteLibraryRepository(database), LocalFileStore(settings.data_dir, settings.cache_dir / "uploads"),
                LocalDocumentParser(), DemoAnswerProvider(), settings.upload_limit)
        else:
            application.state.library = service
        yield

    application = FastAPI(title="课程书桌 · 本地演示", lifespan=lifespan)
    application.state.settings = settings
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    application.add_middleware(UploadBodyLimit, limit=settings.upload_limit, temp_dir=temp)

    @application.exception_handler(StudyError)
    async def business_error(_, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @application.middleware("http")
    async def local_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            allowed = {"http://127.0.0.1:8000", "http://localhost:8000", str(request.base_url).rstrip("/")}
            if origin and origin not in allowed:
                return JSONResponse({"detail": "仅接受本机页面发出的操作。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data: blob:; worker-src 'self' blob:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        response.headers["Cache-Control"] = "no-cache"
        return response

    application.include_router(router)
    application.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    application.mount("/samples", StaticFiles(directory=ROOT / "samples", check_dir=False), name="samples")

    @application.get("/")
    def home():
        return FileResponse(ROOT / "frontend/index.html")

    return application

app = create_app()
