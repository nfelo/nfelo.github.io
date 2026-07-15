#!/usr/bin/env python3
"""Refresh post-snapshot results and fixtures from a GitHub-hosted CC0 feed."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unicodedata
from urllib.request import Request, urlopen

from ledger import canonical, read_successors


DEFAULT_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/"
    "master/results.csv"
)
WORLD_CUP_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json/"
    "master/2026/worldcup.json"
)
SPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json"
WFE_FIXTURES_URL = "https://www.eloratings.net/fixtures.tsv"
SPORTSDB_FIXTURE_COMPETITIONS = (
    {
        "league_id": "4490",
        "season": "2026-2027",
        "rounds": range(1, 7),
        "code": "NL",
        "name": "UEFA Nations League",
    },
)
EXPECTED_COLUMNS = {
    "date",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "tournament",
    "city",
    "country",
    "neutral",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("source"))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--world-cup-url", default=WORLD_CUP_URL)
    parser.add_argument("--wfe-fixtures-url", default=WFE_FIXTURES_URL)
    parser.add_argument(
        "--sportsdb-key",
        default=os.environ.get("THESPORTSDB_API_KEY", "123"),
        help="TheSportsDB v1 key; the documented free key is used by default",
    )
    # Kept for compatibility with the existing scheduled workflow.
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--full-if-sunday", action="store_true")
    parser.add_argument("--allow-large-rewrite", action="store_true")
    parser.add_argument("--rate", type=float, default=2.0)
    return parser.parse_args()


def normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed.casefold() if character.isalnum())


def download(
    url: str,
    minimum_size: int = 1_000_000,
    user_agent: str = "NetworkFootballEloPages/2.0",
    accept: str = "text/csv,text/plain;q=0.9,*/*;q=0.1",
) -> str:
    try:
        from curl_cffi import requests as curl_requests

        response = curl_requests.get(
            url,
            impersonate="chrome124",
            timeout=60,
            headers={"User-Agent": user_agent, "Accept": accept},
        )
        if response.status_code != 200:
            raise ValueError(f"Open results request returned HTTP {response.status_code}")
        text = response.text.lstrip("\ufeff")
        if len(text) < minimum_size:
            raise ValueError(f"Open results response is unexpectedly small: {len(text)} bytes")
        return text
    except ImportError:
        pass
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": accept,
        },
    )
    with urlopen(request, timeout=60) as response:
        text = response.read().decode("utf-8-sig")
    if len(text) < minimum_size:
        raise ValueError(f"Open results response is unexpectedly small: {len(text)} bytes")
    return text


def latest_snapshot_date(pages: Path) -> date:
    latest = date(1872, 1, 1)
    for path in pages.glob("*.tsv"):
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) != 16:
                continue
            year, month, day = map(int, fields[:3])
            if month and day:
                latest = max(latest, date(year, month, day))
    if latest.year < 2020:
        raise ValueError(f"Bundled snapshot ends unexpectedly early: {latest.isoformat()}")
    return latest


def team_aliases(source: Path, successors: dict[str, str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for line in (source / "en.teams.tsv").read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) < 2 or not fields[0] or fields[0].endswith("_loc"):
            continue
        code = canonical(fields[0], successors)
        for label in fields[1:]:
            if label:
                aliases.setdefault(normalise(label), code)
    manual = {
        "unitedstates": "US",
        "southkorea": "KR",
        "northkorea": "KP",
        "ivorycoast": "CI",
        "capeverde": "CV",
        "drcongo": "CD",
        "republicofireland": "IE",
        "czechrepublic": "CZ",
        "curacao": "CW",
        "turkiye": "TR",
        "bosniaherzegovina": "BA",
        "unitedstatesofamerica": "US",
    }
    for label, code in manual.items():
        aliases[label] = canonical(code, successors)
    return aliases


def tournament_code(name: str) -> str:
    if normalise(name) == "friendly":
        return "F"
    known = {
        "fifaworldcup": "WC",
        "fifaworldcupqualification": "WQT",
        "uefaeuro": "EC",
        "uefanationsleague": "NL",
        "copaamerica": "CA",
        "africancupofnations": "AC",
        "afcasiancup": "AS",
        "concacafgoldcup": "GC",
        "ofcnationscup": "OC",
    }
    key = normalise(name)
    if key in known:
        return known[key]
    return "X" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:7].upper()


def valid_score(value: str) -> bool:
    return value.strip().isdigit()


def record_key(item: dict[str, object]) -> tuple[str, tuple[str, str]]:
    return str(item["date"]), tuple(sorted((str(item["team1_code"]), str(item["team2_code"]))))


def venue_country(ground: str) -> tuple[str, str | None]:
    city = ground.casefold()
    if any(name in city for name in ("mexico city", "guadalajara", "monterrey")):
        return "Mexico", "MX"
    if any(name in city for name in ("toronto", "vancouver")):
        return "Canada", "CA"
    return "United States", "US"


def merge_record(
    target: dict[tuple[str, tuple[str, str]], dict[str, object]],
    item: dict[str, object],
) -> None:
    key = record_key(item)
    previous = target.get(key)
    if previous is not None and "score1" in previous and "score1" in item:
        old_scores = (previous["score1"], previous["score2"])
        new_scores = (item["score1"], item["score2"])
        old_codes = (previous["team1_code"], previous["team2_code"])
        new_codes = (item["team1_code"], item["team2_code"])
        if old_codes == tuple(reversed(new_codes)):
            new_scores = tuple(reversed(new_scores))
        if old_scores != new_scores:
            raise ValueError(f"Conflicting scores from result sources for {key}: {old_scores} vs {new_scores}")
    target[key] = item


def integer_score(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def read_team_names(source: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in (source / "en.teams.tsv").read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0] and not fields[0].endswith("_loc"):
            names[fields[0]] = fields[1]
    return names


def read_primary_labels(path: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0]:
            labels[fields[0]] = fields[1]
    return labels


def main() -> None:
    args = parse_args()
    source = args.source
    source.mkdir(parents=True, exist_ok=True)
    successors = read_successors(source / "teams.tsv")
    aliases = team_aliases(source, successors)
    team_names = read_team_names(source)
    published_tournaments = read_primary_labels(source / "en.tournaments.tsv")
    cutoff = latest_snapshot_date(source / "elo_pages")
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=370)

    text = download(args.url)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not EXPECTED_COLUMNS.issubset(reader.fieldnames):
        raise ValueError(f"Open results schema changed: {reader.fieldnames}")
    rows = list(reader)
    if len(rows) < 49_000:
        raise ValueError(f"Open results feed unexpectedly has only {len(rows)} rows")

    results: list[dict[str, object]] = []
    fixtures: list[dict[str, object]] = []
    tournament_names: dict[str, str] = {}
    unresolved: set[str] = set()
    for row in rows:
        try:
            match_date = date.fromisoformat(row["date"])
        except (TypeError, ValueError):
            continue
        home_name = row["home_team"].strip()
        away_name = row["away_team"].strip()
        if not home_name or not away_name or home_name == "NA" or away_name == "NA":
            continue
        has_score = valid_score(row["home_score"]) and valid_score(row["away_score"])
        relevant_result = has_score and match_date > cutoff
        relevant_fixture = not has_score and today <= match_date <= horizon
        if not relevant_result and not relevant_fixture:
            continue
        home = aliases.get(normalise(home_name))
        away = aliases.get(normalise(away_name))
        if home is None or away is None:
            unresolved.update(
                name for name, code in ((home_name, home), (away_name, away)) if code is None
            )
            continue
        tournament = row["tournament"].strip() or "International match"
        code = tournament_code(tournament)
        tournament_names[code] = tournament
        neutral = row["neutral"].strip().upper() == "TRUE"
        common = {
            "date": match_date.isoformat(),
            "team1_code": home,
            "team2_code": away,
            "team1_name": home_name,
            "team2_name": away_name,
            "tournament_code": code,
            "tournament_name": tournament,
            "city": row["city"].strip(),
            "country": row["country"].strip(),
            "neutral": neutral,
            "home_sign": 0 if neutral else 1,
        }
        if relevant_result:
            results.append(
                {
                    **common,
                    "score1": int(row["home_score"]),
                    "score2": int(row["away_score"]),
                }
            )
        elif relevant_fixture:
            fixtures.append(common)

    result_map: dict[tuple[str, tuple[str, str]], dict[str, object]] = {}
    fixture_map: dict[tuple[str, tuple[str, str]], dict[str, object]] = {}
    for item in results:
        merge_record(result_map, item)
    for item in fixtures:
        merge_record(fixture_map, item)

    world_cup_text = download(args.world_cup_url, minimum_size=10_000)
    world_cup = json.loads(world_cup_text)
    world_cup_matches = world_cup.get("matches")
    if world_cup.get("name") != "World Cup 2026" or not isinstance(world_cup_matches, list):
        raise ValueError("OpenFootball World Cup schema changed")
    if len(world_cup_matches) < 100:
        raise ValueError(f"OpenFootball World Cup feed has only {len(world_cup_matches)} matches")

    world_cup_results = 0
    for match in world_cup_matches:
        if not isinstance(match, dict):
            continue
        try:
            match_date = date.fromisoformat(str(match["date"]))
        except (KeyError, ValueError):
            continue
        home_name = str(match.get("team1", "")).strip()
        away_name = str(match.get("team2", "")).strip()
        if any(
            not name
            or normalise(name) in {"tbd", "tobedetermined"}
            or (len(name) > 1 and name[0] in {"W", "L"} and name[1:].isdigit())
            for name in (home_name, away_name)
        ):
            continue
        home = aliases.get(normalise(home_name))
        away = aliases.get(normalise(away_name))
        score = match.get("score")
        full_time = score.get("ft") if isinstance(score, dict) else None
        has_score = (
            isinstance(full_time, list)
            and len(full_time) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in full_time)
        )
        relevant_result = has_score and match_date > cutoff
        relevant_fixture = not has_score and today <= match_date <= horizon
        if not relevant_result and not relevant_fixture:
            continue
        if home is None or away is None:
            unresolved.update(
                name for name, code in ((home_name, home), (away_name, away)) if name and code is None
            )
            continue
        ground = str(match.get("ground", "")).strip()
        country, host_code = venue_country(ground)
        home_sign = 1 if home == host_code else (-1 if away == host_code else 0)
        common = {
            "date": match_date.isoformat(),
            "team1_code": home,
            "team2_code": away,
            "team1_name": home_name,
            "team2_name": away_name,
            "tournament_code": "WC",
            "tournament_name": "FIFA World Cup",
            "city": ground,
            "country": country,
            "neutral": home_sign == 0,
            "home_sign": home_sign,
        }
        if relevant_result:
            merge_record(
                result_map,
                {**common, "score1": int(full_time[0]), "score2": int(full_time[1])},
            )
            world_cup_results += 1
        elif record_key(common) not in result_map:
            merge_record(fixture_map, common)

    sportsdb_urls: list[str] = []
    sportsdb_events = 0
    for competition in SPORTSDB_FIXTURE_COMPETITIONS:
        tournament_names[str(competition["code"])] = str(competition["name"])
        for round_number in competition["rounds"]:
            url = (
                f"{SPORTSDB_BASE}/{args.sportsdb_key}/eventsround.php"
                f"?id={competition['league_id']}&r={round_number}&s={competition['season']}"
            )
            sportsdb_urls.append(url.replace(f"/{args.sportsdb_key}/", "/KEY/"))
            payload = json.loads(download(url, minimum_size=100))
            events = payload.get("events")
            if not isinstance(events, list):
                raise ValueError(f"TheSportsDB returned no event list for {competition['name']} round {round_number}")
            for event in events:
                if not isinstance(event, dict):
                    continue
                try:
                    match_date = date.fromisoformat(str(event["dateEvent"]))
                except (KeyError, ValueError):
                    continue
                if match_date <= cutoff or match_date > horizon:
                    continue
                home_name = str(event.get("strHomeTeam", "")).strip()
                away_name = str(event.get("strAwayTeam", "")).strip()
                home = aliases.get(normalise(home_name))
                away = aliases.get(normalise(away_name))
                if home is None or away is None:
                    unresolved.update(
                        name for name, code in ((home_name, home), (away_name, away)) if name and code is None
                    )
                    continue
                home_score = integer_score(event.get("intHomeScore"))
                away_score = integer_score(event.get("intAwayScore"))
                common = {
                    "date": match_date.isoformat(),
                    "kickoff_utc": str(event.get("strTimestamp", "")).strip(),
                    "team1_code": home,
                    "team2_code": away,
                    "team1_name": home_name,
                    "team2_name": away_name,
                    "tournament_code": competition["code"],
                    "tournament_name": competition["name"],
                    "city": str(event.get("strVenue", "")).strip(),
                    "country": str(event.get("strCountry", "")).strip(),
                    "neutral": False,
                    "home_sign": 1,
                }
                if home_score is not None and away_score is not None:
                    merge_record(
                        result_map,
                        {**common, "score1": home_score, "score2": away_score},
                    )
                elif match_date >= today and record_key(common) not in result_map:
                    merge_record(fixture_map, common)
                    sportsdb_events += 1

    # World Football Elo Ratings publishes a compact, public fixture ledger
    # covering all confederations and friendlies.  It complements the
    # competition-specific API above, which cannot discover unscheduled league
    # IDs or one-off internationals.
    wfe_text = download(
        args.wfe_fixtures_url,
        minimum_size=1_000,
        user_agent="curl/8.5.0",
        accept="*/*",
    )
    wfe_rows = 0
    for line_number, line in enumerate(wfe_text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            raise ValueError(f"WFE fixture row {line_number} has only {len(fields)} fields")
        try:
            year, month, day = map(int, fields[:3])
            provisional_date = date(year, month, day or 1)
        except ValueError as exc:
            raise ValueError(f"Invalid WFE fixture date on row {line_number}") from exc
        if provisional_date < today.replace(day=1) or provisional_date > horizon:
            continue
        raw_home, raw_away, tournament, venue = fields[3:7]
        home = canonical(raw_home, successors)
        away = canonical(raw_away, successors)
        if home not in team_names or away not in team_names:
            unresolved.update(code for code in (raw_home, raw_away) if code not in team_names)
            continue
        code = tournament.strip() or "F"
        tournament_names.setdefault(code, published_tournaments.get(code, code))
        home_sign = 1 if venue == raw_home else (-1 if venue == raw_away else 0)
        fixture = {
            "date": provisional_date.isoformat(),
            "date_precision": "month" if day == 0 else "day",
            "team1_code": home,
            "team2_code": away,
            "team1_name": team_names.get(raw_home, team_names[home]),
            "team2_name": team_names.get(raw_away, team_names[away]),
            "tournament_code": code,
            "tournament_name": tournament_names.get(code, code),
            "city": "",
            "country": team_names.get(venue, ""),
            "neutral": home_sign == 0,
            "home_sign": home_sign,
        }
        if record_key(fixture) not in result_map and record_key(fixture) not in fixture_map:
            merge_record(fixture_map, fixture)
            wfe_rows += 1

    for key in result_map:
        fixture_map.pop(key, None)
    results = list(result_map.values())
    fixtures = list(fixture_map.values())
    tournament_names["WC"] = "FIFA World Cup"
    results.sort(key=lambda item: (item["date"], item["team1_code"], item["team2_code"]))
    fixtures.sort(key=lambda item: (item["date"], item["team1_name"], item["team2_name"]))
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory(prefix="open-results-", dir=source) as temp_name:
        staging = Path(temp_name)
        result_path = staging / "supplemental_results.csv"
        fieldnames = [
            "date", "team1_code", "team2_code", "team1_name", "team2_name",
            "score1", "score2", "tournament_code", "tournament_name", "city",
            "country", "neutral", "home_sign",
        ]
        with result_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        (staging / "upcoming_fixtures.json").write_text(
            json.dumps(
                {
                    "sources": [args.url, args.world_cup_url, args.wfe_fixtures_url, "TheSportsDB v1 schedule API"],
                    "checked_at": checked_at,
                    "fixtures": fixtures,
                },
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        (staging / "supplemental_tournaments.json").write_text(
            json.dumps(tournament_names, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for filename in (
            "supplemental_results.csv",
            "upcoming_fixtures.json",
            "supplemental_tournaments.json",
        ):
            (staging / filename).replace(source / filename)

    old_status_path = source / "status.json"
    previous = (
        json.loads(old_status_path.read_text(encoding="utf-8"))
        if old_status_path.exists()
        else {}
    )
    base_snapshot = previous
    while (
        isinstance(base_snapshot, dict)
        and base_snapshot.get("mode") in {
            "GitHub-hosted open-results supplement",
            "multi-source open-results supplement",
        }
        and isinstance(base_snapshot.get("base_snapshot"), dict)
    ):
        base_snapshot = base_snapshot["base_snapshot"]
    status = {
        "source_checked_at": checked_at,
        "mode": "multi-source open-results supplement",
        "base_snapshot_through": cutoff.isoformat(),
        "supplemental_results": len(results),
        "upcoming_fixtures": len(fixtures),
        "open_feed_rows": len(rows),
        "unresolved_names": sorted(unresolved),
        "base_urls": [args.url, args.world_cup_url],
        "world_cup_results": world_cup_results,
        "sportsdb_fixture_events": sportsdb_events,
        "sportsdb_requests": len(sportsdb_urls),
        "wfe_fixture_rows": wfe_rows,
        "integrity": "All result and fixture sources passed schema, size, date, score, alias and conflict checks",
        "base_snapshot": base_snapshot,
    }
    old_status_path.write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
