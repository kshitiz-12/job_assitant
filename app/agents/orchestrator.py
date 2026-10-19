"""Orchestrator: read the message, call one or two specialists, then answer.

The plan is the small intent object from intents.py. Parsing, matching, and
applying each live in their own module so a change to scoring can't break
the application log, and the other way around.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.applications import ApplicationAgent, speak_apply, speak_status
from app.agents.intents import interpret
from app.agents.matcher import MatchAgent, describe_filters
from app.agents.resume import ResumeReadError, extract_upload, parse_resume_text, profile_summary
from app.skills import skill_label
from app.store import Store, applicant_key, blank_filters

_HELP = (
    "I read a PDF or DOCX resume, find roles in the dataset that fit your title, skills, and experience, "
    "and record an application when you ask.\n\n"
    "Try dropping the file in, then say something like:\n"
    "show only remote roles\n"
    "jobs needing React\n"
    "apply to job 3\n"
    "show my applied jobs\n\n"
    "If I misread the resume, correct me: \"my title is Data Analyst\" or \"I have 4 years\"."
)


class Orchestrator:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.matcher = MatchAgent(store)
        self.applications = ApplicationAgent(store)

    def handle(self, session_id: str | None, message: str, filename: str | None, data: bytes | None) -> dict:
        with self.store.lock:
            return self._turn(session_id, message or "", filename, data)

    def _turn(self, session_id: str | None, message: str, filename: str | None, data: bytes | None) -> dict:
        session = self.store.ensure_session(session_id)
        user_text = _user_text(message, filename, data)
        activity: list[str] = []
        prelude = ""
        jobs: list[dict] = []
        shown_apps = None

        if data:
            try:
                parsed = self._read_resume(session, extract_upload(filename or "", data))
            except ResumeReadError as exc:
                self._remember(session, "user", user_text)
                self._remember(session, "assistant", exc.message)
                self.store.save_session(session)
                return self._payload(session, user_text, exc.message, [], None, ["Tried to read the resume"])
            prelude = profile_summary(parsed)
            activity.append("Read the resume")
        elif message.strip():
            # interpret() also flags a pasted resume; handle it before filters.
            pass

        intent = interpret(
            message if not (data and not message.strip()) else "",
            profile=session.get("profile"),
            filters=session.get("filters"),
        )
        if data and intent["kind"] in {"empty", "greet", "ack", "fallback", "help"}:
            intent["kind"] = "jobs"
        if intent["kind"] == "pasted_resume" and not data:
            try:
                parsed = self._read_resume(session, message)
            except ResumeReadError as exc:
                self._remember(session, "user", user_text)
                self._remember(session, "assistant", exc.message)
                self.store.save_session(session)
                return self._payload(session, user_text, exc.message, [], None, ["Tried to read the pasted resume"])
            prelude = profile_summary(parsed)
            activity.append("Read the pasted resume")
            intent["kind"] = "jobs"

        filters_changed = self._apply_patches(session, intent)
        kind = intent["kind"]

        if kind in {"jobs", "empty"} and not session.get("profile") and not prelude:
            reply = (
                "I need a resume before I can match anything. "
                "Drop a PDF or DOCX in the chat. I'll remember the filters you just set."
                if intent["filter_patch"] or intent["clear_filters"]
                else "Drop a PDF or DOCX resume in the chat and I'll read it before I go looking for roles."
            )
            if not session.get("profile") and intent["kind"] == "empty" and not data:
                reply = "Drop a PDF or DOCX resume in the chat and I'll read it before I go looking for roles."
        elif kind == "greet":
            name = (session.get("profile") or {}).get("name")
            reply = (
                f"Hey{', ' + name if name else ''}. I still have the resume on file — want a fresh set of matches, or should we narrow them?"
                if session.get("profile")
                else "Hey. Drop a PDF or DOCX resume in and I'll line it up with the roles in the dataset."
            )
        elif kind == "ack":
            reply = (
                "Got it. I can narrow the list, or you can apply with a number from it."
                if session.get("profile")
                else "Got it. Whenever you're ready, send the resume as a PDF or DOCX."
            )
        elif kind == "help":
            reply = _HELP
        elif kind == "profile":
            if session.get("profile"):
                reply = profile_summary(session["profile"])
                activity.append("Pulled up the parsed resume")
            else:
                reply = "I don't have a resume for this chat yet. Upload a PDF or DOCX and I'll show you what I can read."
        elif kind == "status":
            rows = self.applications.list_for(session)
            reply = speak_status(rows)
            shown_apps = rows
            activity.append("Checked saved applications")
        elif kind == "details":
            reply, jobs = self._details(session, intent["detail_index"])
            activity.append("Opened that posting")
        elif kind == "apply":
            if not session.get("profile"):
                reply = "Upload a resume first so I know who the application is for. Then say \"apply to job 3\"."
            else:
                result = self.applications.apply(session, message)
                reply = speak_apply(result, session)
                # Only the rows this turn touched. The full log still goes out as saved_applications.
                shown_apps = result["created"] + result["duplicates"]
                activity.append("Saved the live posting link" if result["created"] else "Checked the application log")
        elif kind == "jobs":
            if not session.get("profile"):
                reply = (
                    "I need a resume before I can match anything. Drop a PDF or DOCX in the chat — "
                    "I'll keep those filters and use them once I've read it."
                )
            else:
                result = self.matcher.recommend(
                    session,
                    more=bool(intent["more"]) and not filters_changed,
                    filters_changed=filters_changed,
                )
                reply = self._speak_jobs(session, result)
                jobs = result["jobs"]
                activity.append(f"Compared the profile with {len(self.store.jobs):,} listings")
        else:
            if session.get("profile"):
                reply = (
                    "I can narrow the roles, open one of them, or record an application. "
                    "\"Remote only\", \"jobs needing Python\", and \"apply to job 2\" all work."
                )
            else:
                reply = "I can read a PDF or DOCX resume and match it to the dataset. Drop the file in whenever you're ready."

        if prelude:
            reply = f"{prelude}\n\n{reply}"

        self._remember(session, "user", user_text)
        self._remember(session, "assistant", reply, jobs=jobs, applications=shown_apps)
        self.store.save_session(session)
        return self._payload(session, user_text, reply, jobs, shown_apps, activity)

    def _read_resume(self, session: dict, text: str) -> dict:
        profile = parse_resume_text(text)
        previous = f"session:{session['id']}"
        session["profile"] = profile
        session["offset"] = 0
        # The browser session is only a stand-in until the resume has an email.
        # Applications follow the email after that, so a later upload of the same
        # resume still finds them. This is a stable key, not an account system.
        self.store.rekey_applications(previous, applicant_key(session))
        return profile

    def _apply_patches(self, session: dict, intent: dict) -> bool:
        changed = False
        filters = session.setdefault("filters", blank_filters())
        if intent.get("clear_filters"):
            session["filters"] = blank_filters()
            filters = session["filters"]
            changed = True
        patch = intent.get("filter_patch") or {}
        for key in ("remote", "location", "level", "track"):
            if key in patch:
                filters[key] = patch[key]
                changed = True
        if "skills" in patch:
            filters["skills"] = list(patch["skills"])
            changed = True
        if patch.get("add_skills"):
            for skill in patch["add_skills"]:
                if skill not in filters["skills"]:
                    filters["skills"].append(skill)
                    changed = True
        if patch.get("remove_skills"):
            before = list(filters["skills"])
            filters["skills"] = [skill for skill in filters["skills"] if skill not in patch["remove_skills"]]
            changed = changed or before != filters["skills"]

        profile = session.get("profile")
        for key, value in (intent.get("profile_patch") or {}).items():
            if not profile:
                break
            if key == "add_skills":
                have = list(profile.get("skills") or [])
                for skill in value:
                    if skill not in have:
                        have.append(skill)
                        changed = True
                profile["skills"] = have
            elif key == "years":
                profile["years"] = int(value) if float(value).is_integer() else value
                changed = True
            elif key == "designation":
                profile["designation"] = value
                changed = True
        if changed:
            session["offset"] = 0
        return changed

    def _speak_jobs(self, session: dict, result: dict) -> str:
        filters = describe_filters(session.get("filters") or {})
        if result["empty"] == "dataset":
            body = "The job dataset isn't loaded, so I can't match or apply right now."
        elif result["empty"] == "filters":
            body = (
                f"Nothing in the dataset matches {filters}. "
                "Say \"clear filters\" or loosen one of them and I'll look again."
            )
        elif result["empty"] == "overlap":
            body = (
                f"I went through {len(self.store.jobs):,} listings and none share enough of your "
                "designation and skills to be worth showing. If the title looks wrong, correct it and I'll search again."
            )
        else:
            total = result["total"]
            shown = len(result["jobs"])
            start = result["offset"] + 1
            end = result["offset"] + shown
            if result["exhausted"]:
                body = f"That's already the full list — {total} {'match' if total == 1 else 'matches'} under {filters}."
            elif result["wrapped"]:
                body = f"That's the end of the matches. Back at the top: {start}–{end} of {total}."
            elif result["loose"]:
                body = (
                    f"These are loose matches — none of them line up closely. "
                    f"Nearest {shown} of {total}, from {len(self.store.jobs):,} listings."
                )
            else:
                body = (
                    f"Showing {start}–{end} of {total} {'match' if total == 1 else 'matches'} "
                    f"from {len(self.store.jobs):,} listings"
                )
                if filters != "no extra filters":
                    body += f" ({filters})"
                body += "."
            if not session.get("explained_ranks") and result["jobs"]:
                session["explained_ranks"] = True
                body += (
                    " Numbers are for this list only — \"apply to job 2\" means the second card. "
                    "Asking to apply saves the live posting link. It does not submit the company form."
                )
        return body

    def _details(self, session: dict, index: int | None) -> tuple[str, list[dict]]:
        last = session.get("last_results") or []
        if not index or index < 1 or index > len(last):
            count = len(last)
            if count == 0:
                return "I haven't shown a list yet. Ask for matches, then say \"tell me about job 1\".", []
            return f"Job {index} isn't on the current list. It's numbered 1 to {count}.", []
        job = self.store.get_job(last[index - 1])
        if not job:
            return "That posting isn't in the dataset anymore.", []
        from app.store import public_job

        card = public_job(job, rank=index, score=None, reason="Details for the role you asked about.", preview=job["description"][:220])
        skills = ", ".join(skill_label(skill) for skill in (job.get("skills") or [])[:8]) or "Not listed"
        where = job["location"]
        if job.get("remote"):
            where += " · remote"
        reply = (
            f"**{job['title']}** at **{job['company']}**\n"
            f"{where}\n"
            f"Experience: {job.get('experience_required')}\n"
            f"Skills: {skills}\n\n"
            f"{job['description'][:700]}\n\n"
            f"Posting: {job['source_link']}\n"
            f"Say \"apply to job {index}\" if you want it recorded."
        )
        return reply, [card]

    def _remember(self, session: dict, role: str, text: str, jobs: list | None = None, applications: list | None = None) -> None:
        session.setdefault("messages", []).append({
            "role": role,
            "text": text,
            "jobs": jobs or [],
            "applications": applications or [],
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    def _payload(self, session, user_text, reply, jobs, applications, activity) -> dict:
        return {
            "session_id": session["id"],
            "user_text": user_text,
            "reply": reply,
            "jobs": jobs or [],
            "applications": applications,
            "profile": session.get("profile"),
            "filters": session.get("filters") or blank_filters(),
            "saved_applications": self.applications.list_for(session),
            "activity": activity,
            "suggestions": _suggestions(session),
            "dataset_size": len(self.store.jobs),
        }


def _user_text(message: str, filename: str | None, data: bytes | None) -> str:
    if data:
        label = f"Uploaded {filename or 'resume'}"
        return f"{label}\n{message}".strip() if message.strip() else label
    return message.strip()


def _suggestions(session: dict) -> list[str]:
    if not session.get("profile"):
        return ["What can you do?"]
    tips = []
    filters = session.get("filters") or {}
    if filters.get("remote") is not True:
        tips.append("Show only remote roles")
    skills = (session.get("profile") or {}).get("skills") or []
    if skills:
        tips.append(f"Jobs needing {skill_label(skills[0])}")
    if (session.get("match_total") or 0) > 5:
        tips.append("Show more")
    tips.append("Show my applied jobs")
    # Keep the row short. Three is enough; a fourth starts to look like a menu.
    return tips[:3]
