"""Gemini reads the chat and writes the reply.

The dataset still picks the jobs. The model chooses which tool to run and
then phrases the answer from the tool result. A missing key, a timeout, or a
reply that claims an application was submitted falls back to the local text.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from app.skills import SKILL_ALIASES
from app.tracks import LABELS

_KNOWN_SKILLS = tuple(name for name, _aliases in SKILL_ALIASES)
_KINDS = {"jobs", "apply", "status", "help", "profile", "details", "advice", "greet", "ack", "fallback"}
_LEVELS = {"intern", "junior", "senior"}
_NOT_SUBMITTED = re.compile(
    r"not submit|did not submit|didn't submit|was not submitted|not been submitted",
    re.I,
)
_FALSE_SUBMIT = re.compile(
    r"\b(i submitted|i applied|application was submitted|successfully applied|has been submitted)\b",
    re.I,
)


def plan_with_gemini(
    message: str,
    profile: dict | None,
    filters: dict | None,
    history: list | None = None,
) -> dict | None:
    if not (message or "").strip():
        return None
    text = _generate(_plan_prompt(message, profile, filters, history), json_mode=True, timeout=10)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return _as_intent(data)


def compose_reply(message: str, history: list | None, facts: dict, fallback: str) -> str:
    """Rewrite the tool result in the user's conversation. Never invent a posting."""
    if not (fallback or "").strip():
        return fallback
    text = _generate(_reply_prompt(message, history, facts), json_mode=False, timeout=12)
    return _accept_reply(text, fallback, facts)


def _generate(prompt: str, *, json_mode: bool, timeout: int) -> str | None:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key or not prompt.strip():
        return None
    model = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    config: dict = {"temperature": 0.4 if not json_mode else 0}
    if json_mode:
        config["responseMimeType"] = "application/json"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": config,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return _response_text(payload) or None


def _plan_prompt(message: str, profile: dict | None, filters: dict | None, history: list | None) -> str:
    resume = "none"
    if profile:
        skills = ", ".join((profile.get("skills") or [])[:12]) or "unknown"
        resume = f"{profile.get('name') or 'unknown'}, {profile.get('designation') or 'unknown title'}, about {profile.get('years')} years, skills: {skills}"
    turns = _history_lines(history)
    return (
        "Read this job-search chat and classify the latest user message.\n"
        "Do not invent jobs, companies, or links. Return JSON only.\n"
        "Keys:\n"
        "kind: jobs | apply | status | help | profile | details | advice | greet | ack | fallback\n"
        "jobs: they want roles, named a title (ai engineer, sde), a company (amazon), a skill, or a place. "
        "A bare stack such as \"js type script node.js\" is jobs, with skills javascript, typescript, node.js.\n"
        "advice: they want resume changes, edits, or what to improve.\n"
        "details: they want one numbered role opened. Set detail_index.\n"
        "apply: they want to record an application. status: they want the saved list.\n"
        "fallback: only when the message is not about the resume, the roles, or an application.\n"
        "more: true when they want the next page\n"
        "clear_filters: true when they want every filter removed\n"
        "remote: true, false, or null. Omit the key if this message does not change it. "
        "Use null when they name a new title or company and do not mention remote.\n"
        "track: frontend | backend | fullstack | mobile | devops | data | null\n"
        "skills: canonical names only, from this list, or []. "
        "Use [] when a new title or company replaces an older skill filter. Omit the key if skills stay as they are.\n"
        "Known skills: " + ", ".join(_KNOWN_SKILLS) + "\n"
        "location: a place they named, or null\n"
        "level: intern | junior | senior | null\n"
        "query: the role title they asked for, such as \"ai engineer\" or \"sde\". "
        "Null when they did not name a title. Do not put the company name in query.\n"
        "company: the employer they named, or null. Use the words they used.\n"
        "detail_index: the job number they want details for, or null\n"
        "designation: a corrected job title for their own resume, or null\n"
        "years: a number they stated about themselves, or null\n"
        f"Current filters: {json.dumps(filters or {}, default=str)}\n"
        f"Resume on file: {resume}\n"
        f"Recent chat:\n{turns}\n"
        f"Latest message: {message.strip()[:2000]}"
    )


def _reply_prompt(message: str, history: list | None, facts: dict) -> str:
    return (
        "You are the chat assistant in a job search. Rewrite the draft as a natural reply "
        "to the latest message, using the recent chat for context.\n"
        "Rules:\n"
        "- Use only the jobs, companies, links, and resume facts in the draft and the JSON.\n"
        "- Do not invent a posting, an employer, a link, or a metric.\n"
        "- An application status of not_submitted means the company form was not sent. "
        "Never say you submitted it or that they applied.\n"
        "- Keep the same outcome as the draft: if it found nothing, say nothing was found.\n"
        "- Two or three short sentences. Bold a job title with **title** when you name one.\n"
        "- Plain text, no JSON.\n"
        f"Recent chat:\n{_history_lines(history)}\n"
        f"Latest message: {(message or '').strip()[:2000]}\n"
        f"Facts: {json.dumps(facts, default=str)[:4000]}\n"
        f"Draft:\n{(facts.get('draft') or '')[:1600]}"
    )


def _history_lines(history: list | None) -> str:
    lines = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = "User" if item.get("role") == "user" else "Assistant"
        text = " ".join(str(item.get("text") or "").split())[:400]
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines[-6:]) or "(none)"


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
    if isinstance(data.get("skills"), list):
        patch["skills"] = [skill for skill in data["skills"] if skill in _KNOWN_SKILLS]
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
    query = data.get("query")
    if isinstance(query, str) and query.strip():
        patch["query"] = " ".join(query.lower().split())[:80]
    elif query is None and "query" in data:
        patch["query"] = None
    company = data.get("company")
    if isinstance(company, str) and company.strip():
        patch["company"] = company.strip()[:80]
    elif company is None and "company" in data:
        patch["company"] = None

    profile: dict = {}
    designation = data.get("designation")
    if isinstance(designation, str) and designation.strip():
        profile["designation"] = designation.strip()[:80]
    years = data.get("years")
    if isinstance(years, (int, float)) and not isinstance(years, bool):
        profile["years"] = float(years)
    if data.get("add_to_profile") and patch.get("skills"):
        profile["add_skills"] = patch["skills"]

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


def _accept_reply(text: str | None, fallback: str, facts: dict) -> str:
    cleaned = _clean_prose(text or "")
    if not cleaned or len(cleaned) > 1800:
        return fallback
    if _FALSE_SUBMIT.search(cleaned):
        return fallback
    if facts.get("must_not_claim_submitted") and not _NOT_SUBMITTED.search(cleaned):
        return fallback
    return cleaned


def _clean_prose(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
