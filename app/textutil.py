"""Small text helpers used while ingesting jobs and reading resumes."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

_TAG_BREAKS = {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr", "section"}


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip = True
        if tag in _TAG_BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "li", "div", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def plain_text(value: str | None) -> str:
    """Turn an ATS description into readable text.

    Greenhouse often sends the body already escaped (`&lt;p&gt;...&lt;/p&gt;`).
    Strip tags only after unescaping, or the description is a wall of entities.
    """
    if not value:
        return ""
    text = value
    for _ in range(2):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    parser = _HTMLText()
    try:
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def clip(text: str, limit: int = 1400) -> str:
    text = re.sub(r"\s+\n", "\n", text).strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut < int(limit * 0.6):
        cut = limit
    return text[:cut].rstrip(" ,;:-") + "…"


def is_remote(location: str, workplace: str | None = None, flagged: bool | None = None) -> bool:
    if flagged is True:
        return True
    blob = f"{location or ''} {workplace or ''}".lower()
    if any(word in blob for word in ("hybrid", "on-site", "onsite", "on site", "in-office", "in office")):
        return False
    return any(word in blob for word in ("remote", "anywhere", "work from home", "distributed"))


_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# "3+ years", "3-5 years", "at least 4 years". Skip "18 years of age".
_EXP_PATTERNS = [
    re.compile(r"(\d{1,2})\s*\+\s*years?(?!\s+of\s+age)", re.I),
    re.compile(r"(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*years?(?!\s+of\s+age)", re.I),
    re.compile(r"(?:at least|minimum of|minimum)\s+(\d{1,2})\s*years?", re.I),
    re.compile(r"(\d{1,2})\s*years?\s+of\s+experience", re.I),
]


def experience_required(title: str, body: str) -> tuple[str, int | None]:
    """Best-effort seniority label. None means the posting never stated a number."""
    title_l = title.lower()
    if re.search(r"\bintern(ship)?\b", title_l):
        return "Internship", 0
    sample = f"{title}\n{(body or '')[:2500]}"
    ranged = _EXP_PATTERNS[1].search(sample)
    if ranged:
        low = int(ranged.group(1))
        if low <= 20:
            return f"{low}-{int(ranged.group(2))} years", low
    for pattern in (_EXP_PATTERNS[0], _EXP_PATTERNS[2], _EXP_PATTERNS[3]):
        found = pattern.search(sample)
        if found:
            years = int(found.group(1))
            if 0 < years <= 20:
                return f"{years}+ years", years
    if re.search(r"\b(entry[- ]level|new grad|new graduate|junior)\b", title_l):
        return "Entry level", 0
    if re.search(r"\b(senior|staff|principal)\b", title_l):
        return "Senior", 5
    return "Not specified", None


def parse_month_year(token: str) -> tuple[int, int] | None:
    token = token.strip().rstrip(".")
    year_only = re.fullmatch(r"(19|20)\d{2}", token)
    if year_only:
        return int(token), 1
    named = re.fullmatch(r"([A-Za-z]+)\.?\s+((?:19|20)\d{2})", token)
    if named and named.group(1).lower()[:3] in _MONTHS or named.group(1).lower() in _MONTHS:
        month_key = named.group(1).lower().rstrip(".")
        month = _MONTHS.get(month_key) or _MONTHS.get(month_key[:3])
        if month:
            return int(named.group(2)), month
    numeric = re.fullmatch(r"(0?[1-9]|1[0-2])[/-]((?:19|20)\d{2})", token)
    if numeric:
        return int(numeric.group(2)), int(numeric.group(1))
    return None


_RANGE = re.compile(
    r"(?P<start>(?:[A-Za-z]{3,9}\.?\s+)?(?:19|20)\d{2}|(?:0?[1-9]|1[0-2])[/-](?:19|20)\d{2})"
    r"\s*(?:-|–|—|\bto\b)\s*"
    r"(?P<end>present|current|now|(?:[A-Za-z]{3,9}\.?\s+)?(?:19|20)\d{2}|(?:0?[1-9]|1[0-2])[/-](?:19|20)\d{2})",
    re.IGNORECASE,
)


def find_date_ranges(text: str) -> list[re.Match[str]]:
    return list(_RANGE.finditer(text))


def years_between(
    ranges: list[tuple[tuple[int, int], tuple[int, int]]],
    today: datetime | None = None,
) -> float | None:
    """Total years, with overlapping jobs counted once.

    Two concurrent roles in the same two years are not four years of experience.
    """
    if not ranges:
        return None
    today = today or datetime.now(timezone.utc)
    intervals: list[list[float]] = []
    for start, end in ranges:
        start_n = start[0] + (start[1] - 1) / 12
        end_n = end[0] + (end[1] - 1) / 12
        if end_n < start_n:
            continue
        # Ignore a range that claims someone started 60 years ago; that's a parse miss.
        if start_n < today.year - 60:
            continue
        intervals.append([start_n, end_n])
    if not intervals:
        return None
    intervals.sort()
    merged = [intervals[0]]
    for start_n, end_n in intervals[1:]:
        if start_n <= merged[-1][1] + 0.09:
            merged[-1][1] = max(merged[-1][1], end_n)
        else:
            merged.append([start_n, end_n])
    total = sum(end_n - start_n for start_n, end_n in merged)
    return round(total, 1)


def pretty_date(iso_date: str) -> str:
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def stated_years(text: str) -> float | None:
    found = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*years?\s+of\s+experience", text, re.I)
    if not found:
        found = re.search(r"experience\s*[:\-]\s*(\d+(?:\.\d+)?)\s*\+?\s*years?", text, re.I)
    if not found:
        return None
    value = float(found.group(1))
    if value > 60:
        return None
    return value
