"""Ask Gemini what the user meant. It does not pick jobs.

The database stays the source of roles. The model only returns a small JSON
plan: which tool to run, and which filters changed. A missing key, a timeout,
or a weird answer falls back to the phrase rules.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.skills import SKILL_ALIASES
from app.tracks import LABELS

_KNOWN_SKILLS = tuple(name for name, _aliases in SKILL_ALIASES)
_KINDS = {"jobs", "apply", "status", "help", "profile", "details", "advice", "greet", "ack", "fallback"}
_LEVELS = {"intern", "junior", "senior"}


def plan_with_gemini(message: str, profile: dict | None, filters: dict | None) -> dict | None:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key or not (message or "").strip():
        return None
    model = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": _prompt(message, profile, filters)}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    text = _response_text(payload)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return _as_intent(data)


def _prompt(message: str, profile: dict | None, filters: dict | None) -> str:
    resume = "none"
    if profile:
        skills = ", ".join((profile.get("skills") or [])[:12]) or "unknown"
        resume = f"{profile.get('designation') or 'unknown title'}, about {profile.get('years')} years, skills: {skills}"
    current = filters or {}
    return (
        "Classify one message for a job-search chat.\n"
        "Do not invent jobs, companies, or links. Return JSON only.\n"
        "Keys:\n"
        "kind: jobs | apply | status | help | profile | details | advice | greet | ack | fallback\n"
        "Use advice when they ask what to change, add, or improve on the resume.\n"
        "more: true when they want the next page\n"
        "clear_filters: true when they want every filter removed\n"
        "remote: true, false, or null. Use null when they name a new kind of role and do not mention remote, "
        "so an older remote filter is cleared. Use true only if this message asks for remote.\n"
        "track: frontend | backend | fullstack | mobile | devops | data | null\n"
        "skills: canonical names only, from this list: " + ", ".join(_KNOWN_SKILLS) + "\n"
        "location: a place they named, or null\n"
        "level: intern | junior | senior | null\n"
        "detail_index: the job number they want details for, or null\n"
        "designation: a corrected job title, or null\n"
        "years: a number they stated, or null\n"
        f"Current filters: {json.dumps(current, default=str)}\n"
        f"Resume on file: {resume}\n"
        f"Message: {message.strip()[:2000]}"
    )


def _response_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    return "".join(part.get("text") or "" for part in parts if isinstance(part, dict)).strip()


def _as_intent(data: dict) -> dict | None:
    kind = str(data.get("kind") or "fallback").lower()
    if kind not in _KINDS or kind == "fallback":
        return None
    patch: dict = {}
    if "remote" in data and data["remote"] in (True, False, None):
        patch["remote"] = data["remote"]
    track = data.get("track")
    if track in LABELS:
        patch["track"] = track
    elif track is None and "track" in data:
        patch["track"] = None
    skills = [skill for skill in (data.get("skills") or []) if skill in _KNOWN_SKILLS]
    if skills:
        patch["skills"] = skills
    location = data.get("location")
    if isinstance(location, str) and location.strip():
        patch["location"] = location.strip()[:80]
    elif location is None and "location" in data:
        patch["location"] = None
    level = data.get("level")
    if level in _LEVELS:
        patch["level"] = level
    elif level is None and "level" in data:
        patch["level"] = None

    profile: dict = {}
    designation = data.get("designation")
    if isinstance(designation, str) and designation.strip():
        profile["designation"] = designation.strip()[:80]
    years = data.get("years")
    if isinstance(years, (int, float)) and not isinstance(years, bool):
        profile["years"] = float(years)
    if skills and data.get("add_to_profile"):
        profile["add_skills"] = skills

    detail = data.get("detail_index")
    detail_index = int(detail) if isinstance(detail, int) and not isinstance(detail, bool) else None
    return {
        "kind": kind,
        "more": bool(data.get("more")),
        "clear_filters": bool(data.get("clear_filters")),
        "filter_patch": patch,
        "profile_patch": profile,
        "detail_index": detail_index,
    }
