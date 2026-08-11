#!/usr/bin/env python3
"""Build the independent global-club ratings section and static data archive."""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

import duckdb

from club_ledger import build_club_ledger
from club_model import load_club_config, run_club_model
from club_sources import ensure_runtime_sources


ACTIVE_DAYS = 550
MATCH_SCHEMA = [
    "id", "date", "home", "away", "home_goals", "away_goals",
    "competition", "kind", "home_tier", "away_tier", "neutral",
    "cross_border", "status", "leg", "tie_key",
    "aggregate_before_home", "aggregate_after_home", "aggregate_weight",
    "evidence_weight", "pre_home_rating", "pre_away_rating",
    "post_home_rating", "post_away_rating", "home_probability",
    "draw_probability", "away_probability", "home_rating_delta",
    "surprise", "source", "source_ref", "round",
]
HISTORY_SCHEMA = [
    "rank", "club", "rating", "mean", "standard_error", "matches", "tier",
    "last_match",
]
ANNUAL_SCHEMA = [
    "year", "rating", "mean", "standard_error", "matches", "tier",
]


def rounded(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    return value


def ordinal_date(value: int | None) -> str | None:
    if value is None or int(value) < 1:
        return None
    return date.fromordinal(int(value)).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def attach_model(connection: duckdb.DuckDBPyConnection, model: Path) -> None:
    escaped = str(model.resolve()).replace("'", "''")
    connection.execute(f"ATTACH '{escaped}' AS model (READ_ONLY)")


def match_array(row: tuple[Any, ...]) -> list[Any]:
    values = list(row)
    values[1] = str(values[1])
    for position in (17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27):
        values[position] = (
            None if values[position] is None else rounded(float(values[position]))
        )
    values[10] = 1 if values[10] else 0
    values[11] = 1 if values[11] else 0
    return values


def _match_select(extra: str = "") -> str:
    return f"""
        SELECT r.match_id,r.day,h.code,a.code,r.home_goals,r.away_goals,
               r.competition,r.kind,r.home_tier,r.away_tier,r.neutral,
               r.cross_border,r.status,r.leg,r.tie_key,
               r.aggregate_before_home,r.aggregate_after_home,r.aggregate_weight,
               r.evidence_weight,r.pre_home_rating,r.pre_away_rating,
               r.post_home_rating,r.post_away_rating,r.home_probability,
               r.draw_probability,r.away_probability,r.rating_delta,r.surprise,
               r.source,r.source_ref,r.round_name
        FROM model.rated_matches r
        JOIN clubs h ON h.club=r.home
        JOIN clubs a ON a.club=r.away
        {extra}
    """


def export_club_site(
    ledger: Path,
    model: Path,
    source: Path,
    config_dir: Path,
    output: Path,
    runtime_manifest: dict[str, Any],
    ledger_summary: dict[str, Any],
    model_summary: dict[str, Any],
) -> dict[str, Any]:
    """Export a replay to compact, traceable static files."""
    root = output / "clubs"
    data = root / "data"
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)

    config = load_club_config(config_dir / "club_model.json")
    connection = duckdb.connect(str(ledger), read_only=True)
    attach_model(connection, model)
    try:
        maximum_day = int(
            connection.execute(
                "SELECT max(last_day) FROM model.current_club_ratings"
            ).fetchone()[0]
        )
        active_after = maximum_day - ACTIVE_DAYS
        current_rows = connection.execute(
            """
            SELECT c.club,c.code,c.name,c.country,c.country_name,c.country_code,
                   c.continent,c.identity,c.resolution,r.mean,r.rating,r.se,
                   r.matches,r.first_day,r.last_day,r.tier
            FROM model.current_club_ratings r JOIN clubs c USING(club)
            ORDER BY c.club
            """
        ).fetchall()

        clubs_by_id: dict[int, dict[str, Any]] = {}
        for row in current_rows:
            club = {
                "code": row[1],
                "name": row[2],
                "country": row[3],
                "country_name": row[4],
                "country_code": row[5],
                "continent": row[6] or "Unassigned",
                "identity": row[7],
                "resolution": row[8],
                "mean": rounded(float(row[9]), 2),
                "rating": rounded(float(row[10]), 2),
                "se": rounded(float(row[11]), 2),
                "matches": int(row[12]),
                "first": ordinal_date(int(row[13])),
                "last": ordinal_date(int(row[14])),
                "tier": int(row[15]),
                "active": int(row[14]) >= active_after,
                "provisional": int(row[12]) < 30,
            }
            clubs_by_id[int(row[0])] = club

        active = sorted(
            (club for club in clubs_by_id.values() if club["active"]),
            key=lambda club: (-float(club["rating"]), str(club["name"]), str(club["code"])),
        )
        for rank, club in enumerate(active, start=1):
            club["rank"] = rank

        all_clubs = sorted(
            clubs_by_id.values(),
            key=lambda club: (str(club["name"]).casefold(), str(club["country"]), str(club["code"])),
        )
        club_catalog = [
            {
                key: club[key]
                for key in (
                    "code", "name", "country", "country_name", "country_code",
                    "continent", "rating", "mean", "se", "matches", "first",
                    "last", "tier", "active", "provisional",
                )
            }
            for club in all_clubs
        ]
        write_json(data / "rankings.json", {"active_days": ACTIVE_DAYS, "clubs": active})
        write_json(data / "clubs.json", {"clubs": club_catalog})

        association_rows = connection.execute(
            """
            SELECT a.country,coalesce(max(c.country_name),replace(a.country,'-',' ')),
                   coalesce(max(c.country_code),''),coalesce(max(c.continent),'Unassigned'),
                   a.rating,a.se,a.international_updates
            FROM model.current_association_ratings a
            LEFT JOIN clubs c USING(country)
            GROUP BY a.country,a.rating,a.se,a.international_updates
            ORDER BY a.rating DESC,a.country
            """
        ).fetchall()
        associations = [
            {
                "rank": rank,
                "country": row[0],
                "name": str(row[1]).title() if not row[2] else row[1],
                "code": row[2],
                "continent": row[3],
                "coefficient": rounded(float(row[4]), 2),
                "index": rounded(float(config["base_rating"]) + float(row[4]), 2),
                "se": rounded(float(row[5]), 2),
                "cross_border_updates": int(row[6]),
            }
            for rank, row in enumerate(association_rows, start=1)
        ]
        write_json(data / "associations.json", {"associations": associations})

        opening_rows = connection.execute(
            """
            SELECT y.year,y.club,y.mean,y.rating,y.se,y.last_match_day,y.matches,y.tier
            FROM model.year_openings y ORDER BY y.year,y.club
            """
        ).fetchall()
        annual_by_club: dict[int, list[list[Any]]] = defaultdict(list)
        eligible_by_year: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
        for row in opening_rows:
            year, club_id = int(row[0]), int(row[1])
            if club_id not in clubs_by_id:
                continue
            annual_by_club[club_id].append(
                [
                    year, rounded(float(row[3]), 2), rounded(float(row[2]), 2),
                    rounded(float(row[4]), 2), int(row[6]), int(row[7]),
                ]
            )
            opening_ordinal = date(year, 1, 1).toordinal()
            if int(row[5]) >= opening_ordinal - ACTIVE_DAYS:
                eligible_by_year[year].append(row)

        history_index: list[dict[str, Any]] = []
        number_ones: list[dict[str, Any]] = []
        for year in sorted(eligible_by_year):
            rows = sorted(
                eligible_by_year[year],
                key=lambda row: (-float(row[3]), clubs_by_id[int(row[1])]["name"]),
            )
            values = []
            for rank, row in enumerate(rows, start=1):
                values.append(
                    [
                        rank, clubs_by_id[int(row[1])]["code"],
                        rounded(float(row[3]), 2), rounded(float(row[2]), 2),
                        rounded(float(row[4]), 2), int(row[6]), int(row[7]),
                        ordinal_date(int(row[5])),
                    ]
                )
            write_json(data / "history" / f"{year}.json", {"year": year, "rankings": values})
            history_index.append({"year": year, "clubs": len(values), "file": f"{year}.json"})
            if values:
                leader = clubs_by_id[int(rows[0][1])]
                number_ones.append(
                    {"year": year, "club": leader["code"], "name": leader["name"], "rating": values[0][2]}
                )
        write_json(
            data / "history" / "index.json",
            {"schema": HISTORY_SCHEMA, "active_days": ACTIVE_DAYS, "years": history_index},
        )

        match_year_rows = connection.execute(
            """
            SELECT club,year(day) year_value,count(*) matches FROM (
                SELECT home club,day FROM matches
                UNION ALL SELECT away,day FROM matches
            ) GROUP BY club,year_value ORDER BY club,year_value
            """
        ).fetchall()
        years_by_club: dict[int, list[list[int]]] = defaultdict(list)
        for club_id, year, matches in match_year_rows:
            years_by_club[int(club_id)].append([int(year), int(matches)])

        def write_club_detail(item: tuple[int, dict[str, Any]]) -> None:
            club_id, club = item
            write_json(
                data / "club" / f"{club['code']}.json",
                {
                    "club": club,
                    "annual_schema": ANNUAL_SCHEMA,
                    "annual": annual_by_club.get(club_id, []),
                    "match_years": years_by_club.get(club_id, []),
                },
            )

        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as executor:
            list(executor.map(write_club_detail, clubs_by_id.items()))

        years = [
            int(row[0])
            for row in connection.execute(
                "SELECT distinct year(day) FROM model.rated_matches ORDER BY 1"
            ).fetchall()
        ]
        match_index: list[dict[str, Any]] = []
        archive_query = _match_select(
            "WHERE year(r.day)=? ORDER BY r.day,r.match_id"
        )
        for year in years:
            rows = connection.execute(archive_query, [year]).fetchall()
            values = [match_array(row) for row in rows]
            write_json(data / "matches" / f"{year}.json", {"year": year, "matches": values})
            match_index.append(
                {
                    "year": year,
                    "count": len(values),
                    "first": values[0][1],
                    "last": values[-1][1],
                    "file": f"{year}.json",
                }
            )
            print(f"club site: exported {year} ({len(values):,} matches)")
        write_json(
            data / "matches" / "index.json",
            {"schema": MATCH_SCHEMA, "years": match_index},
        )

        coverage_rows = connection.execute(
            """
            SELECT competition_key,competition,kind,matches,first_date,last_date,
                   club_sides,sources FROM competition_coverage
            ORDER BY matches DESC,competition
            """
        ).fetchall()
        competitions = [
            {
                "key": row[0], "name": row[1], "kind": row[2],
                "matches": int(row[3]), "first": str(row[4]), "last": str(row[5]),
                "club_sides": int(row[6]), "sources": list(row[7]),
            }
            for row in coverage_rows
        ]
        write_json(data / "competitions.json", {"competitions": competitions})

        source_coverage_rows = connection.execute(
            """
            SELECT source,count(*),min(day),max(day),count(distinct competition_key)
            FROM matches GROUP BY source ORDER BY count(*) DESC
            """
        ).fetchall()
        kind_rows = connection.execute(
            "SELECT kind,count(*) FROM matches GROUP BY kind ORDER BY count(*) DESC"
        ).fetchall()
        tier_rows = connection.execute(
            """
            SELECT greatest(home_tier,away_tier) tier,count(*)
            FROM matches GROUP BY 1 ORDER BY 1
            """
        ).fetchall()

        peak_rows = connection.execute(
            """
            WITH points AS (
                SELECT home club,day,post_home_rating rating FROM model.rated_matches
                UNION ALL
                SELECT away club,day,post_away_rating rating FROM model.rated_matches
            ), peaks AS (
                SELECT club,max(rating) rating,arg_max(day,rating) peak_day FROM points GROUP BY club
            )
            SELECT c.code,c.name,c.country_name,p.rating,p.peak_day
            FROM peaks p JOIN clubs c USING(club)
            ORDER BY p.rating DESC,c.name LIMIT 250
            """
        ).fetchall()
        peaks = [
            {"club": r[0], "name": r[1], "country": r[2], "rating": rounded(float(r[3]), 2), "date": str(r[4])}
            for r in peak_rows
        ]
        strongest = [
            match_array(row)
            for row in connection.execute(
                _match_select("ORDER BY r.pre_home_rating+r.pre_away_rating DESC LIMIT 250")
            ).fetchall()
        ]
        upsets = [
            match_array(row)
            for row in connection.execute(
                _match_select("ORDER BY r.surprise DESC LIMIT 250")
            ).fetchall()
        ]
        aggregate_examples = [
            match_array(row)
            for row in connection.execute(
                _match_select(
                    "WHERE r.leg=2 AND r.aggregate_weight<0.999999 "
                    "ORDER BY r.aggregate_weight,r.day DESC LIMIT 250"
                )
            ).fetchall()
        ]
        write_json(
            data / "records.json",
            {
                "match_schema": MATCH_SCHEMA,
                "peaks": peaks,
                "strongest_matches": strongest,
                "upsets": upsets,
                "aggregate_examples": aggregate_examples,
                "year_opening_number_ones": number_ones,
            },
        )

        brazil_manifest_path = source / "club_brazil.manifest.json"
        brazil_manifest = (
            json.loads(brazil_manifest_path.read_text(encoding="utf-8"))
            if brazil_manifest_path.exists() else None
        )
        brazil_states_manifest_path = source / "club_brazil_states.manifest.json"
        brazil_states_manifest = (
            json.loads(brazil_states_manifest_path.read_text(encoding="utf-8"))
            if brazil_states_manifest_path.exists() else None
        )
        sources = {
            "discovery_index": {
                "name": "Sabino football-statistics research sources",
                "url": "https://docs.ufpr.br/~mmsabino/sstatistics/fontes_pesquisa.html",
                "role": "Discovery and corroboration index; not parsed by the unattended build.",
            },
            "runtime": runtime_manifest,
            "brazil": brazil_manifest,
            "brazil_states": brazil_states_manifest,
            "coverage": [
                {
                    "source": row[0], "matches": int(row[1]), "first": str(row[2]),
                    "last": str(row[3]), "competitions": int(row[4]),
                }
                for row in source_coverage_rows
            ],
            "additional_research": [
                {"name": "RSSSF", "url": "https://www.rsssf.org/", "role": "Historical corroboration and gap discovery"},
                {"name": "OpenFootball", "url": "https://openfootball.github.io/", "role": "Open-format corroboration and future ingestion candidate"},
            ],
            "limitations": [
                "Coverage is broad, not literally complete: lower tiers, state competitions, early cups, and some confederations remain uneven.",
                "A club identity is kept separate when legal or sporting succession is genuinely ambiguous.",
                "Mutable upstream feeds are hash-recorded on every build; historical corrections can change a later replay without refitting coefficients.",
                "Penalty-shootout-decided matches are learned as regulation/extra-time draws; shootout goals are not treated as ordinary goal margin.",
            ],
        }
        write_json(data / "sources.json", sources)

        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        meta = {
            "generated_at": generated_at,
            "model_version": config["version"],
            "results_through": ledger_summary["last"],
            "first_result": ledger_summary["first"],
            "candidate_matches": ledger_summary["raw_matches"],
            "matches": ledger_summary["matches"],
            "deduplicated": ledger_summary["deduplicated"],
            "rated_clubs": len(clubs_by_id),
            "active_clubs": len(active),
            "associations": len(associations),
            "competitions": len(competitions),
            "explicit_second_legs": ledger_summary["explicit_second_legs"],
            "active_days": ACTIVE_DAYS,
            "match_schema": MATCH_SCHEMA,
            "history_schema": HISTORY_SCHEMA,
            "model_metrics": model_summary["metrics"],
            "fit": config.get("fit", {}),
            "parameters": config,
            "coverage": {
                "kinds": {str(key): int(value) for key, value in kind_rows},
                "maximum_tier": max((int(row[0]) for row in tier_rows), default=1),
                "tiers": {str(row[0]): int(row[1]) for row in tier_rows},
                "sources": ledger_summary["sources"],
            },
            "method": {
                "rating": "1500 + club residual + association coefficient - uncertainty penalty",
                "home": "Separate fitted domestic and cross-border home advantages; neutral matches receive zero.",
                "same_date": "Every match on a date is forecast from one frozen start-of-day state, then that date is updated.",
                "aggregate": "Only a controlled second-leg loss by a club that remains ahead on aggregate is discounted; comebacks, level ties, and confirming wins retain full weight.",
            },
        }
        write_json(data / "meta.json", meta)
        write_json(
            data / "bootstrap.json",
            {
                "meta": {key: meta[key] for key in (
                    "generated_at", "model_version", "results_through", "first_result",
                    "matches", "rated_clubs", "active_clubs", "associations",
                    "competitions", "explicit_second_legs",
                )},
                "top": active[:20],
            },
        )
    finally:
        connection.close()

    version_club_assets(root)
    return meta


