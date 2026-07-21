#!/usr/bin/env python3
"""Replay the published model and write compact static JSON for GitHub Pages."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import re
import unicodedata
from typing import Any

from model import (
    calibration_scale,
    home_advantage,
    logistic10,
    run_replay,
    three_way_probabilities,
)
from forecast_layer import forecast_from_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("source"))
    parser.add_argument("--config", type=Path, default=Path("config"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    return parser.parse_args()


def compact(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [compact(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(compact(value), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_browser_assets(output: Path) -> None:
    index = output / "index.html"
    html = index.read_text(encoding="utf-8")
    for asset in ("assets/styles.css", "assets/app.js"):
        revision = sha256(output / asset)[:12]
        html = re.sub(
            rf'{re.escape(asset)}(?:\?v=[^"\']*)?',
            f"{asset}?v={revision}",
            html,
        )
    index.write_text(html, encoding="utf-8")


def write_route_entries(output: Path, summary: dict[str, Any]) -> None:
    template = (output / "index.html").read_text(encoding="utf-8")
    root = "https://nfelo.github.io/"
    routes = {
        "rankings": ("Rankings", "Current international football rankings from the Network Football Elo model."),
        "history": ("Historical rankings", "Reconstruct international football rankings on any historical matchday."),
        "tournaments": ("Tournament rankings", "Compare participant rankings immediately before and after international tournaments."),
        "matches": ("Matches", "Search international football results and pre-match forecasts from 1872 onward."),
        "fixtures": ("Upcoming matches", "Upcoming senior internationals with current ratings and match probabilities."),
        "records": ("Records", "All-time national-team rating peaks, greatest matchups and largest upsets."),
        "compare": ("Compare teams", "Compare two national teams' ratings, movement, histories and head-to-head results."),
        "predict": ("Predict a match", "Compare two national teams and calculate win, draw and loss probabilities."),
        "methodology": ("Methodology", "Detailed, reproducible methodology for the Network Football Elo model."),
        "faq": ("Frequently asked questions", "Clear answers about Network Football Elo ratings, forecasts, data and methodology."),
        "about": ("About", "Data sources, update schedule and limitations of Network Football Elo."),
    }
    entries: list[tuple[str, str, str]] = [
        (path, title, description) for path, (title, description) in routes.items()
    ]
    entries.extend(
        (f"team/{team['code']}", team["nation"], f"{team['nation']} ratings, results and historical record.")
        for team in summary["teams"]
    )
    urls = [root]
    for path, title, description in entries:
        canonical = f"{root}{path}/"
        html = template
        html = re.sub(r"<title>.*?</title>", f"<title>{title} &middot; Network Football Elo</title>", html)
        html = re.sub(r'(<meta name="description" content=")[^"]*', rf"\g<1>{description}", html)
        html = re.sub(r'(<link rel="canonical" href=")[^"]*', rf"\g<1>{canonical}", html)
        html = re.sub(r'(<meta property="og:title" content=")[^"]*', rf"\g<1>{title} &middot; Network Football Elo", html)
        html = re.sub(r'(<meta property="og:description" content=")[^"]*', rf"\g<1>{description}", html)
        html = re.sub(r'(<meta property="og:url" content=")[^"]*', rf"\g<1>{canonical}", html)
        html = re.sub(r'(<meta name="twitter:title" content=")[^"]*', rf"\g<1>{title} &middot; Network Football Elo", html)
        html = re.sub(r'(<meta name="twitter:description" content=")[^"]*', rf"\g<1>{description}", html)
        target = output / path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        urls.append(canonical)
    (output / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{url}</loc></url>\n" for url in urls)
        + "</urlset>\n",
        encoding="utf-8",
    )


def build_fixtures(source: Path, output: Any) -> dict[str, Any]:
    path = source / "upcoming_fixtures.json"
    if not path.exists():
        return {"checked_at": None, "source": None, "fixtures": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    state = output.state
    index = {code: position for position, code in enumerate(state["codes"])}
    count = len(state["codes"])
    covariance = state["covariance"]
    current = {team["code"]: team for team in output.summary["teams"]}
    fixtures = []
    results_through = str(output.summary["meta"]["results_through"])
    for fixture in payload.get("fixtures", []):
        # A feed can continue advertising a fixture after the completed result
        # has entered another source. Results always take precedence.
        if str(fixture.get("date", "")) <= results_through:
            continue
        first = fixture.get("team1_code")
        second = fixture.get("team2_code")
        if first not in index or second not in index:
            continue
        i, j = index[first], index[second]
        year = int(str(fixture["date"])[:4])
        scale = calibration_scale(year)
        difference = scale * (float(state["means"][i]) - float(state["means"][j]))
        difference += home_advantage(year) * int(fixture.get("home_sign", 0))
        variance = max(
            0.0,
            float(
                covariance[i * count + i]
                + covariance[j * count + j]
                - 2.0 * covariance[i * count + j]
            ),
        )
        network_probabilities = three_way_probabilities(
            difference,
            variance,
            year,
            friendly=fixture.get("tournament_code") == "F",
        )
        year_value, month_value, day_value = (
            int(value) for value in str(fixture["date"]).split("-")
        )
        forecast_day = year_value * 400 + month_value * 32 + day_value
        probabilities = forecast_from_snapshot(
            snapshot=state["forecast_layer"],
            first=i,
            second=j,
            day=forecast_day,
            expected_score=float(logistic10(difference)),
            nfelo_probabilities=network_probabilities,
            friendly=fixture.get("tournament_code") == "F",
        )
        first_team = current[first]
        second_team = current[second]
        fixtures.append(
            {
                **fixture,
                "team1_name": first_team["nation"],
                "team2_name": second_team["nation"],
                "rating1": first_team["rating"],
                "rating2": second_team["rating"],
                "combined_rating": first_team["rating"] + second_team["rating"],
                "probabilities": probabilities.tolist(),
            }
        )
    return {
        "checked_at": payload.get("checked_at"),
        "source": payload.get("source"),
        "fixtures": fixtures,
    }


def update_prospective_ledger(
    source: Path,
    fixture_payload: dict[str, Any],
    summary: dict[str, Any],
    state: dict[str, Any],
    generated_at: str,
) -> None:
    """Append the first published forecast for each fixture and model version."""
    path = source / "prospective_forecasts.jsonl"
    existing: set[tuple[str, str]] = set()
    if path.exists():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                existing.add((str(row["fixture_key"]), str(row["model_version"])))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Invalid prospective forecast ledger row {line_number}"
                ) from error
    model_version = str(summary["meta"]["methodology_version"])
    state_sha256 = hashlib.sha256(
        json.dumps(
            compact(state),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    additions: list[str] = []
    for fixture in fixture_payload.get("fixtures", []):
        fixture_key = "|".join(str(fixture.get(key, "")) for key in (
            "date", "team1_code", "team2_code", "tournament_code", "home_sign",
        ))
        identity = (fixture_key, model_version)
        if identity in existing:
            continue
        existing.add(identity)
        additions.append(json.dumps({
            "fixture_key": fixture_key,
            "model_version": model_version,
            "published_at": generated_at,
            "results_through": summary["meta"]["results_through"],
            "source_sha256": summary["meta"]["source_sha256"],
            "state_sha256": state_sha256,
            "date": fixture.get("date"),
            "team1_code": fixture.get("team1_code"),
            "team2_code": fixture.get("team2_code"),
            "team1_name": fixture.get("team1_name"),
            "team2_name": fixture.get("team2_name"),
            "tournament_code": fixture.get("tournament_code"),
            "tournament_name": fixture.get("tournament_name"),
            "home_sign": fixture.get("home_sign"),
            "rating1": fixture.get("rating1"),
            "rating2": fixture.get("rating2"),
            "probabilities": fixture.get("probabilities"),
        }, ensure_ascii=False, separators=(",", ":")))
    if additions:
        path.parent.mkdir(parents=True, exist_ok=True)
        needs_separator = (
            path.exists()
            and path.stat().st_size > 0
            and not path.read_bytes().endswith(b"\n")
        )
        with path.open("a", encoding="utf-8") as handle:
            if needs_separator:
                handle.write("\n")
            handle.write("\n".join(additions))
            handle.write("\n")


def build_ranking_movements(output: Any) -> None:
    """Attach calendar-year rating and rank movement to each current team."""
    results_day = date.fromisoformat(output.summary["meta"]["results_through"])
    try:
        comparison_day = results_day.replace(year=results_day.year - 1)
    except ValueError:
        comparison_day = results_day.replace(
            year=results_day.year - 1, month=2, day=28
        )
    try:
        active_cutoff = comparison_day.replace(year=comparison_day.year - 4)
    except ValueError:
        active_cutoff = comparison_day.replace(
            year=comparison_day.year - 4, month=2, day=28
        )

    past: dict[str, dict[str, Any]] = {}
    for code, page in output.team_pages.items():
        points = [
            point for point in page["history"]
            if point["date"] <= comparison_day.isoformat()
        ]
        if not points:
            continue
        point = points[-1]
        if point["matches"] < 30 or point["date"] < active_cutoff.isoformat():
            continue
        past[code] = point

    past_ranks = {
        code: rank
        for rank, (code, _) in enumerate(
            sorted(
                past.items(),
                key=lambda item: (-item[1]["rating"], item[0]),
            ),
            start=1,
        )
    }
    current_ranks = {
        team["code"]: team["rank"] for team in output.summary["current"]
    }
    for team in output.summary["teams"]:
        point = past.get(team["code"])
        team["movement_date_12m"] = comparison_day.isoformat()
        team["rating_12m"] = None if point is None else point["rating"]
        team["rating_change_12m"] = (
            None if point is None else team["rating"] - point["rating"]
        )
        team["rank_12m"] = past_ranks.get(team["code"])
        team["rank_change_12m"] = (
            past_ranks[team["code"]] - current_ranks[team["code"]]
            if team["code"] in past_ranks and team["code"] in current_ranks
            else None
        )



TOURNAMENT_CATEGORY_ORDER = {
    "Global championships": 0,
    "Continental championships": 1,
    "Nations leagues": 2,
    "Regional championships": 3,
    "Other tournaments": 4,
}


def folded_competition(value: str) -> str:
    normalised = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(
        character for character in normalised
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", ascii_text.casefold()).strip()


def tournament_identity(
    competition: str,
    level: int,
) -> tuple[str, str] | None:
    # Return a display category and stable tournament family name.
    name = re.sub(r"\s+", " ", competition).strip()
    folded = folded_competition(name)

    if not name or level <= 0:
        return None

    qualifier = any(token in folded for token in (
        "qualif",
        "prelim",
        "repechage",
    ))
    if "friendly" in folded or "warm-up" in folded:
        return None

    if folded in {"world cup", "fifa world cup"}:
        return "Global championships", "FIFA World Cup"
    if "olympic" in folded:
        return "Global championships", "Olympic Games"
    if "confederations cup" in folded or "king fahd cup" in folded:
        return "Global championships", "FIFA Confederations Cup"
    if "mundialito" in folded or "world champions gold cup" in folded:
        return "Global championships", "Mundialito"
    if "mini world cup" in folded:
        return "Global championships", "Mini World Cup"
    if "world football cup" in folded:
        return "Global championships", "World Football Cup"
    if "intercontinental championship" in folded:
        return "Global championships", "Intercontinental Championship"
    if "afro-asian cup" in folded:
        return "Global championships", "Afro-Asian Cup"
    if (
        "finalissima" in folded
        or "artemio franchi" in folded
        or "intercontinental cup of nations" in folded
    ):
        return "Global championships", "Intercontinental champions match"

    if not qualifier and (
        "european championship" in folded
        or folded in {"euro", "uefa euro"}
    ):
        return "Continental championships", "UEFA European Championship"
    if not qualifier and (
        "copa america" in folded
        or "south american championship" in folded
    ):
        return "Continental championships", "Copa América"
    if not qualifier and (
        "africa cup of nations" in folded
        or "african cup of nations" in folded
        or folded == "african nations cup"
    ):
        return "Continental championships", "Africa Cup of Nations"
    if "asian challenge cup" in folded:
        return "Continental championships", "AFC Challenge Cup"
    if "asian solidarity cup" in folded:
        return "Continental championships", "AFC Solidarity Cup"
    if not qualifier and "asian cup" in folded:
        return "Continental championships", "AFC Asian Cup"
    if not qualifier and (
        "gold cup" in folded
        or folded == "concacaf championship"
    ):
        return "Continental championships", "CONCACAF Gold Cup"
    if not qualifier and (
        "ofc nations cup" in folded
        or "oceania nations cup" in folded
    ):
        return "Continental championships", "OFC Nations Cup"
    if "panamerican championship" in folded:
        return "Continental championships", "Panamerican Championship"

    if "nations league" in folded and not qualifier:
        if "uefa" in folded or "europe" in folded:
            family = "UEFA Nations League"
        elif "concacaf" in folded:
            family = "CONCACAF Nations League"
        elif "caf" in folded or "afric" in folded:
            family = "CAF Nations League"
        else:
            family = name
        return "Nations leagues", family

    if any(token in folded for token in (
        "asean championship",
        "tiger cup",
        "southeast asian championship",
    )):
        return "Regional championships", "ASEAN Championship"
    if "british championship" in folded or "british home" in folded:
        return "Regional championships", "British Championship"
    if "baltic cup" in folded:
        return "Regional championships", "Baltic Cup"
    if "nordic championship" in folded:
        return "Regional championships", "Nordic Championship"
    if "caribbean cup" in folded:
        return "Regional championships", "Caribbean Cup"
    if "caribbean championship" in folded:
        return "Regional championships", "Caribbean Championship"
    if "central american cup" in folded:
        return "Regional championships", "Central American Cup"
    if "uncaf nations cup" in folded:
        return "Regional championships", "UNCAF Nations Cup"
    if "east asian championship" in folded:
        return "Regional championships", "East Asian Championship"
    if "west asian championship" in folded:
        return "Regional championships", "West Asian Championship"
    if "south asian championship" in folded:
        return "Regional championships", "South Asian Championship"

    regional_tokens = (
        "arab cup",
        "arab nations",
        "gulf cup",
        "asean",
        "aff championship",
        "saff",
        "eaff",
        "waff",
        "cecafa",
        "cosafa",
        "unaf",
        "caribbean cup",
        "central american",
        "baltic cup",
        "british home",
        "british championship",
        "nordic championship",
        "balkan cup",
        "pan american games",
        "pan-arab games",
        "panarab games",
        "panamerican games",
        "asian games",
        "african games",
        "pacific games",
        "mediterranean games",
        "island games",
        "afro-asian",
        "merdeka",
        "king's cup",
        "kings cup",
        "pestabola",
        "south pacific games",
        "indian ocean",
        "east asian championship",
        "west asian championship",
        "south asian championship",
        "central asian",
        "west african",
        "east and central african",
        "cemac",
        "uemoa",
        "ecowas",
        "cedeao",
        "central african",
        "unifac",
        "cccf championship",
        "north american championship",
        "un caf",
        "uncaf",
        "caribbean championship",
    )
    if any(token in folded for token in regional_tokens):
        return "Regional championships", name

    if qualifier or "play-off" in folded or "playoff" in folded:
        return None

    # The source classifies competitive matches above level zero. Once
    # qualifiers and friendlies are excluded, retain remaining named events so
    # historical and less prominent tournaments stay discoverable.
    return "Other tournaments", name


def tournament_family_id(name: str) -> str:
    folded = folded_competition(name)
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:48] or "tournament"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def tolerant_tournament_date(value: str) -> date:
    """Return a sortable date for imperfect historical source dates.

    Some early source rows contain zero months/days or impossible dates
    such as 31 February. Preserve their year/month ordering while
    clamping the day to the nearest valid calendar date.
    """
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if match is None:
        raise ValueError(f"Unsupported tournament date: {value!r}")

    year, month, day = (int(part) for part in match.groups())
    month = min(12, max(1, month))
    day = max(1, day)

    try:
        return date(year, month, day)
    except ValueError:
        next_month = (
            date(year + 1, 1, 1)
            if month == 12
            else date(year, month + 1, 1)
        )
        return next_month - timedelta(days=1)


def split_tournament_editions(
    family: str,
    matches: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    ordered = sorted(matches, key=lambda row: (tolerant_tournament_date(row["date"]), row["id"]))
    if not ordered:
        return []

    nations_league = "nations league" in folded_competition(family)
    editions: list[list[dict[str, Any]]] = [[ordered[0]]]

    for match in ordered[1:]:
        previous = editions[-1][-1]
        previous_day = tolerant_tournament_date(previous["date"])
        current_day = tolerant_tournament_date(match["date"])
        gap = (current_day - previous_day).days

        if nations_league:
            edition_first = tolerant_tournament_date(editions[-1][0]["date"])
            edition_span = (previous_day - edition_first).days
            new_season = (
                (
                    previous_day.month <= 7
                    and current_day.month >= 8
                    and gap > 45
                )
                or (
                    edition_span > 300
                    and current_day.year > previous_day.year
                    and gap > 120
                )
                or gap > 600
            )
        else:
            new_season = gap > 120

        if new_season:
            editions.append([match])
        else:
            editions[-1].append(match)

    return editions


def tournament_edition_label(
    first: date,
    last: date,
    same_year_editions: int,
) -> str:
    if first.year != last.year:
        if last.year == first.year + 1:
            return f"{first.year}–{str(last.year)[-2:]}"
        return f"{first.year}–{last.year}"
    if same_year_editions > 1:
        return f"{first.strftime('%B')} {first.year}"
    return str(first.year)


def build_tournament_catalog(matches: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for match in matches:
        identity = tournament_identity(
            str(match.get("t", "")),
            int(match.get("level", 0)),
        )
        if identity is None:
            continue
        grouped.setdefault(identity, []).append(match)

    families: list[dict[str, Any]] = []
    for (category, family), family_matches in grouped.items():
        clusters = split_tournament_editions(family, family_matches)
        same_year_counts: Counter[int] = Counter()
        bounds: list[tuple[date, date, list[dict[str, Any]]]] = []

        for cluster in clusters:
            first = min(tolerant_tournament_date(row["date"]) for row in cluster)
            last = max(tolerant_tournament_date(row["date"]) for row in cluster)
            bounds.append((first, last, cluster))
            if first.year == last.year:
                same_year_counts[first.year] += 1

        editions = []
        family_id = tournament_family_id(family)
        for first, last, cluster in bounds:
            participants = sorted({
                code
                for row in cluster
                for code in (row["a"], row["b"])
            })
            label = tournament_edition_label(
                first,
                last,
                same_year_counts[first.year],
            )
            if len(participants) < 3 and category == "Other tournaments":
                continue
            editions.append({
                "id": f"{family_id}-{first.isoformat()}-{last.isoformat()}",
                "label": label,
                "start": first.isoformat(),
                "end": last.isoformat(),
                "before": (first - timedelta(days=1)).isoformat(),
                "after": last.isoformat(),
                "teams": participants,
                "matches": len(cluster),
            })

        editions.sort(key=lambda row: (row["after"], row["start"]), reverse=True)
        if not editions:
            continue
        families.append({
            "id": family_id,
            "name": family,
            "category": category,
            "editions": editions,
        })

    families.sort(key=lambda row: (
        TOURNAMENT_CATEGORY_ORDER.get(row["category"], 99),
        row["name"].casefold(),
    ))
    categories = [
        category
        for category, _ in sorted(
            TOURNAMENT_CATEGORY_ORDER.items(),
            key=lambda item: item[1],
        )
        if any(family["category"] == category for family in families)
    ]
    return {
        "categories": categories,
        "families": families,
    }


def build_historical_rankings(data: Path, output: Any) -> None:
    """Write independently loadable end-of-day ranking events for each year."""
    names = {team["code"]: team["nation"] for team in output.summary["teams"]}
    preferred_historical_names = {"Soviet Union": "USSR"}
    events_by_year: dict[int, list[dict[str, Any]]] = {}
    for code, page in output.team_pages.items():
        for point in page["history"]:
            year = int(point["date"][:4])
            events_by_year.setdefault(year, []).append(
                {
                    "id": point["id"], "date": point["date"], "code": code,
                    "nation": preferred_historical_names.get(
                        point.get("historical_name", names[code]),
                        point.get("historical_name", names[code]),
                    ),
                    "rating": point["rating"],
                    "mean": point["mean"], "se": point["se"],
                    "latent": point["latent"],
                    "reliability": point["reliability"],
                    "score_state": point["score_state"],
                    "matches": point["matches"], "form": point["form"],
                }
            )

    matchdays_by_year: dict[int, set[str]] = {}
    for match in output.matches:
        year = int(match["year"])
        matchdays_by_year.setdefault(year, set()).add(match["date"])

    matches_by_day_team: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for match in output.matches:
        matches_by_day_team.setdefault((match["date"], match["a"]), []).append(match)
        matches_by_day_team.setdefault((match["date"], match["b"]), []).append(match)

    first_date, last_date = output.matches[0]["date"], output.matches[-1]["date"]
    contexts_by_year: dict[int, list[dict[str, Any]]] = {}
    for item in output.prediction_contexts:
        contexts_by_year.setdefault(int(item["date"][:4]), []).append(item)
    opening_context: dict[str, Any] | None = None
    opening: dict[str, dict[str, Any]] = {}
    number_ones: list[dict[str, Any]] = []
    years = []
    for year in range(int(first_date[:4]), int(last_date[:4]) + 1):
        rows = sorted(events_by_year.get(year, []), key=lambda row: (row["date"], row["id"], row["code"]))
        filename = f"{year}.json"
        year_contexts = contexts_by_year.get(year, [])
        write_json(data / "rankings-history" / filename, {
            "year": year, "opening": list(opening.values()), "events": rows,
            "matchdays": sorted(matchdays_by_year.get(year, set())),
            "opening_prediction_context": opening_context,
            "prediction_contexts": year_contexts,
        })
        if year_contexts:
            opening_context = year_contexts[-1]
        years.append({"year": year, "file": filename, "events": len(rows)})
        daily_rows: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            daily_rows.setdefault(row["date"], []).append(row)
        for day, day_rows in daily_rows.items():
            ratings_before = {
                code: row["rating"] for code, row in opening.items()
            }
            for row in day_rows:
                opening[row["code"]] = {
                    key: value for key, value in row.items() if key != "id"
                }
            eligible = [row for row in opening.values() if row["matches"] >= 30]
            if not eligible:
                continue
            leader = max(eligible, key=lambda row: (row["rating"], row["code"]))
            previous = number_ones[-1] if number_ones else None
            changed_team = previous is None or previous["code"] != leader["code"]
            changed_name = previous is not None and previous["nation"] != leader["nation"]
            if changed_team or changed_name:
                if previous is not None:
                    previous["to"] = (
                        date.fromisoformat(day) - timedelta(days=1)
                    ).isoformat()
                incoming_matches = matches_by_day_team.get(
                    (day, leader["code"]), []
                )
                outgoing_matches = (
                    matches_by_day_team.get((day, previous["code"]), [])
                    if previous is not None and changed_team
                    else []
                )
                incoming_before = ratings_before.get(leader["code"])
                incoming_gain = (
                    float("inf")
                    if incoming_before is None
                    else leader["rating"] - incoming_before
                )
                outgoing_drop = float("-inf")
                if previous is not None and previous["code"] in ratings_before:
                    outgoing_after = opening.get(previous["code"])
                    if outgoing_after is not None:
                        outgoing_drop = (
                            ratings_before[previous["code"]]
                            - outgoing_after["rating"]
                        )
                # Attribute the change to the result that contributed most to
                # reversing the gap: the incoming team's rise or the outgoing
                # leader's fall. This avoids crediting an incoming team that
                # actually lost while the previous No. 1 fell even further.
                if outgoing_matches and outgoing_drop > incoming_gain:
                    trigger_matches = outgoing_matches
                elif incoming_matches:
                    trigger_matches = incoming_matches
                else:
                    trigger_matches = outgoing_matches
                trigger_matches = sorted(trigger_matches, key=lambda row: row["id"])
                trigger_rows = [{
                    "id": trigger["id"],
                    "team1_code": trigger["a"],
                    "team2_code": trigger["b"],
                    "team1": trigger["an"],
                    "team2": trigger["bn"],
                    "score1": trigger["sa"],
                    "score2": trigger["sb"],
                    "competition": trigger["t"],
                } for trigger in trigger_matches]
                number_ones.append({
                    "code": leader["code"],
                    "nation": leader["nation"],
                    "from": day,
                    "to": None,
                    "rating": leader["rating"],
                    "displaced_code": previous["code"] if changed_team and previous else None,
                    "displaced": previous["nation"] if changed_team and previous else None,
                    "matches": trigger_rows,
                    "match": trigger_rows[0] if len(trigger_rows) == 1 else None,
                })

    for spell in number_ones:
        effective_end = spell["to"] or last_date
        spell["days"] = (
            date.fromisoformat(effective_end) - date.fromisoformat(spell["from"])
        ).days + 1
    output.summary["number_ones"] = list(reversed(number_ones))
    number_one_summary: dict[str, dict[str, Any]] = {}
    for spell in number_ones:
        row = number_one_summary.setdefault(spell["code"], {
            "code": spell["code"],
            "nation": names[spell["code"]],
            "first": spell["from"],
            "latest": spell["to"] or last_date,
            "current": False,
            "spells": 0,
            "days": 0,
        })
        row["first"] = min(row["first"], spell["from"])
        row["latest"] = max(row["latest"], spell["to"] or last_date)
        row["current"] = row["current"] or spell["to"] is None
        row["spells"] += 1
        row["days"] += spell["days"]
    output.summary["number_one_summary"] = sorted(
        number_one_summary.values(),
        key=lambda row: (-row["days"], row["first"], row["nation"]),
    )

    write_json(data / "rankings-history" / "index.json", {
        "first": first_date,
        "last": last_date,
        "years": years,
    })
    write_json(
        data / "tournaments" / "index.json",
        build_tournament_catalog(output.matches),
    )


def main() -> None:
    args = parse_args()
    output = run_replay(args.source, args.config)
    data = args.output / "data"
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)

    status_path = args.source / "status.json"
    status = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.exists()
        else {"mode": "bundled snapshot", "source_checked_at": None}
    )
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output.summary["meta"]["generated_at"] = generated_at
    output.summary["meta"]["source_update"] = status

    build_historical_rankings(data, output)
    build_ranking_movements(output)
    write_json(data / "summary.json", output.summary)
    write_json(data / "state.json", output.state)
    fixtures = build_fixtures(args.source, output)
    write_json(data / "fixtures.json", fixtures)
    update_prospective_ledger(
        args.source,
        fixtures,
        output.summary,
        output.state,
        generated_at,
    )

    decades: dict[int, list[dict[str, Any]]] = {}
    for match in output.matches:
        decade = int(match["year"]) // 10 * 10
        decades.setdefault(decade, []).append(match)
    match_index = []
    for decade in sorted(decades):
        rows = decades[decade]
        filename = f"{decade}.json"
        write_json(data / "matches" / filename, {"matches": rows})
        match_index.append(
            {
                "decade": decade,
                "file": filename,
                "count": len(rows),
                "first": rows[0]["date"],
                "last": rows[-1]["date"],
            }
        )
    write_json(data / "matches" / "index.json", {"decades": match_index})
    write_json(data / "matches" / "search.json", {
        "matches": [
            {
                "id": match["id"], "date": match["date"], "year": match["year"],
                "a": match["a"], "b": match["b"], "an": match["an"], "bn": match["bn"],
                "ac": match["ac"], "bc": match["bc"], "t": match["t"],
                "level": match["level"], "decade": int(match["year"]) // 10 * 10,
            }
            for match in output.matches
        ]
    })

    for code, page in output.team_pages.items():
        write_json(data / "teams" / f"{code}.json", page)

    tournament_counts = Counter(match["tc"] for match in output.matches)
    write_json(
        data / "catalog.json",
        {
            "teams": [
                {"code": team["code"], "name": team["nation"]}
                for team in output.summary["teams"]
            ],
            "tournaments": [
                {
                    "code": code,
                    "name": next(
                        (match["t"] for match in output.matches if match["tc"] == code),
                        code,
                    ),
                    "matches": count,
                }
                for code, count in sorted(
                    tournament_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        },
    )

    version_browser_assets(args.output)
    write_route_entries(args.output, output.summary)
    (args.output / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copyfile(args.config / "404.html", args.output / "404.html")
    manifest_files = [
        path
        for path in sorted(args.output.rglob("*"))
        if path.is_file() and path.name != "build-manifest.json"
    ]
    manifest = {
        "generated_at": generated_at,
        "results_through": output.summary["meta"]["results_through"],
        "matches": output.summary["meta"]["matches"],
        "files": {
            str(path.relative_to(args.output)): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in manifest_files
        },
    }
    write_json(args.output / "build-manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": "ok",
                "results_through": manifest["results_through"],
                "matches": manifest["matches"],
                "files": len(manifest_files),
            }
        )
    )


if __name__ == "__main__":
    main()
