#!/usr/bin/env python3
"""Safely refresh public World Football Elo Ratings TSV inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from urllib.parse import quote
from urllib.request import Request, urlopen

from ledger import canonical, read_successors


REFERENCE_FILES = (
    "World.tsv",
    "teams.tsv",
    "en.teams.tsv",
    "en.tournaments.tsv",
    "tournaments.tsv",
    "menu.tsv",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("source"))
    parser.add_argument("--base-url", default="https://www.eloratings.net")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--full-if-sunday", action="store_true")
    parser.add_argument("--allow-large-rewrite", action="store_true")
    parser.add_argument("--rate", type=float, default=2.0, help="Maximum requests/second")
    return parser.parse_args()


class PublicTsvClient:
    def __init__(self, rate: float) -> None:
        self.interval = 1.0 / rate if rate > 0 else 0.0
        self.last_request = 0.0
        self.user_agent = (
            "NetworkFootballEloPages/1.0 "
            f"(+https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'scheduled-static-site')})"
        )
        try:
            from curl_cffi import requests as curl_requests

            self.session = curl_requests.Session(impersonate="chrome124")
        except ImportError:
            self.session = None

    def get(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(4):
            elapsed = time.monotonic() - self.last_request
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_request = time.monotonic()
            try:
                if self.session is not None:
                    response = self.session.get(
                        url,
                        timeout=45,
                        headers={"User-Agent": self.user_agent, "Accept": "text/tab-separated-values,*/*"},
                    )
                    if response.status_code != 200:
                        raise RuntimeError(f"HTTP {response.status_code} for {url}")
                    text = response.text
                else:
                    request = Request(url, headers={"User-Agent": self.user_agent})
                    with urlopen(request, timeout=45) as response:
                        text = response.read().decode("utf-8")
                if not text.strip():
                    raise RuntimeError(f"Empty response from {url}")
                return text
            except Exception as error:  # network failures are retried, then fail closed
                last_error = error
                if attempt < 3:
                    time.sleep(2**attempt)
        raise RuntimeError(f"Unable to fetch {url}: {last_error}") from last_error


def normalise_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed.casefold() if character.isalnum())


def validate_world(text: str) -> list[list[str]]:
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    if len(rows) < 150:
        raise ValueError(f"World.tsv unexpectedly has only {len(rows)} rows")
    if any(len(row) != 31 for row in rows):
        bad = next(len(row) for row in rows if len(row) != 31)
        raise ValueError(f"World.tsv schema changed: expected 31 fields, saw {bad}")
    for row in rows:
        int(row[1])
        int(row[3])
        if not row[2].strip():
            raise ValueError("World.tsv contains a blank country")
    return rows


def validate_reference(name: str, text: str) -> None:
    lines = [line for line in text.splitlines() if line.strip()]
    minimum = 100 if name in {"en.teams.tsv", "en.tournaments.tsv", "menu.tsv"} else 20
    if len(lines) < minimum:
        raise ValueError(f"{name} unexpectedly has only {len(lines)} rows")
    if any("\t" not in line for line in lines):
        raise ValueError(f"{name} contains a non-TSV row")


def validate_team_page(text: str, slug: str) -> int:
    rows = [line for line in text.splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"{slug}.tsv is empty")
    for line_number, line in enumerate(rows, start=1):
        fields = line.split("\t")
        if len(fields) != 16:
            raise ValueError(
                f"{slug}.tsv:{line_number} has {len(fields)} fields instead of 16"
            )
        int(fields[0])
        int(fields[5])
        int(fields[6])
        int(fields[9])
        int(fields[10])
        int(fields[11])
    return len(rows)


def parse_name_codes(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0] and not fields[0].endswith("_loc"):
            for name in fields[1:]:
                if name:
                    result.setdefault(normalise_name(name), fields[0])
    return result


def latest_official_rating(path: Path, team: str, successors: dict[str, str]) -> int | None:
    latest: tuple[int, int] | None = None
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 16:
            return None
        day = int(fields[0]) * 400 + int(fields[1]) * 32 + int(fields[2])
        first, second = canonical(fields[3], successors), canonical(fields[4], successors)
        if first == team:
            candidate = (day, int(fields[10]))
        elif second == team:
            candidate = (day, int(fields[11]))
        else:
            continue
        if latest is None or candidate[0] >= latest[0]:
            latest = candidate
    return None if latest is None else latest[1]


def slug_from_country(country: str, existing: dict[str, str]) -> str:
    normal = normalise_name(country)
    if normal in existing:
        return existing[normal]
    slug = re.sub(r"\s+", "_", country.strip())
    return slug.replace("/", "_")


def main() -> None:
    args = parse_args()
    args.source.mkdir(parents=True, exist_ok=True)
    pages = args.source / "elo_pages"
    pages.mkdir(parents=True, exist_ok=True)
    client = PublicTsvClient(args.rate)
    base = args.base_url.rstrip("/")

    with tempfile.TemporaryDirectory(prefix="source-refresh-", dir=args.source) as temp_name:
        staging = Path(temp_name)
        fetched: dict[str, str] = {}
        for filename in REFERENCE_FILES:
            text = client.get(f"{base}/{quote(filename)}")
            if filename == "World.tsv":
                world_rows = validate_world(text)
            else:
                validate_reference(filename, text)
            (staging / filename).write_text(text, encoding="utf-8")
            fetched[filename] = text

        successors_path = staging / "teams.tsv"
        successors = read_successors(successors_path)
        name_codes = parse_name_codes(fetched["en.teams.tsv"])
        existing_stems = {
            normalise_name(path.stem.replace("_", " ")): path.stem
            for path in pages.glob("*.tsv")
        }
        # Also map the first-party canonical labels directly to existing stems.
        for normal, code in name_codes.items():
            for path in pages.glob("*.tsv"):
                if normalise_name(path.stem.replace("_", " ")) == normal:
                    existing_stems[normal] = path.stem

        now = datetime.now(timezone.utc)
        full = args.full or (args.full_if_sunday and now.weekday() == 6)
        selected: list[tuple[str, str, int]] = []
        unresolved: list[str] = []
        for row in world_rows:
            country = row[2].strip()
            official = int(row[3])
            normal = normalise_name(country)
            slug = slug_from_country(country, existing_stems)
            code = name_codes.get(normal)
            if code is None:
                unresolved.append(country)
                selected.append((slug, "", official))
                continue
            team = canonical(code, successors)
            local = latest_official_rating(pages / f"{slug}.tsv", team, successors)
            if full or local != official:
                selected.append((slug, team, official))

        refreshed = []
        for slug, _, _ in selected:
            url = f"{base}/{quote(slug, safe='_-.()')}.tsv"
            text = client.get(url)
            new_count = validate_team_page(text, slug)
            old_path = pages / f"{slug}.tsv"
            old_count = (
                len([line for line in old_path.read_text(encoding="utf-8").splitlines() if line])
                if old_path.exists()
                else 0
            )
            if (
                old_count
                and new_count < math_floor(old_count * 0.95)
                and not args.allow_large_rewrite
            ):
                raise ValueError(
                    f"Refusing large source rewrite for {slug}: {old_count} -> {new_count} rows"
                )
            target = staging / "elo_pages" / f"{slug}.tsv"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            if not old_path.exists() or old_path.read_text(encoding="utf-8") != text:
                refreshed.append(slug)

        # Nothing is replaced until every response has passed validation.
        for filename in REFERENCE_FILES:
            os.replace(staging / filename, args.source / filename)
        staged_pages = staging / "elo_pages"
        page_paths = staged_pages.glob("*.tsv") if staged_pages.exists() else []
        for path in page_paths:
            os.replace(path, pages / path.name)

    status = {
        "source_checked_at": now.replace(microsecond=0).isoformat(),
        "mode": "full reconciliation" if full else "rating-change detection",
        "world_teams": len(world_rows),
        "pages_checked": len(selected),
        "pages_changed": len(refreshed),
        "changed": refreshed,
        "unresolved_world_names": unresolved,
        "base_url": base,
        "integrity": "all downloaded rows passed schema and rewrite guards",
    }
    (args.source / "status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False))

    # Refresh the independent recent-results and future-fixtures supplement
    # after the first-party snapshot has been safely replaced. This keeps the
    # scheduled workflow comprehensive without requiring a second workflow
    # definition or a manually maintained list of competitions.
    subprocess.run(
        [sys.executable, str(Path(__file__).with_name("open_results.py")), "--source", str(args.source)],
        check=True,
    )


def math_floor(value: float) -> int:
    # Local helper avoids importing a module solely for one safety threshold.
    return int(value // 1)


if __name__ == "__main__":
    main()
