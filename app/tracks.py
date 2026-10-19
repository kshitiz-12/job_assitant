"""Role families people ask for in chat, like "only frontend roles".

These are not skills. "Frontend" will not show up in the skill list, so the
matcher has to recognise the family on its own.
"""

from __future__ import annotations

import re

# Longer families first. "full stack" contains neither front nor back as a word,
# but "frontend" must not be read as part of a longer phrase we add later.
_PHRASES: list[tuple[str, re.Pattern[str]]] = [
    ("fullstack", re.compile(r"\bfull[\s-]?stack\b", re.I)),
    ("frontend", re.compile(r"\bfront[\s-]?end\b", re.I)),
    ("backend", re.compile(r"\bback[\s-]?end\b", re.I)),
    ("mobile", re.compile(r"\b(mobile|ios|android)\b", re.I)),
    ("devops", re.compile(r"\b(devops|sre|site reliability)\b", re.I)),
    ("data", re.compile(r"\b(data scientist|data engineer|data analyst|machine learning)\b", re.I)),
]

_TITLE = {
    "frontend": re.compile(r"front[\s-]?end|\bui engineer\b|\bweb developer\b|\breact\b|\bvue\b|\bangular\b", re.I),
    "backend": re.compile(r"back[\s-]?end|\bbackend\b|\bapi engineer\b|\bplatform engineer\b", re.I),
    "fullstack": re.compile(r"full[\s-]?stack", re.I),
    "mobile": re.compile(r"\b(ios|android|mobile|flutter|react native)\b", re.I),
    "devops": re.compile(r"\b(devops|sre|site reliability|infrastructure|platform)\b", re.I),
    "data": re.compile(r"\b(data|analytics|machine learning|ml)\b", re.I),
}

# A React mention in a data-platform title is not a frontend role.
_EXCLUDE = {
    "frontend": re.compile(r"back[\s-]?end|\bbackend\b|data engineer|devops|\bsre\b|site reliability|\bios\b|\bandroid\b|machine learning", re.I),
    "backend": re.compile(r"front[\s-]?end|\bfrontend\b|\bdesigner\b", re.I),
    "fullstack": re.compile(r"\bdesigner\b|\bintern\b", re.I),
    "mobile": re.compile(r"front[\s-]?end web|back[\s-]?end", re.I),
    "devops": re.compile(r"front[\s-]?end|\bdesigner\b", re.I),
    "data": re.compile(r"front[\s-]?end|\bios\b", re.I),
}

LABELS = {
    "frontend": "frontend",
    "backend": "backend",
    "fullstack": "full stack",
    "mobile": "mobile",
    "devops": "DevOps",
    "data": "data",
}


def track_from_text(text: str) -> str | None:
    for name, pattern in _PHRASES:
        if pattern.search(text or ""):
            return name
    return None


def job_matches_track(job: dict, track: str) -> bool:
    # The title has to be that kind of role. A backend posting that mentions
    # React once is not a frontend job.
    title = job.get("title") or ""
    if track not in _TITLE:
        return False
    if _EXCLUDE[track].search(title):
        return False
    return bool(_TITLE[track].search(title))
