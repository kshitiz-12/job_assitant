"""Decide which tool the orchestrator should run.

The phrases are the ones a person actually types at a job chat
("only remote", "apply to job 3"). Anything we don't recognize falls through
to a short clarification instead of a made-up answer.
"""

from __future__ import annotations

import re

from app.agents.llm import plan_with_gemini
from app.skills import extract_skills
from app.tracks import track_from_text

_APPLY = re.compile(r"\b(apply|applying)\b|\bapplication\s+(for|to)\b", re.I)
_STATUS = re.compile(
    r"\b(applied|applications|application status|what did i apply|my apps)\b",
    re.I,
)
_JOBS = re.compile(
    r"\b(jobs?|roles?|openings?|recommend|matches|matching|find|search|hiring|opportunities)\b",
    re.I,
)
_MORE = re.compile(r"\b(show more|more roles|more jobs|next page|next five|next 5)\b", re.I)
_CLEAR = re.compile(r"\b(clear|reset|drop)\s+(all\s+)?filters\b|\bshow all (matches|roles|jobs)\b", re.I)
_HELP = re.compile(r"\b(help|what can you do|how does this work|who are you|what do you do)\b", re.I)
_GREET = re.compile(r"^(hi|hey|hello|yo|good morning|good afternoon|good evening)[!. ]*$", re.I)
_ACK = re.compile(r"^(thanks|thank you|ty|ok|okay|cool|great|nice|got it|perfect)[.! ]*$", re.I)
_PROFILE = re.compile(
    r"\b(my resume|parsed resume|what did you (get|extract|read|find)|show my (profile|details|resume)|what do you have on me)\b",
    re.I,
)
_DETAILS = re.compile(r"\b(more about|tell me about|details on|details for|what about)\b", re.I)
_ADVICE = re.compile(
    r"\b(improve|tailor|rewrite|fix|update) (my |the )?resume\b"
    r"|\bresume (tips|feedback|suggestions|changes|advice)\b"
    r"|\b(changes|edits|tweaks|improvements) (to|for|on) (my |the )?resume\b"
    r"|\bsuggest(?:ion|ions)?\b.{0,40}\b(change|changes|improve|improvements|edit|edits|tweak|tweaks|resume)\b"
    r"|\b(change|changes|improve|improvements|edit|edits)\b.{0,40}\b(resume|cv)\b"
    r"|\bwhat (should|would|can|could) (i|you) (change|add|fix|improve|tweak)\b"
    r"|\bhow (can|should|do|would) i (improve|change|fix|tailor)\b",
    re.I,
)
_SKILL_ADD = re.compile(
    r"\bi (?:also )?(?:know|use|have worked with|have experience with)\b",
    re.I,
)


def interpret(message: str, profile: dict | None = None, filters: dict | None = None) -> dict:
    intent = _interpret_rules(message)
    # Apply, status, and greet stay on the rules. The model only rewrites
    # an open-ended search sentence, and only when a key is configured.
    if intent["kind"] in {"jobs", "fallback"}:
        planned = plan_with_gemini(message, profile, filters)
        if planned:
            return planned
    return intent


def _interpret_rules(message: str) -> dict:
    text = (message or "").strip()
    low = text.lower()
    intent = {
        "kind": "fallback",
        "more": False,
        "clear_filters": False,
        "filter_patch": {},
        "profile_patch": {},
        "detail_index": None,
    }
    if not text:
        intent["kind"] = "empty"
        return intent
    # A pasted resume is long and full of words like "role". Catch it before
    # the job-search matcher treats the whole document as a filter.
    if _looks_like_pasted_resume(text):
        intent["kind"] = "pasted_resume"
        return intent
    if _ACK.match(low):
        intent["kind"] = "ack"
        return intent
    if _GREET.match(low):
        intent["kind"] = "greet"
        return intent
    if _HELP.search(low) and not _APPLY.search(low):
        intent["kind"] = "help"
        return intent

    # "show my applied jobs" contains "jobs", so status has to win before the job search.
    if _wants_status(low):
        intent["kind"] = "status"
        return intent
    if _APPLY.search(low):
        intent["kind"] = "apply"
        return intent
    if _PROFILE.search(low):
        intent["kind"] = "profile"
        return intent
    if _ADVICE.search(low) and not _APPLY.search(low):
        intent["kind"] = "advice"
        return intent

    detail = _detail_index(low)
    if detail and _DETAILS.search(low):
        intent["kind"] = "details"
        intent["detail_index"] = detail
        return intent

    patch, profile_patch, more, clear = _patches(text)
    intent["filter_patch"] = patch
    intent["profile_patch"] = profile_patch
    intent["more"] = more
    intent["clear_filters"] = clear
    if more or clear or patch or profile_patch or _JOBS.search(low):
        intent["kind"] = "jobs"
        return intent
    if _looks_like_pasted_resume(text):
        intent["kind"] = "pasted_resume"
        return intent
    return intent


