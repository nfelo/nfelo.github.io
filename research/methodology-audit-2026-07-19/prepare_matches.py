#!/usr/bin/env python3
"""Write the repository's canonical ledger as a compact numeric audit file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-successors", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo / "scripts"))
    from ledger import read_matches, read_successors
    from tournament_classification import (
        load_registry,
        read_evidence,
        runtime_is_friendly,
        validate_registry,
    )

    source = args.repo / "source"
    successors = {} if args.no_successors else read_successors(source / "teams.tsv")
    matches = read_matches(
        source / "elo_pages",
        successors,
        source / "supplemental_results.csv",
    )
    teams = sorted({match.team1 for match in matches} | {match.team2 for match in matches})
    team_index = {team: index for index, team in enumerate(teams)}
    config = args.repo / "config"
    levels = json.loads((config / "elo_matches.json").read_text(encoding="utf-8"))[
        "tournament_levels"
    ]
    registry = load_registry(config / "tournament_classification.json")
    validate_registry(registry)
    evidence_path = config / "tournament_evidence.json"
    evidence = read_evidence(evidence_path if evidence_path.exists() else None)
    names: dict[str, str] = {}
    for line in (source / "en.tournaments.tsv").read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0]:
            names[fields[0]] = fields[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        handle.write(f"# teams={len(teams)} matches={len(matches)}\n")
        for match_id, match in enumerate(matches):
            level = int(levels.get(match.tournament, 0 if match.tournament == "F" else 1))
            friendly = runtime_is_friendly(
                match.tournament,
                match.date_text,
                registry,
                aliases=(names.get(match.tournament, match.tournament),),
                level=level,
                evidence=evidence.get(match.tournament),
            )
            fields = (
                match_id,
                match.day,
                match.year,
                match.month,
                match.day_of_month,
                team_index[match.team1],
                team_index[match.team2],
                match.score1,
                match.score2,
                match.home_sign,
                int(friendly),
                level,
                match.official_pre1,
                match.official_pre2,
            )
            handle.write("\t".join(str(value) for value in fields) + "\n")
    (args.output.with_suffix(args.output.suffix + ".teams.json")).write_text(
        json.dumps(teams, indent=2) + "\n", encoding="utf-8"
    )
    print(f"matches={len(matches)} teams={len(teams)} output={args.output}")


if __name__ == "__main__":
    main()
