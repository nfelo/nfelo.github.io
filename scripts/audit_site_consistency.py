#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any


EXPECTED_ROUTES = (
    "rankings",
    "history",
    "tournaments",
    "matches",
    "fixtures",
    "records",
    "compare",
    "predict",
    "methodology",
    "faq",
    "about",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def close(first: Any, second: Any, tolerance: float = 1e-6) -> bool:
    if first is None or second is None:
        return first is second
    return math.isclose(
        float(first),
        float(second),
        rel_tol=0.0,
        abs_tol=tolerance,
    )


def historical_snapshot(
    public: Path,
    index: dict[str, Any],
    value: str,
    cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    chosen = max(index["first"], min(index["last"], value))
    data_year = str(
        min(int(chosen[:4]), int(index["last"][:4]))
    )
    if data_year not in cache:
        cache[data_year] = load_json(
            public
            / "data"
            / "rankings-history"
            / f"{data_year}.json"
        )
    payload = cache[data_year]
    state = {
        team["code"]: dict(team)
        for team in payload["opening"]
    }
    for event in payload.get("events", []):
        if event["date"] <= chosen:
            state[event["code"]] = dict(event)
    chosen_year = int(chosen[:4])
    ranked = [
        team
        for team in state.values()
        if chosen_year - int(team["date"][:4]) <= 4
    ]
    ranked.sort(
        key=lambda team: (
            -float(team["rating"]),
            team["nation"],
        )
    )
    for position, team in enumerate(ranked, start=1):
        team["rank"] = position
    return ranked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--public",
        type=Path,
        default=Path("public"),
    )
    args = parser.parse_args()
    public = args.public

    summary = load_json(public / "data" / "summary.json")
    catalog = load_json(public / "data" / "catalog.json")
    tournament_index = load_json(
        public / "data" / "tournaments" / "index.json"
    )
    history_index = load_json(
        public
        / "data"
        / "rankings-history"
        / "index.json"
    )
    fixtures = load_json(public / "data" / "fixtures.json")

    all_teams = summary["teams"]
    team_codes = [team["code"] for team in all_teams]
    assert len(team_codes) == len(set(team_codes))
    by_code = {team["code"]: team for team in all_teams}
    current_codes = {
        team["code"] for team in summary["current"]
    }
    assert current_codes <= set(by_code)

    history_cache: dict[str, dict[str, Any]] = {}
    latest_date = summary["meta"]["results_through"]
    latest = historical_snapshot(
        public,
        history_index,
        latest_date,
        history_cache,
    )
    latest_by_code = {
        team["code"]: team for team in latest
    }
    current_by_code = {
        team["code"]: team
        for team in summary["current"]
    }

    # Current Rankings and the latest History view use the same
    # eligibility rule, so membership must agree. Their displayed
    # rating values are intentionally not compared: History stores
    # each matchday's contemporary reference context, while Current
    # Rankings recomputes the final state in the current reference
    # context.
    assert set(latest_by_code) == set(current_by_code), {
        "history_only": sorted(
            set(latest_by_code) - set(current_by_code)
        ),
        "current_only": sorted(
            set(current_by_code) - set(latest_by_code)
        ),
    }

    expected_current = sorted(
        summary["current"],
        key=lambda team: (
            -float(team["rating"]),
            team["nation"],
        ),
    )
    assert [
        team["code"] for team in summary["current"]
    ] == [
        team["code"] for team in expected_current
    ], "Current Rankings are not sorted by rating and name."
    assert [
        team["rank"] for team in summary["current"]
    ] == list(
        range(1, len(summary["current"]) + 1)
    ), "Current Rankings have inconsistent rank numbers."

    assert [
        team["rank"] for team in latest
    ] == list(
        range(1, len(latest) + 1)
    ), "Latest History has inconsistent rank numbers."
    assert [
        team["code"] for team in latest
    ] == [
        team["code"]
        for team in sorted(
            latest,
            key=lambda team: (
                -float(team["rating"]),
                team["nation"],
            ),
        )
    ], "Latest History is not sorted by rating and historical name."

    # Every latest History row must be the same stored matchday
    # point exposed on that team's dynamic page.
    latest_team_pages: dict[str, dict[str, Any]] = {}
    for code, historical in latest_by_code.items():
        page_path = (
            public / "data" / "teams" / f"{code}.json"
        )
        assert page_path.exists(), page_path
        page = load_json(page_path)
        latest_team_pages[code] = page
        points = [
            point
            for point in page.get("history", [])
            if point["date"] <= latest_date
        ]
        assert points, (
            code,
            "missing team history through latest date",
        )
        point = points[-1]
        for key in (
            "date",
            "rating",
            "mean",
            "se",
            "latent",
            "reliability",
            "matches",
            "form",
        ):
            if key in ("rating", "mean", "se", "latent", "reliability"):
                assert close(
                    historical.get(key),
                    point.get(key),
                ), (code, "history", key)
            else:
                assert historical.get(key) == point.get(key), (
                    code,
                    "history",
                    key,
                )

    for code, summary_team in by_code.items():
        page_path = public / "data" / "teams" / f"{code}.json"
        assert page_path.exists(), page_path
        page_team = load_json(page_path)["team"]
        assert page_team["code"] == code
        assert page_team["nation"] == summary_team["nation"]
        for key in ("rating", "mean", "se", "rank", "matches"):
            if key in page_team and key in summary_team:
                assert close(
                    page_team[key],
                    summary_team[key],
                ), (code, key)

    editions: dict[tuple[str, str], dict[str, Any]] = {}
    for family in tournament_index["families"]:
        for edition in family["editions"]:
            key = (family["id"], edition["id"])
            assert key not in editions
            editions[key] = {
                **edition,
                "family_name": family["name"],
            }
            participant_codes = edition["teams"]
            assert len(participant_codes) == len(
                set(participant_codes)
            )
            assert set(participant_codes) <= set(by_code)
            participants = edition.get("participants", [])
            assert {
                participant["code"] for participant in participants
            } == set(participant_codes)
            changes = edition.get("rating_changes", [])
            assert {
                item["code"] for item in changes
            } == set(participant_codes)
            for item in changes:
                if item["change"] is None:
                    assert item["start_rating"] is None
                    assert item["end_rating"] is None
                else:
                    assert close(
                        float(item["end_rating"])
                        - float(item["start_rating"]),
                        item["change"],
                    )

    best = summary.get("best_tournaments", [])
    assert len(best) <= 500
    assert all(
        float(first["rating_gain"])
        >= float(second["rating_gain"])
        for first, second in zip(best, best[1:])
    )
    for row in best:
        assert row["code"] in by_code
        edition = editions[
            (row["tournament_id"], row["edition_id"])
        ]
        assert row["tournament"] == edition["family_name"]
        assert row["edition"] == edition["label"]
        for key in ("start", "end", "before", "after"):
            assert row[key] == edition[key], (
                row["code"],
                row["tournament"],
                row["edition"],
                key,
            )
        change_by_code = {
            item["code"]: item
            for item in edition.get("rating_changes", [])
        }
        change = change_by_code[row["code"]]
        assert close(
            row["before_rating"],
            change["start_rating"],
        )
        assert close(
            row["after_rating"],
            change["end_rating"],
        )
        assert close(
            row["rating_gain"],
            change["change"],
        )
        assert int(row["tournament_matches"]) == int(
            change["matches"]
        )
        assert close(
            float(row["after_rating"])
            - float(row["before_rating"]),
            row["rating_gain"],
        )

    for row in summary.get("peaks", []):
        assert row["code"] in by_code
        assert row["date"] <= latest_date
    for collection, code_keys in (
        ("top_matches", ("code1", "code2")),
        ("upsets", ("code1", "code2")),
    ):
        for row in summary.get(collection, []):
            assert all(row[key] in by_code for key in code_keys)
            assert row["date"] <= latest_date

    for fixture in fixtures.get("fixtures", []):
        first = by_code[fixture["team1_code"]]
        second = by_code[fixture["team2_code"]]
        assert fixture["team1_name"] == first["nation"]
        assert fixture["team2_name"] == second["nation"]
        assert close(fixture["rating1"], first["rating"])
        assert close(fixture["rating2"], second["rating"])
        assert close(
            fixture["combined_rating"],
            float(first["rating"]) + float(second["rating"]),
        )

    catalog_codes = {
        item["code"] for item in catalog.get("teams", [])
    }
    if catalog_codes:
        assert catalog_codes <= set(by_code)

    root_html = (
        public / "index.html"
    ).read_text(encoding="utf-8")
    root_nav = re.search(
        r'<nav id="site-nav".*?</nav>',
        root_html,
        flags=re.DOTALL,
    )
    assert root_nav
    nav_html = root_nav.group(0)
    root_assets = tuple(
        re.findall(
            r'(?:href|src)="(assets/(?:styles\.css|app\.js)'
            r'(?:\?v=[^"]+)?)"',
            root_html,
        )
    )
    assert len(root_assets) == 2
    sitemap = (
        public / "sitemap.xml"
    ).read_text(encoding="utf-8")

    for route in EXPECTED_ROUTES:
        route_path = public / route / "index.html"
        assert route_path.exists(), route_path
        html = route_path.read_text(encoding="utf-8")
        route_nav = re.search(
            r'<nav id="site-nav".*?</nav>',
            html,
            flags=re.DOTALL,
        )
        assert route_nav
        assert route_nav.group(0) == nav_html
        route_assets = tuple(
            re.findall(
                r'(?:href|src)="(assets/(?:styles\.css|app\.js)'
                r'(?:\?v=[^"]+)?)"',
                html,
            )
        )
        assert route_assets == root_assets
        canonical = f"https://nfelo.github.io/{route}/"
        assert (
            f'<link rel="canonical" href="{canonical}">'
            in html
        )
        assert f"<loc>{canonical}</loc>" in sitemap

    javascript = (
        public / "assets" / "app.js"
    ).read_text(encoding="utf-8")
    stylesheet = (
        public / "assets" / "styles.css"
    ).read_text(encoding="utf-8")
    for marker in (
        "summary.current",
        "summary.best_tournaments",
        "year - Number(team.date.slice(0, 4)) <= 4",
        "loadHistoricalSnapshot",
        'getJSON("data/tournaments/index.json")',
        'getJSON("data/fixtures.json")',
        'getJSON(`data/teams/${encodeURIComponent(code)}.json`)',
    ):
        assert marker in javascript
    assert not re.search(
        r'\.hide-mobile\s*\{[^}]*display\s*:\s*none',
        stylesheet,
        flags=re.DOTALL,
    )

    print(
        "Site consistency audit passed: Rankings, History, "
        "Tournaments, Records, Fixtures, team pages, clean "
        "routes and mobile data all use the same build."
    )


if __name__ == "__main__":
    main()