def _wants_status(low: str) -> bool:
    if _APPLY.search(low):
        return False
    if "my application" in low and not re.search(r"\bapplication\s+(for|to)\b", low):
        return True
    return bool(_STATUS.search(low))


def _detail_index(low: str) -> int | None:
    match = re.search(r"(?:#|job|role|number)\s*(\d{1,2})\b", low)
    if match:
        return int(match.group(1))
    words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    for word, number in words.items():
        if re.search(rf"\b{word}\b", low):
            return number
    return None


def _patches(text: str) -> tuple[dict, dict, bool, bool]:
    low = text.lower()
    patch: dict = {}
    profile: dict = {}
    more = bool(_MORE.search(low))
    clear = bool(_CLEAR.search(low))

    title = re.search(r"\bmy (?:title|role|designation) is\s+(.{3,80})", text, re.I)
    if title:
        profile["designation"] = _trim_phrase(title.group(1))
    years = re.search(r"\bi (?:have|have got|ve got)\s+(\d+(?:\.\d+)?)\s*\+?\s*years\b", low)
    if years:
        profile["years"] = float(years.group(1))
    if _SKILL_ADD.search(text):
        added = extract_skills(text, limit=12)
        if added:
            profile["add_skills"] = added

    # "only frontend roles" must not be read as "only remote". The remote
    # pattern used to be loose enough that a previous remote filter just stayed.
    mentions_remote = bool(re.search(r"\bremote\b|\bwfh\b|work from home", low))
    if re.search(r"\b(on-?site only|in[- ]office only|office only|not remote)\b", low):
        patch["remote"] = False
    elif re.search(r"\b(include on-?site|not just remote|any workplace|remote or office)\b", low):
        patch["remote"] = None
    elif mentions_remote and re.search(r"\b(only remote|remote only|remote roles?|fully remote|work from home|wfh|remote)\b", low):
        patch["remote"] = True

    track = track_from_text(low)
    if track:
        patch["track"] = track
        # A new family replaces the workplace filter unless they asked for both.
        if "remote" not in patch:
            patch["remote"] = None

    if re.search(r"\b(internships?|intern roles|only intern)\b", low):
        patch["level"] = "intern"
    elif re.search(r"\b(entry[- ]level|junior roles|new grad)\b", low):
        patch["level"] = "junior"
    elif re.search(r"\b(senior|staff)\b", low) and re.search(r"\b(only|roles|jobs|show|filter)\b", low):
        patch["level"] = "senior"
    elif re.search(r"\b(any level|all levels)\b", low):
        patch["level"] = None

    location = re.search(
        r"\b(?:in|near|around|based in|located in)\s+([A-Za-z][A-Za-z .'-]{1,40})",
        text,
        re.I,
    )
    if location and not re.search(r"\b(in the dataset|in this list|in the list)\b", low):
        place = _trim_phrase(location.group(1))
        # "in React" is a skill phrase, not a city. Drop it when the whole place is a skill.
        if place and not extract_skills(place, limit=3):
            patch["location"] = place
    if re.search(r"\b(any location|anywhere|all locations)\b", low) and "remote" not in low:
        patch["location"] = None

    # "I know React" updates the profile. Don't also lock the search to only React.
    if "add_skills" not in profile:
        mentioned = extract_skills(text, limit=8)
        skillish = bool(re.search(
            r"\b(needing|that need|that use|require|requires|requiring|with|using|knowing|filter)\b",
            low,
        )) or bool(re.search(r"\b(jobs?|roles?|openings?)\b", low))
        drop = re.search(r"\b(?:drop|remove|without)\s+(.{2,40})", text, re.I)
        if drop:
            gone = extract_skills(drop.group(1), limit=6)
            if gone:
                patch["remove_skills"] = gone
                mentioned = [skill for skill in mentioned if skill not in gone]
        if mentioned and (skillish or re.search(r"\b(only|just)\b", low)):
            if re.search(r"\b(also|and also|plus|as well)\b", low):
                patch["add_skills"] = mentioned
            else:
                patch["skills"] = mentioned
    return patch, profile, more, clear


def _trim_phrase(value: str) -> str:
    value = re.split(
        r"\b(looking|who|that|with|please|roles|jobs|openings|and i|,)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    return value.strip(" .,-")


def _looks_like_pasted_resume(text: str) -> bool:
    if len(text) < 400 or text.count("\n") < 4:
        return False
    has_contact = "@" in text or "linkedin.com" in text.lower()
    return has_contact