def version_club_assets(root: Path) -> None:
    index = root / "index.html"
    if not index.exists():
        raise FileNotFoundError(f"Club application shell is missing: {index}")
    html = index.read_text(encoding="utf-8")
    for asset in ("clubs.css", "clubs.js"):
        revision = sha256_path(root / asset)[:12]
        html = re.sub(
            rf'{re.escape(asset)}(?:\?v=[^"\']*)?',
            f"{asset}?v={revision}",
            html,
        )
    index.write_text(html, encoding="utf-8")


def build_club_site(
    source: Path,
    config: Path,
    output: Path,
    cache: Path = Path(".club-cache"),
) -> dict[str, Any]:
    runtime_manifest = ensure_runtime_sources(cache)
    ledger = cache / "club-ledger.duckdb"
    model = cache / "club-model.duckdb"
    ledger_summary = build_club_ledger(ledger, cache, source)
    model_summary = run_club_model(
        ledger,
        load_club_config(config / "club_model.json"),
        output_database=model,
    )
    return export_club_site(
        ledger, model, source, config, output,
        runtime_manifest, ledger_summary, model_summary,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("source"))
    parser.add_argument("--config", type=Path, default=Path("config"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--cache", type=Path, default=Path(".club-cache"))
    parser.add_argument("--reuse-ledger", type=Path)
    parser.add_argument("--reuse-model", type=Path)
    args = parser.parse_args()
    if bool(args.reuse_ledger) != bool(args.reuse_model):
        parser.error("--reuse-ledger and --reuse-model must be provided together")
    if args.reuse_ledger:
        runtime_manifest = json.loads((args.cache / "manifest.json").read_text(encoding="utf-8"))
        connection = duckdb.connect(str(args.reuse_ledger), read_only=True)
        ledger_summary = {
            "raw_matches": int(connection.execute("select count(*) from raw_matches").fetchone()[0]),
            "matches": int(connection.execute("select count(*) from matches").fetchone()[0]),
            "deduplicated": int(connection.execute("select count(*) from raw_matches").fetchone()[0])
            - int(connection.execute("select count(*) from matches").fetchone()[0]),
            "first": str(connection.execute("select min(day) from matches").fetchone()[0]),
            "last": str(connection.execute("select max(day) from matches").fetchone()[0]),
            "explicit_second_legs": int(connection.execute("select count(*) from matches where leg=2 and aggregate_before_home is not null").fetchone()[0]),
            "sources": dict(connection.execute("select source,count(*) from matches group by source").fetchall()),
        }
        connection.close()
        model_connection = duckdb.connect(str(args.reuse_model), read_only=True)
        model_summary = {
            "metrics": {},
            "matches": int(model_connection.execute("select count(*) from rated_matches").fetchone()[0]),
        }
        model_connection.close()
        meta = export_club_site(
            args.reuse_ledger, args.reuse_model, args.source, args.config,
            args.output, runtime_manifest, ledger_summary, model_summary,
        )
    else:
        meta = build_club_site(args.source, args.config, args.output, args.cache)
    print(json.dumps({"status": "ok", **{key: meta[key] for key in ("matches", "rated_clubs", "results_through")}}))


if __name__ == "__main__":
    main()
