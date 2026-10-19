"""Score dataset jobs against the parsed resume and the filters from chat."""

from __future__ import annotations

import re

from app.skills import WEAK_SKILLS, skill_label
from app.store import Store, public_job

PAGE_SIZE = 5

_TITLE_STOP = frozenset({
    "senior", "junior", "lead", "staff", "principal", "the", "and", "for", "with",
    "level", "sr", "jr", "mid", "remote", "hybrid", "ii", "iii", "iv", "of", "in",
    "at", "to", "a", "an",
})


class MatchAgent:
    def __init__(self, store: Store) -> None:
        self.store = store

    def recommend(self, session: dict, *, more: bool = False, filters_changed: bool = False) -> dict:
        if not self.store.jobs:
            return {
                "jobs": [],
                "total": 0,
                "empty": "dataset",
                "loose": False,
                "wrapped": False,
                "exhausted": False,
                "offset": 0,
            }
        if filters_changed:
            session["offset"] = 0
        ranked, empty = self._rank(session)
        wrapped = False
        exhausted = False
        if empty:
            session["last_results"] = []
            session["match_total"] = 0
            session["offset"] = 0
            return {
                "jobs": [],
                "total": 0,
                "empty": empty,
                "loose": False,
                "wrapped": False,
                "exhausted": False,
                "offset": 0,
            }
        loose = ranked[0]["score"] < 0.45 and not _explicit(session)
        page_size = 3 if loose else PAGE_SIZE
        if more:
            if len(ranked) <= page_size:
                exhausted = True
                session["offset"] = 0
            else:
                session["offset"] = int(session.get("offset") or 0) + page_size
                if session["offset"] >= len(ranked):
                    session["offset"] = 0
                    wrapped = True
        offset = int(session.get("offset") or 0)
        page = ranked[offset:offset + page_size]
        session["last_results"] = [item["job"]["id"] for item in page]
        session["match_total"] = len(ranked)
        cards = []
        for index, item in enumerate(page, start=1):
            job = item["job"]
            preview = job["description"][:220].rsplit(" ", 1)[0] if len(job["description"]) > 220 else job["description"]
            cards.append(public_job(
                job,
                rank=index,
                score=item["percent"],
                reason=item["reason"],
                preview=preview,
            ))
        return {
            "jobs": cards,
            "total": len(ranked),
            "empty": None,
            "loose": loose,
            "wrapped": wrapped,
            "exhausted": exhausted,
            "offset": offset,
        }

    def _rank(self, session: dict) -> tuple[list[dict], str | None]:
        profile = session.get("profile") or {}
        filters = session.get("filters") or {}
        user_skills = [str(s).lower() for s in (profile.get("skills") or [])]
        designation = profile.get("designation") or ""
        years = profile.get("years")
        required = [str(s).lower() for s in (filters.get("skills") or [])]

        passed_filter = 0
        scored: list[dict] = []
        for job in self.store.jobs:
            if not _passes_filters(job, filters, required):
                continue
            passed_filter += 1
            overlap = _overlap(user_skills, job)
            strong = [skill for skill in overlap if skill not in WEAK_SKILLS]
            title_score = _title_score(designation, job["title"])
            exp_score = _experience_score(years, job)
            skill_score = _skill_score(strong, job)
            score = 0.52 * skill_score + 0.30 * title_score + 0.18 * exp_score
            if required and any(skill in job["_blob"] for skill in required):
                score += 0.06
            # A 3-year resume shouldn't lose the page to staff roles just because
            # both say "software engineer" and share a language.
            if _too_senior(job, years):
                score -= 0.14
            explicit = _explicit(session)
            # A direct ask ("jobs needing React") should still surface the role
            # when the resume never mentions React. Don't hide that as "no match".
            if not explicit and not strong and title_score < 0.34:
                continue
            if not explicit and score < 0.38:
                continue
            scored.append({
                "job": job,
                "score": score,
                "percent": _percent(score),
                "reason": _reason(profile, job, strong, title_score, required),
                "strong_count": len(strong),
            })
        if passed_filter == 0:
            return [], "filters"
        if not scored:
            return [], "overlap"
        scored.sort(key=lambda item: (item["score"], item["strong_count"]), reverse=True)
        return _diversify(scored), None


def describe_filters(filters: dict) -> str:
    bits = []
    remote = filters.get("remote")
    if remote is True:
        bits.append("remote only")
    elif remote is False:
        bits.append("on-site only")
    skills = filters.get("skills") or []
    if skills:
        bits.append("needs " + ", ".join(skill_label(s) for s in skills))
    if filters.get("location"):
        bits.append("in " + str(filters["location"]))
    if filters.get("level"):
        bits.append(str(filters["level"]))
    return ", ".join(bits) if bits else "no extra filters"


def _explicit(session: dict) -> bool:
    filters = session.get("filters") or {}
    return bool(
        filters.get("skills")
        or filters.get("location")
        or filters.get("level")
        or filters.get("remote") is not None
    )


