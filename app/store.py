"""JSON files are the database. Jobs are read-only; applications and sessions get written."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from app.textutil import today_iso

PUBLIC_JOB_FIELDS = (
    "id",
    "title",
    "company",
    "location",
    "experience_required",
    "experience_years_min",
    "skills",
    "description",
    "source_link",
    "source",
    "remote",
)


def blank_filters() -> dict:
    return {
        "remote": None,
        "skills": [],
        "location": None,
        "level": None,
        "track": None,
        "query": None,
        "company": None,
        "skill_match": "all",
    }


def blank_session(session_id: str) -> dict:
    return {
        "id": session_id,
        "profile": None,
        "filters": blank_filters(),
        "offset": 0,
        "last_results": [],
        "match_total": 0,
        "explained_ranks": False,
        "messages": [],
        "created_at": today_iso(),
    }


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_path = data_dir / "jobs.json"
        self.applications_path = data_dir / "applications.json"
        self.sessions_path = data_dir / "sessions.json"
        # A turn locks once, then store helpers lock again. RLock keeps that from deadlocking.
        self.lock = threading.RLock()
        self.load_error = ""
        self.meta: dict = {}
        self.jobs: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.applications: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self._load_jobs()
        self._load_applications()
        self._load_sessions()

    def _load_jobs(self) -> None:
        if not self.jobs_path.exists():
            self.load_error = "jobs.json is missing. Run scripts/scrape_jobs.py."
            return
        try:
            raw = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.load_error = "jobs.json is not valid JSON."
            return
        rows = raw["jobs"] if isinstance(raw, dict) else raw
        self.meta = raw if isinstance(raw, dict) else {}
        cleaned = []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("id") or not row.get("title"):
                continue
            job = {key: row.get(key) for key in PUBLIC_JOB_FIELDS}
            job["skills"] = [str(s).lower() for s in (row.get("skills") or [])]
            job["remote"] = bool(row.get("remote"))
            job["description"] = str(row.get("description") or "")
            job["location"] = str(row.get("location") or "Unspecified")
            job["experience_required"] = str(row.get("experience_required") or "Not specified")
            blob_skills = " ".join(job["skills"])
            job["_skills"] = set(job["skills"])
            job["_blob"] = f"{job['title']} {job['location']} {blob_skills} {job['description']}".lower()
            cleaned.append(job)
        self.jobs = cleaned
        self.by_id = {job["id"]: job for job in cleaned}
        if not cleaned and not self.load_error:
            self.load_error = "jobs.json has no usable listings."

    def _load_applications(self) -> None:
        self.applications = _read_list(self.applications_path, "applications")

    def _load_sessions(self) -> None:
        if not self.sessions_path.exists():
            self.sessions = {}
            return
        try:
            raw = json.loads(self.sessions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.sessions = {}
            return
        self.sessions = raw if isinstance(raw, dict) else {}

    def get_job(self, job_id: str) -> dict | None:
        return self.by_id.get(job_id)

    def ensure_session(self, session_id: str | None) -> dict:
        with self.lock:
            sid = session_id or ""
            try:
                uuid.UUID(sid)
            except (ValueError, AttributeError, TypeError):
                sid = str(uuid.uuid4())
            session = self.sessions.get(sid)
            if not session:
                session = blank_session(sid)
                self.sessions[sid] = session
                self._save_sessions()
            session.setdefault("filters", blank_filters())
            session.setdefault("messages", [])
            session.setdefault("last_results", [])
            session.setdefault("offset", 0)
            return session

    def save_session(self, session: dict) -> None:
        with self.lock:
            session["messages"] = session.get("messages", [])[-40:]
            self.sessions[session["id"]] = session
            # Keep the file from growing without bound on a long-lived demo box.
            if len(self.sessions) > 200:
                ordered = sorted(self.sessions.values(), key=lambda item: item.get("created_at") or "")
                for old in ordered[:-200]:
                    self.sessions.pop(old["id"], None)
            self._save_sessions()

    def applications_for(self, key: str) -> list[dict]:
        rows = [row for row in self.applications if row.get("applicant_key") == key]
        rows.sort(key=lambda row: row.get("applied_date") or "", reverse=True)
        return rows

    def find_application(self, key: str, job_id: str) -> dict | None:
        for row in self.applications:
            if row.get("applicant_key") == key and row.get("job_id") == job_id:
                return row
        return None

    def add_application(self, record: dict) -> dict:
        with self.lock:
            self.applications.append(record)
            _atomic_write(self.applications_path, {"applications": self.applications})
            return record

    def rekey_applications(self, old_key: str, new_key: str) -> None:
        """Move rows off the browser session once we know the resume's email."""
        if not old_key or not new_key or old_key == new_key:
            return
        with self.lock:
            existing = {
                row["job_id"]
                for row in self.applications
                if row.get("applicant_key") == new_key
            }
            changed = False
            kept = []
            for row in self.applications:
                if row.get("applicant_key") != old_key:
                    kept.append(row)
                    continue
                changed = True
                if row.get("job_id") in existing:
                    continue
                row["applicant_key"] = new_key
                existing.add(row["job_id"])
                kept.append(row)
            if changed:
                self.applications = kept
                _atomic_write(self.applications_path, {"applications": self.applications})

    def _save_sessions(self) -> None:
        _atomic_write(self.sessions_path, self.sessions)


def applicant_key(session: dict) -> str:
    email = ((session.get("profile") or {}).get("email") or "").strip().lower()
    if email:
        return f"email:{email}"
    return f"session:{session['id']}"


def public_job(job: dict, **extra) -> dict:
    payload = {key: job.get(key) for key in PUBLIC_JOB_FIELDS if not key.startswith("_")}
    payload.update(extra)
    return payload


def _read_list(path: Path, key: str) -> list:
    if not path.exists():
        _atomic_write(path, {key: []})
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(raw, dict) and isinstance(raw.get(key), list):
        return raw[key]
    if isinstance(raw, list):
        return raw
    return []


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
