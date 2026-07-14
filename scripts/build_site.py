#!/usr/bin/env python3
"""Replay the published model and write compact static JSON for GitHub Pages."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
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

    (args.output / ".nojekyll").write_text("", encoding="utf-8")
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
