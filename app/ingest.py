"""Turn a raw ATS payload into the job record the chat actually stores.

The scraper does the HTTP. This module stays pure so a bad posting can be
tested without hitting the network.
"""

from __future__ import annotations

import re

from app.skills import extract_skills
from app.textutil import clip, experience_required, is_remote, plain_text

EXCERPT = 1400


def _company_label(name: str, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    # Keep the employer's spelling ("GitLab") when the feed sends one.
    # Prettify the board token only when that's all we were given.
    token_only = cleaned.casefold() == fallback.casefold() and cleaned == fallback
    if cleaned and not token_only:
        return cleaned
    words = re.split(r"[-_]+", fallback)
    pretty = " ".join(word.capitalize() for word in words if word)
    return pretty or "Unknown company"


def _place_bits(value) -> list[str]:
    """Ashby sometimes sends a city string, and sometimes a postal-address object."""
    if value is None:
        return []
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip(" ;")
        return [text] if text else []
    if isinstance(value, list):
        bits: list[str] = []
        for item in value:
            for bit in _place_bits(item):
                if bit not in bits:
                    bits.append(bit)
        return bits
    if isinstance(value, dict):
        named = value.get("location") or value.get("name")
        if isinstance(named, str) and named.strip():
            return _place_bits(named)
        address = value.get("address") or value.get("postalAddress") or {}
        postal = address.get("postalAddress") if isinstance(address, dict) else None
        postal = postal if isinstance(postal, dict) else address if isinstance(address, dict) else {}
        locality = postal.get("addressLocality") if isinstance(postal, dict) else None
        region = postal.get("addressRegion") if isinstance(postal, dict) else None
        bits = [str(bit).strip() for bit in (locality, region) if bit]
        return [", ".join(bits)] if bits else []
    return []


def _finish(
    *,
    job_id: str,
    title: str,
    company: str,
    location: str,
    body: str,
    source_link: str,
    source: str,
    remote: bool,
) -> dict | None:
    title = re.sub(r"\s+", " ", (title or "").strip())
    source_link = (source_link or "").strip()
    if not title or not source_link:
        return None
    full = plain_text(body)
    label, years_min = experience_required(title, full)
    skills = extract_skills(f"{title}\n{full}", limit=12)
    places = _place_bits(location)
    location = "; ".join(places) if places else "Unspecified"
    if len(location) > 160:
        location = location[:157].rstrip("; ") + "…"
    return {
        "id": job_id,
        "title": title,
        "company": company or "Unknown company",
        "location": location,
        "experience_required": label,
        "experience_years_min": years_min,
        "skills": skills,
        "description": clip(full, EXCERPT) if full else "Description was not included in the source feed.",
        "source_link": source_link,
        "source": source,
        "remote": remote,
    }


def normalize_greenhouse(raw: dict, token: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    loc = raw.get("location") or {}
    location = loc.get("name") if isinstance(loc, dict) else str(loc or "")
    if not location:
        offices = raw.get("offices") or []
        names = [o.get("name", "") for o in offices if isinstance(o, dict)]
        location = ", ".join(n for n in names if n)
    company = _company_label(str(raw.get("company_name") or ""), token)
    return _finish(
        job_id=f"gh_{token}_{raw.get('id')}",
        title=str(raw.get("title") or ""),
        company=company,
        location=location,
        body=str(raw.get("content") or ""),
        source_link=str(raw.get("absolute_url") or ""),
        source="Greenhouse",
        remote=is_remote(location),
    )


def normalize_lever(raw: dict, token: str, company: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    categories = raw.get("categories") or {}
    location = ""
    if isinstance(categories, dict):
        all_locations = categories.get("allLocations") or []
        if isinstance(all_locations, list) and all_locations:
            location = ", ".join(str(item) for item in all_locations if item)
        else:
            location = str(categories.get("location") or "")
    workplace = str(raw.get("workplaceType") or "")
    chunks = [str(raw.get("descriptionPlain") or raw.get("descriptionBodyPlain") or "")]
    for block in raw.get("lists") or []:
        if isinstance(block, dict):
            chunks.append(str(block.get("text") or ""))
            chunks.append(str(block.get("content") or ""))
    return _finish(
        job_id=f"lv_{token}_{raw.get('id')}",
        title=str(raw.get("text") or ""),
        company=_company_label(company, token),
        location=location,
        body="\n".join(chunks),
        source_link=str(raw.get("hostedUrl") or raw.get("applyUrl") or ""),
        source="Lever",
        remote=is_remote(location, workplace),
    )


def normalize_ashby(raw: dict, token: str, company: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    places = _place_bits(raw.get("location"))
    for extra in _place_bits(raw.get("secondaryLocations")):
        if extra not in places:
            places.append(extra)
    location = "; ".join(places)
    workplace = str(raw.get("workplaceType") or "")
    flagged = raw.get("isRemote")
    remote_flag = flagged if isinstance(flagged, bool) else None
    return _finish(
        job_id=f"ab_{token}_{raw.get('id')}",
        title=str(raw.get("title") or ""),
        company=_company_label(company, token),
        location=location,
        body=str(raw.get("descriptionPlain") or raw.get("descriptionHtml") or ""),
        source_link=str(raw.get("jobUrl") or raw.get("applyUrl") or ""),
        source="Ashby",
        remote=is_remote(location, workplace, remote_flag),
    )
