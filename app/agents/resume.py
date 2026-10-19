"""Read a PDF or DOCX resume into the fields the chat shows back.

This is deliberately heuristic. A scanned image has no text layer, and we'd
rather say so than invent a name.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import BytesIO

from app.skills import extract_skills, skill_label
from app.textutil import find_date_ranges, parse_month_year, stated_years, years_between

MAX_PAGES = 15
MIN_LETTERS = 40

HEADER_ALIASES = {
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment history",
        "work history",
        "employment",
    },
    "education": {"education", "academic background", "academics"},
    "skills": {
        "skills",
        "technical skills",
        "core competencies",
        "technologies",
        "tech stack",
    },
    "projects": {
        "projects",
        "personal projects",
        "selected projects",
        "side projects",
    },
    "summary": {
        "summary",
        "professional summary",
        "profile",
        "about me",
        "objective",
    },
}

ROLE = re.compile(
    r"\b(engineer|developer|designer|manager|analyst|scientist|intern|consultant|"
    r"architect|specialist|director|researcher|administrator|recruiter|marketer|"
    r"writer|accountant|programmer|sde|sdet|devops|full[\s-]?stack|frontend|"
    r"front[\s-]?end|backend|back[\s-]?end|data|product|qa|tester)\b",
    re.I,
)
EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE = re.compile(r"(?:\+\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}")
LINK = re.compile(r"(https?://[^\s|,]+|(?:linkedin|github)\.com/[^\s|,]+)", re.I)
BULLET = re.compile(r"^[\s]*[•\-\*–—●▪]\s*")


class ResumeReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def extract_upload(filename: str, data: bytes) -> str:
    kind = _kind(filename, data)
    if kind == ".pdf":
        return _pdf_text(data)
    if kind == ".docx":
        return _docx_text(data)
    raise ResumeReadError(
        "I can read PDF and DOCX resumes. Save it as one of those and send it again."
    )


def _kind(filename: str, data: bytes) -> str:
    name = (filename or "").lower().strip()
    if name.endswith(".pdf") or data.startswith(b"%PDF"):
        return ".pdf"
    if name.endswith(".docx") or data.startswith(b"PK"):
        # A zip that isn't a docx fails later with the unreadable message.
        if name.endswith(".docx") or name.endswith(".pdf"):
            return ".docx" if name.endswith(".docx") else ".pdf"
        if data.startswith(b"PK"):
            return ".docx"
    suffix = ""
    if "." in name:
        suffix = name[name.rfind("."):]
    return suffix


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ResumeReadError("PDF support isn't installed on the server.") from exc
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ResumeReadError(
                    "That PDF is password-protected. Export a copy without a password and send that."
                ) from exc
        pages = []
        for page in list(reader.pages)[:MAX_PAGES]:
            pages.append(page.extract_text() or "")
    except ResumeReadError:
        raise
    except Exception as exc:
        raise ResumeReadError(
            "I couldn't read that PDF. If it's a scan or a photo, export a text-based PDF or a DOCX and try again."
        ) from exc
    return "\n".join(pages)


def _docx_text(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ResumeReadError("DOCX support isn't installed on the server.") from exc
    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise ResumeReadError(
            "I couldn't open that DOCX. It may be corrupted, or it might be an old .doc file renamed to .docx."
        ) from exc
    parts = [p.text for p in document.paragraphs]
    # A lot of resumes hide the contact row inside a table. Paragraphs alone miss it.
    for table in document.tables:
        for row in table.rows:
            cells = []
            for cell in row.cells:
                value = cell.text.strip()
                if value and value not in cells:
                    cells.append(value)
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def parse_resume_text(text: str, today: datetime | None = None) -> dict:
    letters = re.sub(r"[^A-Za-z]", "", text or "")
    if len(letters) < MIN_LETTERS:
        raise ResumeReadError(
            "I couldn't find real text in that file. Scanned PDFs and photos don't have a text layer — export a text-based PDF or DOCX and send it again."
        )
    today = today or datetime.now(timezone.utc)
    lines = [_clean_line(line) for line in text.splitlines()]
    sections = _split_sections(lines)
    header = sections.get("header", [])
    email = _first(EMAIL, text)
    phone = _first(PHONE, text)
    links = _links(text)
    name = _name(header) or _name(lines[:8])
    designation = _designation(header) or _designation(sections.get("summary", [])[:3])
    skills = _collect_skills(text, sections.get("skills", []))
    experience, ranges = _experience(sections.get("experience") or lines, today)
    if not designation and experience:
        designation = experience[0].get("title")
    computed = years_between(ranges, today)
    stated = stated_years(text)
    years, year_note = _pick_years(computed, stated)
    education = _education(sections.get("education", []))
    projects = _projects(sections.get("projects", []))
    warnings = []
    if not email:
        warnings.append("I didn't find an email.")
    if not phone:
        warnings.append("I didn't find a phone number.")
    if not skills:
        warnings.append("I didn't catch a skills list. Tell me what you use, for example \"I know React and Python\".")
    if year_note:
        warnings.append(year_note)
    useful = [
        bool(name),
        bool(email),
        bool(skills),
        bool(designation),
        bool(education),
        bool(experience),
    ]
    if sum(useful) < 2:
        raise ResumeReadError(
            "I got some text out of that file, but it doesn't look like a resume. Check that you uploaded the right document."
        )
    return {
        "name": name,
        "email": email,
        "phone": phone,
        "links": links,
        "designation": designation,
        "skills": skills,
        "years": years,
        "experience": experience[:5],
        "education": education[:4],
        "projects": projects[:5],
        "warnings": warnings,
    }


def profile_summary(profile: dict) -> str:
    """Plain-text version of the parse, for the chat transcript."""
    name = profile.get("name") or "there"
    lines = [f"I read {name}'s resume. Here's what I kept."]
    lines.append(f"Name: {profile.get('name') or 'Not found'}")
    contact = [bit for bit in (profile.get("email"), profile.get("phone"), *(profile.get("links") or [])) if bit]
    lines.append("Contact: " + (" · ".join(contact) if contact else "Not found"))
    lines.append(f"Designation: {profile.get('designation') or 'Not found'}")
    lines.append("Experience: " + _experience_line(profile))
    skills = profile.get("skills") or []
    if skills:
        lines.append("Skills: " + ", ".join(skill_label(s) for s in skills[:16]))
    else:
        lines.append("Skills: Not found")
    education = profile.get("education") or []
    lines.append("Education: " + ("; ".join(education) if education else "Not found"))
    projects = profile.get("projects") or []
    lines.append("Projects: " + ("; ".join(projects) if projects else "Not found"))
    warnings = profile.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append(" ".join(warnings))
    lines.append("")
    lines.append('If a line is wrong, correct me — for example "my title is Data Analyst" or "I have 4 years".')
    return "\n".join(lines)


def _experience_line(profile: dict) -> str:
    roles = []
    for item in profile.get("experience") or []:
        title = item.get("title") or "Role"
        company = item.get("company")
        dates = item.get("dates")
        bit = title
        if company:
            bit += f" at {company}"
        if dates:
            bit += f" ({dates})"
        roles.append(bit)
    years = profile.get("years")
    year_bit = None
    if isinstance(years, (int, float)):
        number = int(years) if float(years).is_integer() else years
        unit = "year" if number == 1 else "years"
        year_bit = f"about {number} {unit}"
    if roles and year_bit:
        return f"{year_bit} — " + "; ".join(roles)
    if roles:
        return "; ".join(roles)
    if year_bit:
        return f"{year_bit} (I couldn't split out individual roles)"
    return "Not found"


def _clean_line(line: str) -> str:
    line = line.replace("\xa0", " ").replace("\u200b", "")
    line = re.sub(r"[ \t]+", " ", line).strip()
    return line


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in lines:
        key = _header_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _header_key(line: str) -> str | None:
    if not line or len(line) > 36:
        return None
    cleaned = re.sub(r"[^a-z ]", "", line.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    for key, names in HEADER_ALIASES.items():
        if cleaned in names:
            return key
    return None


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    found = pattern.search(text or "")
    if not found:
        return None
    return found.group(0).strip()


def _links(text: str) -> list[str]:
    seen: list[str] = []
    for match in LINK.finditer(text or ""):
        link = match.group(0).rstrip(").,;")
        if link not in seen:
            seen.append(link)
    return seen[:4]


def _looks_like_name(line: str) -> bool:
    if not line or len(line) > 48 or any(ch.isdigit() for ch in line):
        return False
    # "Software Engineer" is two capitalised words, same shape as a name.
    if ROLE.search(line):
        return False
    if "@" in line or "http" in line.lower() or "|" in line:
        return False
    if _header_key(line):
        return False
    parts = line.replace(",", " ").split()
    if not 2 <= len(parts) <= 4:
        return False
    word = re.compile(r"[A-Za-z][A-Za-z'’.\-]{0,24}")
    return all(word.fullmatch(part) for part in parts)


def _name(lines: list[str]) -> str | None:
    for line in lines:
        if not line.strip():
            continue
        if EMAIL.search(line) or PHONE.search(line):
            continue
        candidate = line.strip()
        if _looks_like_name(candidate):
            return candidate.title() if candidate.isupper() else candidate
        # The first non-empty line of many resumes is the name even in mixed case.
        if _looks_like_name(candidate.title()):
            return candidate.title() if candidate.islower() else candidate
    return None


def _designation(lines: list[str]) -> str | None:
    for line in lines:
        cleaned = line.strip()
        if not cleaned or len(cleaned) > 80:
            continue
        if EMAIL.search(cleaned) or PHONE.search(cleaned) or "@" in cleaned:
            continue
        if _header_key(cleaned) or _looks_like_name(cleaned):
            continue
        if ROLE.search(cleaned):
            return cleaned.strip(" |-")
    return None


def _collect_skills(text: str, skill_lines: list[str]) -> list[str]:
    listed: list[str] = []
    seen: set[str] = set()
    # Skills written out by the person come first, then anything we recognize in the body.
    blob = "\n".join(skill_lines)
    for skill in extract_skills(blob, limit=24) + extract_skills(text, limit=24):
        if skill in seen:
            continue
        seen.add(skill)
        listed.append(skill)
    if listed:
        return listed[:24]
    # Free-form skill rows ("Stakeholder management, Roadmapping") still count.
    for line in skill_lines:
        for bit in re.split(r"[,|/•·]", line):
            bit = BULLET.sub("", bit).strip(" -–")
            words = bit.split()
            if 1 <= len(words) <= 5 and 2 <= len(bit) <= 40 and bit.lower() not in seen:
                seen.add(bit.lower())
                listed.append(bit)
    return listed[:24]


def _experience(lines: list[str], today: datetime) -> tuple[list[dict], list[tuple]]:
    roles: list[dict] = []
    ranges: list[tuple] = []
    # Work on the joined section so a date range split across spaces still matches,
    # but keep line indexes by scanning line by line.
    for index, line in enumerate(lines):
        match = None
        for found in find_date_ranges(line):
            match = found
            break
        if not match and index + 1 < len(lines):
            # "Apr 2025" on one line and "- Present" on the next is uncommon; skip.
            match = None
        if not match:
            continue
        start = parse_month_year(match.group("start"))
        end_token = match.group("end")
        if end_token.lower() in {"present", "current", "now"}:
            end = (today.year, today.month)
        else:
            end = parse_month_year(end_token)
        if not start or not end:
            continue
        ranges.append((start, end))
        context = _previous_lines(lines, index)
        title, company = _title_and_company(context, line, match.group(0))
        if not title and not company:
            continue
        roles.append({
            "title": title,
            "company": company,
            "dates": re.sub(r"\s+", " ", match.group(0)).strip(),
        })
    # De-dupe identical rows caused by the date appearing twice.
    unique: list[dict] = []
    seen: set[tuple] = set()
    for role in roles:
        key = (role.get("title"), role.get("company"), role.get("dates"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(role)
    return unique[:6], ranges


def _previous_lines(lines: list[str], index: int) -> list[str]:
    found: list[str] = []
    cursor = index - 1
    while cursor >= 0 and len(found) < 3:
        item = lines[cursor].strip()
        cursor -= 1
        if not item:
            if found:
                break
            continue
        if _header_key(item):
            break
        if len(item) > 90:
            continue
        found.append(item)
    return found


def _title_and_company(context: list[str], line: str, dates: str) -> tuple[str | None, str | None]:
    leftover = line.replace(dates, " ").strip(" |-–—")
    candidates = []
    if leftover and not find_date_ranges(leftover):
        candidates.append(leftover)
    candidates.extend(context)
    if not candidates:
        return None, None
    title = next((item for item in candidates if ROLE.search(item) and not find_date_ranges(item)), None)
    company = next((item for item in candidates if item != title), None)
    if title is None:
        title = candidates[0]
        company = candidates[1] if len(candidates) > 1 else company
    if company and ROLE.search(company) and title and not ROLE.search(title):
        title, company = company, title
    if title:
        title = title.strip(" |-")[:80]
    if company:
        company = company.strip(" |-")[:80]
        if company == title:
            company = None
    return title, company


def _pick_years(computed: float | None, stated: float | None) -> tuple[int | float | None, str | None]:
    if computed is None and stated is None:
        return None, None
    if computed is None:
        return _tidy(stated), None
    if stated is None:
        return _tidy(computed), None
    if abs(stated - computed) >= 1.5:
        # Trust the larger number. Date lines get missed more often than the summary does.
        chosen = max(stated, computed)
        return _tidy(chosen), (
            f"The summary says { _num(stated) } years, while the dates I could read add up to about { _num(computed) }. I kept { _num(chosen) }."
        )
    return _tidy(computed), None


def _tidy(value: float | None) -> int | float | None:
    if value is None:
        return None
    if abs(value - round(value)) < 0.05:
        return int(round(value))
    return round(value, 1)


def _num(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return str(round(value, 1))


def _education(lines: list[str]) -> list[str]:
    kept: list[str] = []
    pattern = re.compile(
        r"\b(bachelor|master|ph\.?d|mba|b\.?s\.?|m\.?s\.?|b\.?tech|m\.?tech|b\.?e\.?|"
        r"b\.?a\.?|associate|university|college|institute|school|degree)\b",
        re.I,
    )
    for line in lines:
        cleaned = BULLET.sub("", line).strip()
        if len(cleaned) < 6:
            continue
        if pattern.search(cleaned):
            kept.append(cleaned[:140])
    if kept:
        return kept
    for line in lines:
        cleaned = BULLET.sub("", line).strip()
        if len(cleaned) >= 8:
            kept.append(cleaned[:140])
        if len(kept) >= 3:
            break
    return kept


def _projects(lines: list[str]) -> list[str]:
    names: list[str] = []
    for line in lines:
        cleaned = BULLET.sub("", line).strip()
        if len(cleaned) < 3:
            continue
        name = re.split(r"\s+[\-|–—:]\s+|\s+[|]\s+", cleaned)[0].strip()
        if 2 <= len(name) <= 80:
            names.append(name)
    return names
