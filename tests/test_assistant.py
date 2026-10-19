"""Tests for parsing, matching, and the chat turns a reviewer will actually try."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.agents.resume import parse_resume_text
from app.ingest import normalize_ashby
from app.main import create_app
from app.skills import extract_skills
from app.textutil import experience_required, plain_text, years_between
from scripts.make_sample_resume import LINES, build_pdf

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = "\n".join(LINES)
# Tests stay on the phrase rules even if a developer key is loaded.
os.environ.pop("GEMINI_API_KEY", None)


def test_javascript_is_not_java():
    assert extract_skills("JavaScript developer") == ["javascript"]
    both = extract_skills("I write Java and JavaScript")
    assert "java" in both and "javascript" in both


def test_react_native_keeps_react():
    found = set(extract_skills("Built a React Native app"))
    assert "react native" in found
    assert "react" in found


def test_greenhouse_html_is_unescaped():
    text = plain_text("&lt;p&gt;We use Python and PostgreSQL.&lt;/p&gt;")
    assert "Python" in text
    assert "<" not in text
    assert "lt;" not in text


def test_experience_label_skips_age():
    label, years = experience_required("Analyst", "Must be 18 years of age. 3+ years of experience required.")
    assert years == 3
    assert label == "3+ years"


def test_overlapping_jobs_are_not_double_counted():
    # Two roles in the same window should count once.
    today = datetime(2026, 10, 19, tzinfo=timezone.utc)
    total = years_between(
        [((2024, 1), (2026, 1)), ((2024, 6), (2025, 6))],
        today,
    )
    assert total == 2.0


def test_ashby_location_stays_readable():
    job = normalize_ashby(
        {
            "id": "abc",
            "title": "Software Engineer",
            "location": "New York City, NY",
            "secondaryLocations": [
                {"location": "San Francisco, CA", "address": {"postalAddress": {"addressLocality": "San Francisco"}}}
            ],
            "descriptionPlain": "React and Python. 3+ years of experience.",
            "jobUrl": "https://jobs.ashbyhq.com/example/abc",
            "isRemote": False,
        },
        "example",
        "Example",
    )
    assert job is not None
    assert "San Francisco, CA" in job["location"]
    assert "{" not in job["location"]


def test_sample_resume_fields():
    profile = parse_resume_text(SAMPLE, today=datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert profile["name"] == "Alex Rivera"
    assert profile["email"] == "alex.rivera@example.com"
    assert profile["phone"]
    assert profile["designation"] == "Software Engineer"
    assert "react" in profile["skills"]
    assert "typescript" in profile["skills"]
    assert "python" in profile["skills"]
    assert profile["years"] is not None
    assert 2.2 <= float(profile["years"]) <= 3.6
    assert any("Northwind" in (role.get("company") or "") for role in profile["experience"])
    assert any("State University" in line for line in profile["education"])
    assert any("Trailhead" in name for name in profile["projects"])


def _jobs() -> list[dict]:
    titles = [
        ("Frontend Software Engineer", ["react", "typescript", "javascript"], False, "San Francisco", "2+ years", 2),
        ("Software Engineer", ["react", "node.js", "postgresql", "typescript"], True, "Remote - US", "2+ years", 2),
        ("Backend Software Engineer", ["python", "postgresql", "django"], True, "Remote", "3+ years", 3),
        ("Software Engineer", ["react", "typescript", "aws"], True, "Remote - Canada", "1+ years", 1),
        ("Product Designer", ["figma"], False, "New York", "3+ years", 3),
        ("Senior Staff Engineer", ["go", "kubernetes"], True, "Remote", "8+ years", 8),
        ("Software Engineer", ["react", "python", "node.js"], True, "Remote", "2+ years", 2),
        ("Software Engineer", ["typescript", "react", "graphql"], True, "Remote - Europe", "2+ years", 2),
        ("Software Engineer Intern", ["react", "python"], True, "Remote", "Internship", 0),
    ]
    rows = []
    for index, (title, skills, remote, location, label, minimum) in enumerate(titles, start=1):
        rows.append({
            "id": f"gh_example_{index}",
            "title": title,
            "company": f"Example {index}",
            "location": location,
            "experience_required": label,
            "experience_years_min": minimum,
            "skills": skills,
            "description": f"{title} needs {', '.join(skills)}. Location {location}.",
            "source_link": f"https://example.com/jobs/{index}",
            "source": "Greenhouse",
            "remote": remote,
        })
    return rows


@pytest.fixture
def client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    payload = {"generated_at": "2026-10-19T00:00:00+00:00", "jobs": _jobs()}
    (data / "jobs.json").write_text(json.dumps(payload), encoding="utf-8")
    app = create_app(data)
    return TestClient(app), data


def _docx_bytes() -> bytes:
    document = Document()
    for line in LINES:
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_chat_reads_resume_and_recommends(client):
    api, _data = client
    response = api.post(
        "/api/chat",
        data={"message": "", "session_id": ""},
        files={"file": ("alex.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    body = response.json()
    assert response.status_code == 200
    assert "Alex Rivera" in body["reply"]
    assert body["profile"]["designation"] == "Software Engineer"
    assert body["jobs"], body["reply"]
    assert all(job["reason"] for job in body["jobs"])
    # The designer role shouldn't outrank a React engineer for this resume.
    titles = [job["title"] for job in body["jobs"]]
    assert "Product Designer" not in titles


def test_remote_filter_apply_and_duplicate(client):
    api, data = client
    first = api.post(
        "/api/chat",
        data={"message": "show only remote roles"},
        files={"file": ("alex.pdf", build_pdf(LINES), "application/pdf")},
    ).json()
    assert first["jobs"]
    assert all(job["remote"] for job in first["jobs"])
    session_id = first["session_id"]

    applied = api.post("/api/chat", data={"message": "apply to job 1", "session_id": session_id}).json()
    assert "not submit" in applied["reply"].lower()
    assert applied["saved_applications"][0]["status"] == "not_submitted"
    assert applied["saved_applications"][0]["job_id"] == first["jobs"][0]["id"]

    again = api.post("/api/chat", data={"message": "apply to job 1", "session_id": session_id}).json()
    assert "not submitted" in again["reply"].lower()
    stored = json.loads((data / "applications.json").read_text(encoding="utf-8"))
    assert len(stored["applications"]) == 1

    status = api.post("/api/chat", data={"message": "show my applied jobs", "session_id": session_id}).json()
    assert first["jobs"][0]["title"] in status["reply"]
    assert "not submitted" in status["reply"].lower() or "none of these were submitted" in status["reply"].lower()


def test_frontend_request_drops_the_remote_filter(client):
    api, _data = client
    started = api.post(
        "/api/chat",
        data={"message": "show only remote roles"},
        files={"file": ("alex.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()
    assert started["filters"]["remote"] is True
    narrowed = api.post(
        "/api/chat",
        data={"message": "only frontend roles", "session_id": started["session_id"]},
    ).json()
    assert narrowed["filters"]["remote"] is None
    assert narrowed["filters"]["track"] == "frontend"
    assert narrowed["jobs"]
    titles = [job["title"].lower() for job in narrowed["jobs"]]
    assert titles
    assert all("frontend" in title or "front-end" in title or "front end" in title for title in titles)
    assert "remote only" not in narrowed["reply"].lower()


def test_invalid_job_number(client):
    api, _data = client
    started = api.post(
        "/api/chat",
        data={"message": ""},
        files={"file": ("alex.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()
    missed = api.post(
        "/api/chat",
        data={"message": "apply to job 9", "session_id": started["session_id"]},
    ).json()
    assert "isn't on the list" in missed["reply"]
    assert missed["saved_applications"] == []


def test_unreadable_resume(client):
    api, _data = client
    response = api.post(
        "/api/chat",
        data={"message": ""},
        files={"file": ("scan.pdf", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF", "application/pdf")},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "couldn't" in reply or "text" in reply


def test_no_skill_overlap_filter(client):
    api, _data = client
    started = api.post(
        "/api/chat",
        data={"message": ""},
        files={"file": ("alex.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()
    narrowed = api.post(
        "/api/chat",
        data={"message": "jobs needing Figma", "session_id": started["session_id"]},
    ).json()
    # Figma is on the designer role only. It can show up as a stretch, or as an empty set
    # if the filter wipes the list. Either way the reply has to say what happened.
    if narrowed["jobs"]:
        assert all("figma" in " ".join(job["skills"]) for job in narrowed["jobs"])
    else:
        assert "nothing" in narrowed["reply"].lower() or "figma" in narrowed["reply"].lower()


def test_shipped_dataset():
    path = ROOT / "data" / "jobs.json"
    if not path.exists():
        pytest.skip("dataset not built yet")
    raw = json.loads(path.read_text(encoding="utf-8"))
    jobs = raw["jobs"]
    assert 1500 <= len(jobs) <= 2000
    ids = set()
    required = {
        "id", "title", "company", "location", "experience_required",
        "skills", "description", "source_link",
    }
    for job in jobs:
        assert required <= set(job)
        assert job["id"] not in ids
        ids.add(job["id"])
        link = job["source_link"]
        assert link.startswith("http")
        host = link.split("/")[2].lower()
        assert "example.com" not in host
        job_id = job["id"]
        if job_id.startswith("gh_"):
            assert "greenhouse.io" in host or "gh_jid=" in link, link
        elif job_id.startswith("lv_"):
            assert "lever.co" in host, link
        elif job_id.startswith("ab_"):
            assert "ashbyhq.com" in host, link
        else:
            raise AssertionError(job_id)
        assert isinstance(job["skills"], list)
        assert job["title"] and job["company"]