def _passes_filters(job: dict, filters: dict, required: list[str]) -> bool:
    remote = filters.get("remote")
    location = (job.get("location") or "").lower()
    if remote is True and not (job.get("remote") or "remote" in location):
        return False
    if remote is False and (job.get("remote") or "remote" in location):
        return False
    place = (filters.get("location") or "").strip().lower()
    if place and place not in job["_blob"]:
        return False
    for skill in required:
        if skill not in job["_blob"] and skill not in job["_skills"]:
            return False
    level = filters.get("level")
    if level and not _level_ok(job, level):
        return False
    return True


def _level_ok(job: dict, level: str) -> bool:
    title = job["title"].lower()
    years = job.get("experience_years_min")
    if level == "intern":
        return bool(re.search(r"intern|new grad|university grad|graduate program", title)) or years == 0
    if level == "junior":
        if re.search(r"senior|staff|principal|director", title):
            return False
        if isinstance(years, int) and years >= 5:
            return False
        return True
    if level == "senior":
        return bool(re.search(r"senior|staff|principal", title)) or (isinstance(years, int) and years >= 5)
    return True


def _overlap(user_skills: list[str], job: dict) -> list[str]:
    hits = []
    blob = job["_blob"]
    known = job["_skills"]
    for skill in user_skills:
        if skill in known or skill in blob:
            hits.append(skill)
    return hits


def _skill_score(strong: list[str], job: dict) -> float:
    if not strong:
        return 0.0
    job_skills = [s for s in job["_skills"] if s not in WEAK_SKILLS] or list(job["_skills"])
    coverage = len(set(strong) & set(job_skills)) / max(min(len(job_skills), 8), 1)
    volume = min(len(strong), 6) / 6
    return 0.6 * coverage + 0.4 * volume


def _title_score(designation: str, title: str) -> float:
    left = _title_tokens(designation)
    right = _title_tokens(title)
    if not left or not right:
        return 0.0
    shared = left & right
    if not shared:
        return 0.0
    return len(shared) / len(left | right)


def _title_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9+#]+", (value or "").lower())
    return {token for token in tokens if token not in _TITLE_STOP and len(token) > 1}


def _too_senior(job: dict, years) -> bool:
    if not isinstance(years, (int, float)):
        return False
    if not re.search(r"\b(senior|staff|principal|director)\b", job["title"], re.I):
        return False
    minimum = job.get("experience_years_min")
    bar = float(minimum) if isinstance(minimum, (int, float)) and minimum else 5.0
    return float(years) + 1 < bar


def _experience_score(years, job: dict) -> float:
    title = job["title"].lower()
    minimum = job.get("experience_years_min")
    internish = bool(re.search(r"intern|new grad|entry", title))
    if years is None:
        return 0.55
    years = float(years)
    if internish or minimum == 0:
        if years <= 1.5:
            return 0.95
        if years <= 3:
            return 0.62
        return 0.28
    if minimum is None:
        return 0.6
    if years + 0.25 >= float(minimum):
        gap = years - float(minimum)
        if gap > 8:
            return 0.5
        return 1.0
    short = float(minimum) - years
    if short <= 1:
        return 0.72
    if short <= 2:
        return 0.45
    return 0.18


def _percent(score: float) -> int:
    pct = round(38 + score * 58)
    return max(40, min(97, pct))


def _reason(profile: dict, job: dict, strong: list[str], title_score: float, required: list[str]) -> str:
    bits = []
    if strong:
        shown = [skill_label(skill) for skill in strong[:4]]
        extra = len(strong) - len(shown)
        if extra:
            skills = ", ".join(shown) + f", and {extra} more"
        else:
            skills = _join(shown)
        bits.append(f"Shares {skills}")
    elif required:
        asked = _join(skill_label(skill) for skill in required)
        bits.append(f"Lists {asked}, which you asked for. It's a stretch against the rest of the resume")
    designation = profile.get("designation")
    if designation and title_score >= 0.34:
        bits.append(f"the title sits close to {designation}")
    years = profile.get("years")
    label = job.get("experience_required") or "Not specified"
    minimum = job.get("experience_years_min")
    if isinstance(years, (int, float)) and label != "Not specified":
        number = int(years) if float(years).is_integer() else years
        if minimum is None or float(years) + 0.25 >= float(minimum):
            bits.append(f"asks for {label}, which fits your {number} years")
        else:
            bits.append(f"asks for {label}, which is past your {number} years")
    elif label not in ("Not specified",):
        bits.append(f"experience listed as {label}")
    if not bits:
        bits.append("Kept because it was the closest title under the current filters")
    sentences = []
    for bit in bits:
        text = bit.strip().rstrip(".")
        text = text[0].upper() + text[1:]
        sentences.append(text + ".")
    return " ".join(sentences)


def _join(items) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _diversify(ranked: list[dict]) -> list[dict]:
    """Don't let one employer occupy the whole first page."""
    picked: list[dict] = []
    overflow: list[dict] = []
    counts: dict[str, int] = {}
    for item in ranked:
        company = item["job"]["company"]
        if counts.get(company, 0) >= 2:
            overflow.append(item)
            continue
        picked.append(item)
        counts[company] = counts.get(company, 0) + 1
    return picked + overflow
