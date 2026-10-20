"""Resume edits grounded in the roles just shown. No invented employers or metrics."""

from __future__ import annotations

from collections import Counter

from app.skills import skill_label


def suggest_changes(profile: dict, jobs: list[dict]) -> str:
    profile = profile or {}
    jobs = [job for job in jobs if job]
    if not jobs:
        return (
            "Show me a few roles first, then ask again. "
            "I'll tell you what to change on the resume for those specific postings."
        )
    owned = {str(skill).lower() for skill in (profile.get("skills") or [])}
    missing: Counter[str] = Counter()
    for job in jobs[:5]:
        for skill in job.get("skills") or []:
            key = str(skill).lower()
            if key and key not in owned:
                missing[key] += 1
    focus = jobs[0]
    title = focus.get("title") or "that role"
    company = focus.get("company") or "that company"
    designation = (profile.get("designation") or "").strip()
    lines = [f"If you're aiming at **{title}** at **{company}**, I'd change the resume like this:"]
    gaps = [skill_label(skill) for skill, _count in missing.most_common(3)]
    if gaps:
        lines.append(
            "- These postings ask for "
            + ", ".join(gaps)
            + ". Add a bullet only where you've actually used the tool, and put the result in the same line."
        )
    else:
        lines.append(
            "- The skills already overlap. Don't add a new tool list — rewrite the top bullets so the same skills show a result, not just the name of the tool."
        )
    if designation and designation.lower() not in title.lower() and title.lower() not in designation.lower():
        lines.append(
            f"- Your headline says **{designation}**. If this is the work you want, use **{title}** (or the closest honest version) at the top."
        )
    else:
        lines.append("- Keep the headline, and make the first bullet under it match the first responsibility in this posting.")
    if not profile.get("experience"):
        lines.append("- Add one role with dates. A title with no timeline is hard for a recruiter to trust.")
    else:
        lines.append("- Lead each role with what changed — shipped, reduced, grew — instead of a list of duties.")
    return "\n".join(lines)
