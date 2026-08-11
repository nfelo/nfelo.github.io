#!/usr/bin/env python3
"""Download, validate, and compact the public club-match source blend.

The deployed club model deliberately does not scrape the many historical web
pages in the source directory supplied by the site owner.  Those pages are an
excellent discovery and corroboration index, but their layouts and club names
are not stable enough for an unattended ratings ledger.  The inputs below are
machine-readable, independently attributed, hash-recorded, and fail closed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Iterable
from urllib.request import Request, urlopen


USER_AGENT = "NetworkFootballEloClubBuilder/1.0 (+https://github.com/nfelo/nfelo.github.io)"
SCHOCHASTICS_URL = (
    "https://raw.githubusercontent.com/schochastics/football-data/"
    "master/data/results/games.parquet"
)
ENGSOCCER_REF = "872c5c354161ace8408f3091b758c6af4cccca94"
ENGSOCCER_FILES = (
    "england.csv",
    "england5.csv",
    "england_nonleague.csv",
    "facup.csv",
    "leaguecup.csv",
    "englandplayoffs.csv",
    "scotland.csv",
    "germany.csv",
    "champs.csv",
)
TRANSFERMARKT_BASE = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
TRANSFERMARKT_FILES = ("games.csv.gz", "clubs.csv.gz", "competitions.csv.gz")
BRAZIL_BASE = (
    "https://raw.githubusercontent.com/BrazilianFootball/Data/"
    "master/results/processed"
)
BRAZIL_COMPETITIONS = {
    "Serie_A": ("Campeonato Brasileiro Serie A", 1, "league"),
    "Serie_B": ("Campeonato Brasileiro Serie B", 2, "league"),
    "Serie_C": ("Campeonato Brasileiro Serie C", 3, "league"),
    "Serie_D": ("Campeonato Brasileiro Serie D", 4, "league"),
    "CdB": ("Copa do Brasil", 1, "domestic_cup"),
}
BRAZIL_YEARS = range(2013, 2026)
BRAZIL_STATE_BASE = (
    "https://raw.githubusercontent.com/FerrerasRP/FootballData/"
    "refs/heads/main/database"
)
BRAZIL_STATE_COMPETITIONS = {
    "brasil-campeonato-alagoano": ("Campeonato Alagoano", "AL"),
    "brasil-campeonato-baiano": ("Campeonato Baiano", "BA"),
    "brasil-campeonato-carioca": ("Campeonato Carioca", "RJ"),
    "brasil-campeonato-catarinense": ("Campeonato Catarinense", "SC"),
    "brasil-campeonato-cearense": ("Campeonato Cearense", "CE"),
    "brasil-campeonato-gaucho": ("Campeonato Gaúcho", "RS"),
    "brasil-campeonato-goiano": ("Campeonato Goiano", "GO"),
    "brasil-campeonato-maranhense": ("Campeonato Maranhense", "MA"),
    "brasil-campeonato-matogrossense": ("Campeonato Mato-Grossense", "MT"),
    "brasil-campeonato-mineiro": ("Campeonato Mineiro", "MG"),
    "brasil-campeonato-paraense": ("Campeonato Paraense", "PA"),
    "brasil-campeonato-paranaense": ("Campeonato Paranaense", "PR"),
    "brasil-campeonato-paulista": ("Campeonato Paulista", "SP"),
    "brasil-campeonato-pernanbucano": ("Campeonato Pernambucano", "PE"),
}
BRAZIL_STATE_YEARS = range(2019, 2027)


@dataclass(frozen=True)
class DownloadedSource:
    key: str
    path: str
    url: str
    bytes: int
    sha256: str
    retrieved_at: str
    licence: str
    attribution: str
    mutable: bool


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path, minimum_bytes: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(4):
        temporary: Path | None = None
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/octet-stream,text/csv,application/json,*/*",
                },
            )
            with urlopen(request, timeout=120) as response:
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent,
                    prefix=f".{destination.name}.",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        handle.write(chunk)
            size = temporary.stat().st_size
            if size < minimum_bytes:
                raise ValueError(
                    f"{url} returned only {size:,} bytes; expected at least "
                    f"{minimum_bytes:,}"
                )
            os.replace(temporary, destination)
            return
        except Exception as error:
            last_error = error
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to download {url}: {last_error}") from last_error


def ensure_runtime_sources(cache: Path, *, refresh: bool = False) -> dict[str, Any]:
    """Materialise the large, non-repository inputs and return provenance."""
    cache.mkdir(parents=True, exist_ok=True)
    requested: list[tuple[str, str, Path, int, str, str, bool]] = [
        (
            "schochastics",
            SCHOCHASTICS_URL,
            cache / "schochastics-games.parquet",
            10_000_000,
            "Open Data Commons Attribution 1.0",
            "schochastics/football-data",
            True,
        )
    ]
    for filename in ENGSOCCER_FILES:
        requested.append(
            (
                f"engsoccerdata:{filename}",
                (
                    "https://raw.githubusercontent.com/jalapic/engsoccerdata/"
                    f"{ENGSOCCER_REF}/data-raw/{filename}"
                ),
                cache / "engsoccerdata" / filename,
                100,
                "Free for non-commercial use; citation requested",
                "James P. Curley, engsoccerdata",
                False,
            )
        )
    for filename in TRANSFERMARKT_FILES:
        requested.append(
            (
                f"transfermarkt:{filename}",
                f"{TRANSFERMARKT_BASE}/{filename}",
                cache / "transfermarkt" / filename,
                1_000,
                "CC0 1.0 (dataset repository); underlying source attribution retained",
                "dcaribou/transfermarkt-datasets and Transfermarkt",
                True,
            )
        )

    needed = [item for item in requested if refresh or not item[2].is_file()]
    if needed:
        with ThreadPoolExecutor(max_workers=min(8, len(needed))) as executor:
            futures = {
                executor.submit(_download, url, path, minimum): (key, url)
                for key, url, path, minimum, _, _, _ in needed
            }
            for future in as_completed(futures):
                key, url = futures[future]
                future.result()
                print(f"club source ready: {key} ({url})")

    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sources = []
    for key, url, path, _, licence, attribution, mutable in requested:
        sources.append(
            asdict(
                DownloadedSource(
                    key=key,
                    path=str(path),
                    url=url,
                    bytes=path.stat().st_size,
                    sha256=sha256_path(path),
                    retrieved_at=retrieved_at,
                    licence=licence,
                    attribution=attribution,
                    mutable=mutable,
                )
            )
        )
    manifest = {"retrieved_at": retrieved_at, "sources": sources}
    (cache / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _brazil_url(prefix: str, year: int) -> str:
    return f"{BRAZIL_BASE}/{prefix}_{year}_games.json"


def _read_json_url(url: str) -> tuple[bytes, dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=120) as response:
                payload = response.read()
            if len(payload) < 100:
                raise ValueError(f"short JSON response ({len(payload)} bytes)")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("expected a JSON object keyed by match number")
            return payload, value
        except Exception as error:
            last_error = error
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to download {url}: {last_error}") from last_error


def _read_json_list_url(url: str) -> tuple[bytes, list[dict[str, Any]]]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=120) as response:
                payload = response.read()
            if len(payload) < 20:
                raise ValueError(f"short JSON response ({len(payload)} bytes)")
            value = json.loads(payload)
            if not isinstance(value, list):
                raise ValueError("expected a JSON match list")
            return payload, value
        except Exception as error:
            last_error = error
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to download {url}: {last_error}") from last_error


def _club_and_state(value: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", value).strip()
    match = re.match(r"^(.*?)\s*/\s*([A-Z]{2})$", cleaned)
    if match:
        return match.group(1).strip(), match.group(2)
    return cleaned, ""


def _parse_score(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*[xX×-]\s*(\d+)", str(value))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def refresh_brazil_snapshot(source: Path) -> dict[str, Any]:
    """Create a compact, reviewable CBF match snapshot for tiers 1-4 and cup."""
    jobs = [(prefix, year, _brazil_url(prefix, year)) for prefix in BRAZIL_COMPETITIONS for year in BRAZIL_YEARS]
    payloads: dict[tuple[str, int], tuple[bytes, dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_read_json_url, url): (prefix, year, url)
            for prefix, year, url in jobs
        }
        for future in as_completed(futures):
            prefix, year, url = futures[future]
            payloads[(prefix, year)] = future.result()
            print(f"Brazil club source ready: {prefix} {year} ({url})")

    rows: list[dict[str, Any]] = []
    source_hash = hashlib.sha256()
    per_file: list[dict[str, Any]] = []
    for prefix, year, url in jobs:
        raw, payload = payloads[(prefix, year)]
        digest = hashlib.sha256(raw).hexdigest()
        source_hash.update(f"{url}\0{digest}\n".encode())
        per_file.append({"url": url, "bytes": len(raw), "sha256": digest})
        competition, tier, kind = BRAZIL_COMPETITIONS[prefix]
        for source_id, item in payload.items():
            score = _parse_score(item.get("Result", ""))
            if score is None:
                continue
            try:
                day, month, parsed_year = (
                    int(part) for part in str(item["Date"]).split("/")
                )
                date_text = f"{parsed_year:04d}-{month:02d}-{day:02d}"
            except (KeyError, TypeError, ValueError):
                continue
            home, home_state = _club_and_state(str(item.get("Home", "")))
            away, away_state = _club_and_state(str(item.get("Away", "")))
            if not home or not away or home == away:
                continue
            rows.append(
                {
                    "date": date_text,
                    "season": year,
                    "competition": competition,
                    "kind": kind,
                    "tier": tier,
                    "home": home,
                    "home_state": home_state,
                    "away": away,
                    "away_state": away_state,
                    "home_goals": score[0],
                    "away_goals": score[1],
                    "source_file": f"{prefix}_{year}_games.json",
                    "source_id": source_id,
                }
            )

    rows.sort(key=lambda row: (row["date"], row["competition"], row["source_id"]))
    if len(rows) < 15_000:
        raise ValueError(f"Brazil source unexpectedly yielded only {len(rows):,} matches")
    source.mkdir(parents=True, exist_ok=True)
    target = source / "club_brazil.csv.gz"
    fields = list(rows[0])
    with tempfile.NamedTemporaryFile(dir=source, prefix=".club-brazil.", delete=False) as raw_handle:
        temporary = Path(raw_handle.name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="", compresslevel=9) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

    refreshed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "source": "BrazilianFootball/Data",
        "source_url": "https://github.com/BrazilianFootball/Data",
        "licence": "MIT",
        "attribution": "Igor Patricio Michels and contributors; source match reports: CBF",
        "refreshed_at": refreshed_at,
        "first": rows[0]["date"],
        "last": rows[-1]["date"],
        "matches": len(rows),
        "snapshot_bytes": target.stat().st_size,
        "snapshot_sha256": sha256_path(target),
        "upstream_set_sha256": source_hash.hexdigest(),
        "upstream_files": per_file,
    }
    (source / "club_brazil.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _state_url(slug: str, year: int) -> str:
    return f"{BRAZIL_STATE_BASE}/{slug}/{slug}%20{year}.json"


def _state_team_name(value: Any) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ")
    # A few upstream files append an integer to repeated scraper labels
    # (for example ``santos_2`` and ``athletico-pr-5``).  These competitions
    # contain the senior first teams, not numbered reserve sides, so retain the
    # football name and discard only that terminal disambiguator.
    text = re.sub(r"\s+\d+$", "", text).strip()
    return " ".join(part.capitalize() for part in text.split())


def refresh_brazil_state_snapshot(source: Path) -> dict[str, Any]:
    """Compact fourteen recent Brazilian state championships from CC0 JSON."""
    jobs = [
        (slug, year, _state_url(slug, year))
        for slug in BRAZIL_STATE_COMPETITIONS
        for year in BRAZIL_STATE_YEARS
    ]
    payloads: dict[tuple[str, int], tuple[bytes, list[dict[str, Any]]]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_read_json_list_url, url): (slug, year, url)
            for slug, year, url in jobs
        }
        for future in as_completed(futures):
            slug, year, url = futures[future]
            payloads[(slug, year)] = future.result()
            print(f"Brazil state source ready: {slug} {year} ({url})")

    rows: list[dict[str, Any]] = []
    source_hash = hashlib.sha256()
    per_file: list[dict[str, Any]] = []
    for slug, year, url in jobs:
        raw, payload = payloads[(slug, year)]
        digest = hashlib.sha256(raw).hexdigest()
        source_hash.update(f"{url}\0{digest}\n".encode())
        per_file.append({"url": url, "bytes": len(raw), "sha256": digest})
        competition, state = BRAZIL_STATE_COMPETITIONS[slug]
        for index, item in enumerate(payload):
            try:
                match_day = datetime.strptime(
                    str(item["match_date"])[:10], "%d.%m.%Y"
                ).date().isoformat()
                home_goals = int(item["goals_home"])
                away_goals = int(item["goals_away"])
            except (KeyError, TypeError, ValueError):
                continue
            home = _state_team_name(item.get("home"))
            away = _state_team_name(item.get("away"))
            if not home or not away or home == away:
                continue
            rows.append(
                {
                    "date": match_day,
                    "season": year,
                    "competition": competition,
                    "state": state,
                    "home": home,
                    "away": away,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "round": str(item.get("round") or ""),
                    "source_file": f"{slug}/{slug} {year}.json",
                    "source_id": index,
                }
            )
    rows.sort(
        key=lambda row: (
            row["date"], row["competition"], row["round"], row["source_id"]
        )
    )
    if len(rows) < 6_500:
        raise ValueError(
            f"Brazil state source unexpectedly yielded only {len(rows):,} matches"
        )
    source.mkdir(parents=True, exist_ok=True)
    target = source / "club_brazil_states.csv.gz"
    fields = list(rows[0])
    with tempfile.NamedTemporaryFile(
        dir=source, prefix=".club-brazil-states.", delete=False
    ) as raw_handle:
        temporary = Path(raw_handle.name)
    try:
        with gzip.open(
            temporary, "wt", encoding="utf-8", newline="", compresslevel=9
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, target)
        target.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)

    refreshed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "source": "FerrerasRP/FootballData",
        "source_url": "https://github.com/FerrerasRP/FootballData",
        "licence": "CC0 1.0",
        "attribution": "FerrerasRP/FootballData contributors",
        "refreshed_at": refreshed_at,
        "first": rows[0]["date"],
        "last": rows[-1]["date"],
        "matches": len(rows),
        "competitions": len(BRAZIL_STATE_COMPETITIONS),
        "snapshot_bytes": target.stat().st_size,
        "snapshot_sha256": sha256_path(target),
        "upstream_set_sha256": source_hash.hexdigest(),
        "upstream_files": per_file,
    }
    (source / "club_brazil_states.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".club-cache"))
    parser.add_argument("--source", type=Path, default=Path("source"))
    parser.add_argument("--refresh-runtime", action="store_true")
    parser.add_argument("--refresh-brazil", action="store_true")
    parser.add_argument("--refresh-brazil-states", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] = {}
    if args.refresh_runtime:
        result["runtime"] = ensure_runtime_sources(args.cache, refresh=True)
    if args.refresh_brazil:
        result["brazil"] = refresh_brazil_snapshot(args.source)
    if args.refresh_brazil_states:
        result["brazil_states"] = refresh_brazil_state_snapshot(args.source)
    if not result:
        result["runtime"] = ensure_runtime_sources(args.cache)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
