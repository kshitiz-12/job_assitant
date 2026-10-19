"""HTTP surface for the chat. The UI is static files; this is the whole API."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.orchestrator import Orchestrator
from app.store import Store

log = logging.getLogger("jobchat")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
MAX_UPLOAD = 4 * 1024 * 1024


class QuietStatic(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # Browsers will happily keep yesterday's CSS during a demo.
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(data_dir: Path | None = None) -> FastAPI:
    if data_dir is None:
        data_dir = Path(os.environ.get("DATA_DIR", ROOT / "data"))
    store = Store(data_dir)
    orchestrator = Orchestrator(store)
    app = FastAPI(title="Job Chat Assistant")
    app.state.store = store
    app.state.orchestrator = orchestrator

    @app.get("/api/health")
    def health():
        sources: dict[str, int] = {}
        for job in store.jobs:
            sources[job.get("source") or "Unknown"] = sources.get(job.get("source") or "Unknown", 0) + 1
        return {
            "ok": bool(store.jobs) and not store.load_error,
            "jobs": len(store.jobs),
            "sources": sources,
            "error": store.load_error or None,
            "generated_at": store.meta.get("generated_at"),
        }

    @app.get("/api/session/{session_id}")
    def get_session(session_id: str):
        session = store.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="No chat with that id.")
        return {
            "session_id": session["id"],
            "profile": session.get("profile"),
            "filters": session.get("filters"),
            "messages": session.get("messages") or [],
            "applications": orchestrator.applications.list_for(session),
        }

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not in the dataset.")
        from app.store import public_job
        return public_job(job)

    @app.post("/api/chat")
    async def chat(
        message: str = Form(""),
        session_id: str = Form(""),
        file: UploadFile | None = File(None),
    ):
        data = None
        filename = None
        if file is not None and file.filename:
            data = await file.read()
            filename = file.filename
            if len(data) > MAX_UPLOAD:
                return _error_payload(session_id, "That file is over 4 MB. Send a smaller PDF or DOCX.")
            if len(data) == 0:
                return _error_payload(session_id, "That file was empty.")
        if not (message or "").strip() and not data:
            return _error_payload(session_id, "Say something, or attach a resume.")
        if len(message or "") > 20000:
            return _error_payload(session_id, "That message is too long to read as chat. Attach the resume as a file instead.")
        try:
            return orchestrator.handle(session_id or None, message or "", filename, data)
        except Exception:
            log.exception("chat turn failed")
            return _error_payload(session_id, "Something went wrong on my side while handling that. Try it once more.")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", QuietStatic(directory=STATIC), name="static")
    log.info("loaded %s jobs from %s", len(store.jobs), store.jobs_path)
    if store.load_error:
        log.warning("%s", store.load_error)
    return app


def _error_payload(session_id: str, reply: str) -> dict:
    return {
        "session_id": session_id or None,
        "user_text": "",
        "reply": reply,
        "jobs": [],
        "applications": None,
        "profile": None,
        "filters": {"remote": None, "skills": [], "location": None, "level": None},
        "saved_applications": [],
        "activity": [],
        "suggestions": [],
        "dataset_size": 0,
    }


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
app = create_app()
