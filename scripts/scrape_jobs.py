"""Pull 1,500–2,000 real postings into data/jobs.json.

Board addresses come from a public directory of ATS slugs. The jobs themselves
are read from each employer's own job-board API — Greenhouse, Lever, and Ashby,
the feeds behind their public careers pages. Nothing here logs into a site or
walks a page that asks you not to.

Run from the repo root:

    python scripts/scrape_jobs.py
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingest import normalize_ashby, normalize_greenhouse, normalize_lever  # noqa: E402

USER_AGENT = "JobChat/1.0"
DIRECTORIES = {
    "greenhouse": "https://kalebconfer-sys.github.io/job-board-directory/greenhouse.csv",
    "ashby": "https://kalebconfer-sys.github.io/job-board-directory/ashby.csv",
    "lever": "https://kalebconfer-sys.github.io/job-board-directory/lever.csv",
}

# Used only when the directory file can't be downloaded. Not enough on its
# own to hit 1,500 — the script will say so and exit.
FALLBACK = {
    "greenhouse": [
        "gitlab", "discord", "cloudflare", "coinbase", "robinhood", "plaid",
        "brex", "ramp", "doordash", "lyft", "reddit", "pinterest", "dropbox",
        "asana", "affirm", "chime", "gusto", "rippling", "duolingo", "grammarly",
        "hubspot", "intercom", "zapier", "mongodb", "twilio", "pagerduty",
        "airtable", "databricks", "okta", "fastly", "sentry", "fivetran",
        "calendly", "algolia", "confluent", "snyk", "hashicorp", "instacart",
    ],
    "ashby": ["notion", "ramp", "openai", "linear", "vercel"],
    "lever": ["spotify", "netflix", "palantir"],
}


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/csv, */*"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 500, 502, 503) or attempt == 2:
                raise
        except (TimeoutError, urllib.error.URLError, ConnectionError) as exc:
            last_error = exc
            if attempt == 2:
                raise
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def fetch_json(url: str):
    return json.loads(fetch_bytes(url).decode("utf-8"))


def load_directory(url: str) -> list[dict]:
    import csv
    from io import StringIO

    raw = fetch_bytes(url, timeout=60).decode("utf-8", errors="replace")
    return list(csv.DictReader(StringIO(raw)))


def eligible(rows: list[dict], low: int, high: int) -> list[dict]:
    picked = []
    for row in rows:
        token = (row.get("token") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,48}", token):
            continue
        if token.isdigit():
            continue
        try:
            count = int(float(row.get("open_roles") or 0))
        except ValueError:
            continue
        if not low <= count <= high:
            continue
        picked.append({
            "token": token,
            "company": (row.get("company") or token).strip() or token,
            "open_roles": count,
        })
    random.Random(19).shuffle(picked)
    return picked


def greenhouse_jobs(board: dict, per_board: int) -> list[dict]:
    payload = fetch_json(
        f"https://boards-api.greenhouse.io/v1/boards/{board['token']}/jobs?content=true"
    )
    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    stamped = []
    for raw in rows:
        job = normalize_greenhouse(raw, board["token"])
        if job:
            stamped.append((str(raw.get("updated_at") or ""), job))
    stamped.sort(key=lambda item: item[0], reverse=True)
    return [job for _, job in stamped[:per_board]]


def lever_jobs(board: dict, per_board: int) -> list[dict]:
    urls = [
        f"https://api.lever.co/v0/postings/{board['token']}?mode=json",
        f"https://api.eu.lever.co/v0/postings/{board['token']}?mode=json",
    ]
    payload = None
    last_error: Exception | None = None
    for url in urls:
        try:
            payload = fetch_json(url)
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                continue
            raise
    if payload is None:
        raise last_error or RuntimeError("lever board missing")
    if not isinstance(payload, list):
        return []
    stamped = []
    for raw in payload:
        job = normalize_lever(raw, board["token"], board["company"])
        if job:
            stamped.append((str(raw.get("createdAt") or ""), job))
    stamped.sort(key=lambda item: item[0], reverse=True)
    return [job for _, job in stamped[:per_board]]


def ashby_jobs(board: dict, per_board: int) -> list[dict]:
    payload = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board['token']}")
    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    stamped = []
    for raw in rows:
        if isinstance(raw, dict) and raw.get("isListed") is False:
            continue
        job = normalize_ashby(raw, board["token"], board["company"])
        if job:
            stamped.append((str(raw.get("publishedAt") or ""), job))
    stamped.sort(key=lambda item: item[0], reverse=True)
    return [job for _, job in stamped[:per_board]]


FETCHERS = {
    "greenhouse": greenhouse_jobs,
    "lever": lever_jobs,
    "ashby": ashby_jobs,
}


def gather(source: str, boards: list[dict], per_board: int, target: int, workers: int) -> list[dict]:
    if not boards:
        return []
    found: list[dict] = []
    fetcher = FETCHERS[source]
    print(f"{source}: {len(boards)} boards, aiming for {target}", flush=True)

    def run(board: dict) -> list[dict]:
        try:
            jobs = fetcher(board, per_board)
        except Exception as exc:
            print(f"  skip {source}/{board['token']}: {exc.__class__.__name__}", flush=True)
            return []
        print(f"  {board['token']}: {len(jobs)}", flush=True)
        return jobs

    # A handful at a time. These are public boards, not something to hammer.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = []
        for board in boards:
            pending.append(pool.submit(run, board))
            if len(pending) >= workers:
                found.extend(_drain(pending))
                pending = []
                if len(_dedupe(found)) >= target:
                    break
        if pending and len(_dedupe(found)) < target:
            found.extend(_drain(pending))
    unique = _dedupe(found)
    print(f"{source}: kept {len(unique)}", flush=True)
    return unique[:target]


def _drain(futures) -> list[dict]:
    rows: list[dict] = []
    for future in as_completed(futures):
        rows.extend(future.result())
    return rows


def _dedupe(jobs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    kept = []
    for job in jobs:
        link = (job.get("source_link") or "").split("?")[0].rstrip("/").lower()
        key = link or job["id"]
        title_key = f"{job['company'].casefold()}|{job['title'].casefold()}|{job['location'].casefold()}"
        if key in seen or title_key in seen:
            continue
        seen.add(key)
        seen.add(title_key)
        kept.append(job)
    return kept


def boards_for(source: str, low: int, high: int, limit: int) -> list[dict]:
    try:
        rows = load_directory(DIRECTORIES[source])
    except Exception as exc:
        print(f"directory for {source} failed ({exc}). using the short fallback list.", flush=True)
        return [{"token": token, "company": token, "open_roles": 0} for token in FALLBACK[source]]
    chosen = eligible(rows, low, high)
    if len(chosen) < max(8, limit // 4):
        chosen = eligible(rows, 3, max(high * 3, 120))
    return chosen[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build data/jobs.json from public ATS job boards.")
    parser.add_argument("--target", type=int, default=1850)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "jobs.json")
    parser.add_argument("--per-board", type=int, default=26)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--allow-short", action="store_true")
    args = parser.parse_args()
    target = max(1, min(args.target, 2000))

    # Greenhouse carries most of the volume. Lever and Ashby are there so the
    # dataset isn't a single vendor's shape of "a job".
    greenhouse = gather(
        "greenhouse",
        boards_for("greenhouse", 8, 40, 140),
        args.per_board,
        target=min(1600, target),
        workers=args.workers,
    )
    remaining = max(target - len(greenhouse), 0)
    ashby = gather(
        "ashby",
        boards_for("ashby", 6, 30, 40),
        min(args.per_board, 20),
        target=min(250, remaining),
        workers=args.workers,
    )
    remaining = max(target - len(greenhouse) - len(ashby), 0)
    lever = gather(
        "lever",
        boards_for("lever", 5, 60, 30),
        min(args.per_board, 20),
        target=min(200, remaining) or 120,
        workers=args.workers,
    )
    jobs = _dedupe(greenhouse + ashby + lever)
    if len(jobs) > 2000:
        jobs = jobs[:2000]
    jobs.sort(key=lambda job: (job["company"].lower(), job["title"].lower(), job["id"]))
    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "count": len(jobs),
        "sources": dict(Counter(job["source"] for job in jobs)),
        "note": (
            "Real postings from public Greenhouse, Lever, and Ashby job-board APIs. "
            "Descriptions are plain-text excerpts; source_link is the original posting."
        ),
        "jobs": jobs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(jobs)} jobs to {args.out} ({payload['sources']})", flush=True)
    if len(jobs) < 1500 and not args.allow_short:
        print("expected at least 1500 jobs. Re-run, or pass --allow-short while debugging.", flush=True)
        return 1
    if len(jobs) > 2000:
        print("refused to keep more than 2000 jobs.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
