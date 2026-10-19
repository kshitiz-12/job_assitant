"""Record applications. One row per person per job — asking twice doesn't insert twice."""

from __future__ import annotations

import re

from app.skills import skill_label
from app.store import Store, applicant_key
from app.textutil import pretty_date, today_iso

_ORDINALS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
}


class ApplicationAgent:
    def __init__(self, store: Store) -> None:
        self.store = store

    def apply(self, session: dict, message: str) -> dict:
        key = applicant_key(session)
        targets, problems = self._resolve(session, message)
        created = []
        dupes = []
        if not targets and not problems:
            problems = ["unspecified"]
        for job_id in targets:
            job = self.store.get_job(job_id)
            if not job:
                problems.append(f"missing:{job_id}")
                continue
            existing = self.store.find_application(key, job_id)
            if existing:
                dupes.append(existing)
                continue
            record = {
                "job_id": job["id"],
                "applied_date": today_iso(),
                # The company form is behind a captcha. This row is the link we
                # kept, not a submission.
                "status": "not_submitted",
                "applicant_key": key,
                "applicant_name": (session.get("profile") or {}).get("name"),
                "job_title": job["title"],
                "company": job["company"],
                "source_link": job["source_link"],
            }
            self.store.add_application(record)
            created.append(record)
        return {"created": created, "duplicates": dupes, "problems": problems}

    def list_for(self, session: dict) -> list[dict]:
        return [_public_app(row) for row in self.store.applications_for(applicant_key(session))]

    def _resolve(self, session: dict, message: str) -> tuple[list[str], list[str]]:
        low = (message or "").lower()
        last = list(session.get("last_results") or [])
        problems: list[str] = []
        if re.search(r"\b(all of them|all of these|apply to all|every one of them)\b", low):
            if not last:
                return [], ["no-list"]
            return last, []

        numbers: list[int] = []
        for match in re.finditer(r"(?:#|job|role|number|no\.?)\s*(\d{1,3})\b", low):
            numbers.append(int(match.group(1)))
        bare = re.search(r"\bapply(?:\s+to)?\s+(\d{1,3})\b", low)
        if bare:
            numbers.append(int(bare.group(1)))
        for word, number in _ORDINALS.items():
            if re.search(rf"\b{word}\b", low):
                numbers.append(number)

        ids: list[str] = []
        seen_numbers: set[int] = set()
        for number in numbers:
            if number in seen_numbers:
                continue
            seen_numbers.add(number)
            if number < 1 or number > len(last):
                problems.append(f"bad-index:{number}:{len(last)}")
                continue
            ids.append(last[number - 1])

        for match in re.finditer(r"\b(?:gh|lv|ab)_[a-z0-9_-]+\b", low):
            found = self.store.get_job(match.group(0))
            if found:
                ids.append(found["id"])
            else:
                problems.append(f"bad-id:{match.group(0)}")

        if ids or (problems and numbers):
            return _unique(ids), problems

        query = re.sub(
            r"\b(please|can you|could you|apply|application|applying|to|for|the|a|an|job|role|one|posting|opening|this|that)\b",
            " ",
            low,
        )
        query = re.sub(r"\s+", " ", query).strip(" .?")
        if not query:
            return [], ["unspecified"] if not problems else problems

        hits = _name_hits(query, [self.store.get_job(jid) for jid in last])
        hits = [job for job in hits if job]
        if len(hits) == 1:
            return [hits[0]["id"]], problems
        if len(hits) > 1:
            return [], problems + ["ambiguous-list"]
        # Fall back to the whole dataset only when the company (or title) is unambiguous.
        everywhere = _name_hits(query, self.store.jobs)
        if len(everywhere) == 1:
            return [everywhere[0]["id"]], problems
        if len(everywhere) > 1:
            return [], ["ambiguous-dataset"]
        return [], ["not-found"]


def speak_apply(result: dict, session: dict) -> str:
    lines = []
    for record in result["created"]:
        when = pretty_date(record["applied_date"])
        # "Apply" here is the local log, not the employer's form. Say that once,
        # in the same sentence as the id and date, so the receipt isn't a surprise.
        lines.append(
            f"I did not submit **{record['job_title']}** at **{record['company']}**. "
            f"The posting is real ({record['source_link']}), and that form uses a captcha, "
            f"so I can't send it from here. Saved the link on {when}. Status: not submitted."
        )
    for record in result["duplicates"]:
        when = pretty_date(record["applied_date"])
        title = record.get("job_title") or "that role"
        company = record.get("company") or "that company"
        lines.append(
            f"I already saved **{title}** at **{company}** on {when}. "
            f"Status is still {record.get('status', 'not_submitted')}. It was not submitted."
        )
    for problem in result["problems"]:
        lines.append(_problem_line(problem, session))
    if not lines:
        lines.append("Tell me which role — a number from the list works, like \"apply to job 2\".")
    return "\n\n".join(lines)


def speak_status(rows: list[dict]) -> str:
    if not rows:
        return (
            "Nothing has been submitted. "
            "Ask for a role and I'll keep the live posting link. The company form still has to be finished on their site."
        )
    lines = [f"{len(rows)} {'role' if len(rows) == 1 else 'roles'} saved. None of these were submitted to the company."]
    for index, row in enumerate(rows, start=1):
        when = pretty_date(row["applied_date"])
        lines.append(
            f"{index}. **{row['job_title']}** at **{row['company']}** — {when} — status {row['status']} — `{row['job_id']}`"
        )
    return "\n".join(lines)


def _problem_line(problem: str, session: dict) -> str:
    shown = len(session.get("last_results") or [])
    if problem == "no-list":
        return "I don't have a list on the table yet. Ask me for matches first, then tell me the number."
    if problem == "unspecified":
        return "Which one? A number from the last list is enough — \"apply to job 2\"."
    if problem == "ambiguous-list":
        return "More than one role on the current list fits that. Use the number, like \"apply to job 2\"."
    if problem == "ambiguous-dataset":
        return "That matches several postings. Pull up a short list first, then apply by number so I don't guess."
    if problem == "not-found":
        return "I couldn't tell which posting you meant. Use a number from the list I just showed."
    if problem.startswith("bad-index:"):
        _, number, count = (problem.split(":") + ["0", "0"])[:3]
        if shown == 0:
            return f"Job {number} isn't available — I haven't shown a list in this chat yet."
        return (
            f"Job {number} isn't on the list I just showed. "
            f"That list has {count} {'role' if count == '1' else 'roles'}, numbered from 1."
        )
    if problem.startswith("bad-id:"):
        return f"I don't have a job with id `{problem.split(':', 1)[1]}` in the dataset."
    if problem.startswith("missing:"):
        return "That job id disappeared from the dataset, so I didn't record an application."
    return "I couldn't apply to that one."


def _public_app(row: dict) -> dict:
    return {
        "job_id": row.get("job_id"),
        "applied_date": row.get("applied_date"),
        "status": row.get("status"),
        "job_title": row.get("job_title"),
        "company": row.get("company"),
        "source_link": row.get("source_link"),
    }


def _name_hits(query: str, jobs: list[dict | None]) -> list[dict]:
    hits = []
    for job in jobs:
        if not job:
            continue
        company = (job.get("company") or "").lower()
        title = (job.get("title") or "").lower()
        if query == company or query == title or query in company or (len(query) > 4 and query in title):
            hits.append(job)
    return hits


def _unique(ids: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for job_id in ids:
        if job_id in seen:
            continue
        seen.add(job_id)
        ordered.append(job_id)
    return ordered


def skill_names(skills: list[str]) -> str:
    return ", ".join(skill_label(skill) for skill in skills)
