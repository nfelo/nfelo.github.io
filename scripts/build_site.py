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
from typing import Any

from model import (
    calibration_scale,
    home_advantage,
    run_replay,
    three_way_probabilities,
)


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
        "matches": ("Matches", "Search international football results and pre-match forecasts from 1872 onward."),
        "fixtures": ("Upcoming matches", "Upcoming senior internationals with current ratings and match probabilities."),
        "records": ("Records", "All-time national-team rating peaks, greatest matchups and largest upsets."),
        "predict": ("Predict a match", "Compare two national teams and calculate win, draw and loss probabilities."),
        "methodology": ("Methodology", "Detailed, reproducible methodology for the Network Football Elo model."),
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
        html = re.sub(r"<title>.*?</title>", f"<title>{title} · Network Football Elo</title>", html)
        html = re.sub(r'(<meta name="description" content=")[^"]*', rf"\g<1>{description}", html)
        html = re.sub(r'(<link rel="canonical" href=")[^"]*', rf"\g<1>{canonical}", html)
        html = re.sub(r'(<meta property="og:title" content=")[^"]*', rf"\g<1>{title} · Network Football Elo", html)
        html = re.sub(r'(<meta property="og:description" content=")[^"]*', rf"\g<1>{description}", html)
        html = re.sub(r'(<meta property="og:url" content=")[^"]*', rf"\g<1>{canonical}", html)
        html = re.sub(r'(<meta name="twitter:title" content=")[^"]*', rf"\g<1>{title} · Network Football Elo", html)
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
    for fixture in payload.get("fixtures", []):
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
        probabilities = three_way_probabilities(
            difference,
            variance,
            year,
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
                    "matches": point["matches"], "form": point["form"],
                }
            )

    matchdays_by_year: dict[int, set[str]] = {}
    world_cup_days: dict[int, list[str]] = {}
    for match in output.matches:
        year = int(match["year"])
        matchdays_by_year.setdefault(year, set()).add(match["date"])
        if match["t"] in {"World Cup", "FIFA World Cup"}:
            world_cup_days.setdefault(year, []).append(match["date"])

    first_date, last_date = output.matches[0]["date"], output.matches[-1]["date"]
    opening: dict[str, dict[str, Any]] = {}
    years = []
    for year in range(int(first_date[:4]), int(last_date[:4]) + 1):
        rows = sorted(events_by_year.get(year, []), key=lambda row: (row["date"], row["id"], row["code"]))
        filename = f"{year}.json"
        write_json(data / "rankings-history" / filename, {
            "year": year, "opening": list(opening.values()), "events": rows,
            "matchdays": sorted(matchdays_by_year.get(year, set())),
        })
        years.append({"year": year, "file": filename, "events": len(rows)})
        for row in rows:
            opening[row["code"]] = {key: value for key, value in row.items() if key != "id"}

    world_cups = []
    for year, days in sorted(world_cup_days.items(), reverse=True):
        first, last = min(days), max(days)
        world_cups.append({
            "year": year,
            "before": (date.fromisoformat(first) - timedelta(days=1)).isoformat(),
            "after": last,
        })
    write_json(data / "rankings-history" / "index.json", {
        "first": first_date, "last": last_date, "years": years, "world_cups": world_cups,
    })


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

    write_json(data / "summary.json", output.summary)
    write_json(data / "state.json", output.state)
    write_json(data / "fixtures.json", build_fixtures(args.source, output))

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

    build_historical_rankings(data, output)

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
