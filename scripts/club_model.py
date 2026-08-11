#!/usr/bin/env python3
"""Scalable hierarchical Elo model for the global club ledger.

This is deliberately independent of the national-team full-covariance model.
Domestic matches move club residuals; cross-border matches also move a club's
association coefficient, which is the bridge that makes ratings from separate
league systems globally comparable.  All forecasts are pre-match and all
same-date updates are frozen before that date's results are applied.
"""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import date
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Iterable, Iterator

import duckdb


RATED_FIELDS = (
    "match_id", "day", "season", "home", "away", "home_goals", "away_goals",
    "competition", "competition_key", "kind", "home_tier", "away_tier",
    "neutral", "cross_border", "status", "leg", "tie_key", "round_name",
    "source", "source_ref", "aggregate_before_home", "aggregate_after_home",
    "aggregate_weight", "evidence_weight", "pre_home_mean", "pre_away_mean",
    "pre_home_rating", "pre_away_rating", "pre_home_se", "pre_away_se",
    "home_probability", "draw_probability", "away_probability", "model_score",
    "rating_delta", "post_home_mean", "post_away_mean", "post_home_rating",
    "post_away_rating", "post_home_se", "post_away_se", "surprise",
)


def load_club_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "base_rating", "k_factor", "home_advantage_domestic",
        "home_advantage_cross_border", "draw_peak", "margin_scale",
        "season_retention", "association_retention", "association_share",
        "tier_gap", "extra_time_weight", "penalty_weight", "aggregate_floor",
        "aggregate_scale", "effective_matches_half_life_days", "club_prior_sd",
        "association_prior_sd", "uncertainty_penalty", "competition_weights",
    }
    missing = required - value.keys()
    if missing:
        raise ValueError(f"Club model config is missing {sorted(missing)}")
    if not 0.0 <= float(value["association_share"]) <= 1.0:
        raise ValueError("association_share must be between zero and one")
    if not 0.0 <= float(value["aggregate_floor"]) <= 1.0:
        raise ValueError("aggregate_floor must be between zero and one")
    return value


def logistic10(difference: float) -> float:
    exponent = max(-12.0, min(12.0, -difference / 400.0))
    return 1.0 / (1.0 + 10.0**exponent)


def three_way_probabilities(difference: float, draw_peak: float) -> tuple[float, float, float]:
    expected = logistic10(difference)
    draw = draw_peak * 4.0 * expected * (1.0 - expected)
    home = expected - 0.5 * draw
    away = 1.0 - expected - 0.5 * draw
    floor = 1e-12
    total = max(floor, home) + max(floor, draw) + max(floor, away)
    return max(floor, home) / total, max(floor, draw) / total, max(floor, away) / total


def aggregate_leg_weight(
    before_home: int | None,
    after_home: int | None,
    floor: float,
    scale: float,
    score: float | None = None,
) -> float:
    """Information retained by a second leg given aggregate jeopardy.

    A tie close before or after the second leg has full leverage.  A controlled
    loss in a tie that remains clearly won has little leverage, but never less
    than ``floor``.  Using both states means a genuine comeback remains fully
    informative even if it began from a large deficit.
    """
    if before_home is None or after_home is None:
        return 1.0
    # Aggregate context is a safeguard against the specific strategic case in
    # which the club still winning the tie accepts a second-leg loss.  It must
    # not suppress confirming evidence when the aggregate winner also wins the
    # leg, nor a comeback that changes which club is ahead.
    if before_home == 0 or after_home == 0 or before_home * after_home < 0:
        return 1.0
    if score is not None:
        aggregate_score = 1.0 if after_home > 0 else 0.0
        if (score - 0.5) * (aggregate_score - 0.5) >= 0.0:
            return 1.0
    scale = max(0.05, scale)
    leverage = max(
        math.exp(-abs(before_home) / scale),
        math.exp(-abs(after_home) / scale),
    )
    return floor + (1.0 - floor) * leverage


def margin_multiplier(margin: int, scale: float) -> float:
    if margin <= 1:
        return 1.0
    return 1.0 + scale * math.log1p(margin - 1)


@dataclass
class ClubMeta:
    club: int
    code: str
    name: str
    country: str
    country_name: str
    country_code: str
    continent: str
    resolution: str


class ClubRatingModel:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        config: dict[str, Any],
        *,
        write_tables: bool,
        output_connection: duckdb.DuckDBPyConnection | None = None,
        replay_from: str | None = None,
        evaluation_start: str | None = None,
        evaluation_end: str | None = None,
    ) -> None:
        self.connection = connection
        self.config = config
        self.write_tables = write_tables
        self.output_connection = output_connection
        if write_tables and output_connection is None:
            raise ValueError("write_tables requires a separate output connection")
        self.replay_from = replay_from
        self.evaluation_start = evaluation_start
        self.evaluation_end = evaluation_end
        club_rows = connection.execute(
            """
            SELECT club,code,name,country,country_name,country_code,continent,resolution
            FROM clubs ORDER BY club
            """
        ).fetchall()
        self.clubs = [ClubMeta(*row) for row in club_rows]
        size = len(self.clubs)
        self.residual = [0.0] * size
        self.effective = [0.0] * size
        self.last_day = [-1] * size
        self.last_year = [-1] * size
        self.last_tier = [1] * size
        self.initialised = [False] * size
        self.matches_played = [0] * size
        self.first_day = [-1] * size
        self.last_match_day = [-1] * size
        countries = sorted({club.country for club in self.clubs if club.country})
        self.association_index = {country: index for index, country in enumerate(countries)}
        self.association_rating = [0.0] * len(countries)
        self.association_effective = [0.0] * len(countries)
        self.association_last_day = [-1] * len(countries)
        self.association_last_year = [-1] * len(countries)
        self.association_matches = [0] * len(countries)
        self.recent_second_leg = [-100_000] * size
        self.recent_controlled_second_leg = [-100_000] * size
        self.metrics: dict[str, list[float]] = {
            "all": [0.0, 0.0, 0.0, 0.0],
            "post_tie": [0.0, 0.0, 0.0, 0.0],
            "post_controlled_tie": [0.0, 0.0, 0.0, 0.0],
            "second_leg": [0.0, 0.0, 0.0, 0.0],
        }
        self.minimum_day = 0
        if replay_from:
            self.minimum_day = date.fromisoformat(replay_from).toordinal()
        self.eval_first = date.min.toordinal() if evaluation_start is None else date.fromisoformat(evaluation_start).toordinal()
        self.eval_last = date.max.toordinal() if evaluation_end is None else date.fromisoformat(evaluation_end).toordinal()

    def _association(self, club: int) -> int | None:
        country = self.clubs[club].country
        return self.association_index.get(country)

    def _project_association(self, association: int | None, year: int) -> None:
        if association is None:
            return
        previous = self.association_last_year[association]
        if previous < 0:
            self.association_last_year[association] = year
        elif year > previous:
            self.association_rating[association] *= float(self.config["association_retention"]) ** (year - previous)
            self.association_last_year[association] = year

    def _project_club(self, club: int, year: int, tier: int) -> None:
        prior = -(max(1, tier) - 1) * float(self.config["tier_gap"])
        if not self.initialised[club]:
            self.residual[club] = prior
            self.last_year[club] = year
            self.last_tier[club] = tier
            self.initialised[club] = True
            return
        previous = self.last_year[club]
        if year > previous:
            self.residual[club] = prior + float(self.config["season_retention"]) ** (
                year - previous
            ) * (self.residual[club] - prior)
            self.last_year[club] = year
        self.last_tier[club] = tier

    def _decay(self, value: float, previous_day: int, day: int) -> float:
        if previous_day < 0 or day <= previous_day:
            return value
        half_life = float(self.config["effective_matches_half_life_days"])
        return value * 0.5 ** ((day - previous_day) / half_life)

    def _club_effective(self, club: int, day: int) -> float:
        return self._decay(self.effective[club], self.last_day[club], day)

    def _association_effective(self, association: int | None, day: int) -> float:
        if association is None:
            return 0.0
        return self._decay(
            self.association_effective[association],
            self.association_last_day[association],
            day,
        )

    def mean(self, club: int) -> float:
        association = self._association(club)
        association_value = 0.0 if association is None else self.association_rating[association]
        return float(self.config["base_rating"]) + self.residual[club] + association_value

    def uncertainty(self, club: int, day: int) -> float:
        association = self._association(club)
        club_information = self._club_effective(club, day)
        association_information = self._association_effective(association, day)
        club_sd = float(self.config["club_prior_sd"]) / math.sqrt(1.0 + club_information / 6.0)
        association_sd = float(self.config["association_prior_sd"]) / math.sqrt(
            1.0 + association_information / 4.0
        )
        return math.hypot(club_sd, association_sd)

    def public_rating(self, club: int, day: int) -> float:
        return self.mean(club) - float(self.config["uncertainty_penalty"]) * self.uncertainty(club, day)

    def _home_advantage(self, cross_border: bool, neutral: bool) -> float:
        if neutral:
            return 0.0
        key = "home_advantage_cross_border" if cross_border else "home_advantage_domestic"
        return float(self.config[key])

    def _evidence_weight(
        self,
        kind: str,
        status: str,
        aggregate_weight: float,
    ) -> float:
        competition = float(self.config["competition_weights"].get(kind, 1.0))
        duration = 1.0
        if status == "E":
            duration = float(self.config["extra_time_weight"])
        elif status == "P":
            duration = float(self.config["penalty_weight"])
        return competition * duration * aggregate_weight

    @staticmethod
    def _score(home_goals: int, away_goals: int, status: str) -> float:
        if status == "P" or home_goals == away_goals:
            return 0.5
        return 1.0 if home_goals > away_goals else 0.0

    @staticmethod
    def _outcome_probability(
        score: float,
        home_probability: float,
        draw_probability: float,
        away_probability: float,
    ) -> float:
        if score == 1.0:
            return home_probability
        if score == 0.0:
            return away_probability
        return draw_probability

    def _record_metric(self, bucket: str, probability: float, probabilities: tuple[float, float, float], score: float) -> None:
        values = self.metrics[bucket]
        values[0] += -math.log(max(1e-15, probability))
        outcome = (1.0, 0.0, 0.0) if score == 1.0 else ((0.0, 0.0, 1.0) if score == 0.0 else (0.0, 1.0, 0.0))
        values[1] += sum((predicted - observed) ** 2 for predicted, observed in zip(probabilities, outcome))
        values[2] += 1.0 if probabilities.index(max(probabilities)) == outcome.index(max(outcome)) else 0.0
        values[3] += 1.0

    def _create_output_tables(self) -> None:
        assert self.output_connection is not None
        target = self.output_connection
        target.execute("DROP TABLE IF EXISTS rated_matches")
        target.execute(
            """
            CREATE TABLE rated_matches(
                match_id VARCHAR, day DATE, season INTEGER, home INTEGER, away INTEGER,
                home_goals SMALLINT, away_goals SMALLINT, competition VARCHAR,
                competition_key VARCHAR, kind VARCHAR, home_tier SMALLINT,
                away_tier SMALLINT, neutral BOOLEAN, cross_border BOOLEAN,
                status VARCHAR, leg SMALLINT, tie_key VARCHAR, round_name VARCHAR,
                source VARCHAR, source_ref VARCHAR, aggregate_before_home SMALLINT,
                aggregate_after_home SMALLINT, aggregate_weight DOUBLE,
                evidence_weight DOUBLE, pre_home_mean DOUBLE, pre_away_mean DOUBLE,
                pre_home_rating DOUBLE, pre_away_rating DOUBLE, pre_home_se DOUBLE,
                pre_away_se DOUBLE, home_probability DOUBLE, draw_probability DOUBLE,
                away_probability DOUBLE, model_score DOUBLE, rating_delta DOUBLE,
                post_home_mean DOUBLE, post_away_mean DOUBLE, post_home_rating DOUBLE,
                post_away_rating DOUBLE, post_home_se DOUBLE, post_away_se DOUBLE,
                surprise DOUBLE
            )
            """
        )
        target.execute("DROP TABLE IF EXISTS year_openings")
        target.execute(
            """
            CREATE TABLE year_openings(
                year INTEGER, club INTEGER, mean DOUBLE, rating DOUBLE, se DOUBLE,
                last_match_day INTEGER, matches INTEGER, tier SMALLINT
            )
            """
        )

    def _bulk_copy(self, table: str, rows: Iterable[tuple[Any, ...]]) -> int:
        assert self.output_connection is not None
        target = self.output_connection
        count = 0
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="",
            dir=Path(target.execute("PRAGMA database_list").fetchone()[2]).parent,
            prefix=f".{table}-", delete=False,
        ) as handle:
            path = Path(handle.name)
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            for row in rows:
                writer.writerow([r"\N" if value is None else value for value in row])
                count += 1
        if count == 0:
            path.unlink(missing_ok=True)
            return 0
        try:
            target.execute(
                f"COPY {table} FROM ? (FORMAT CSV, DELIM '\\t', HEADER false, NULLSTR '\\N')",
                [str(path)],
            ).fetchall()
        finally:
            path.unlink(missing_ok=True)
        return count

    def _opening_rows(self, year: int, day: int) -> Iterator[tuple[Any, ...]]:
        for club in range(len(self.clubs)):
            if not self.initialised[club]:
                continue
            yield (
                year, club, self.mean(club), self.public_rating(club, day),
                self.uncertainty(club, day), self.last_match_day[club],
                self.matches_played[club], self.last_tier[club],
            )

    def _match_query(self) -> str:
        condition = ""
        if self.replay_from:
            condition = f"WHERE day >= DATE '{self.replay_from}'"
        return f"""
            SELECT match_id,cast(day as varchar),season,home,away,home_goals,away_goals,
                   competition,competition_key,kind,home_tier,away_tier,neutral,
                   cross_border,status,leg,tie_key,round_name,source,source_ref,
                   aggregate_before_home,aggregate_after_home
            FROM matches {condition} ORDER BY day,match_id
        """

    def replay(self) -> dict[str, Any]:
        if self.write_tables:
            self._create_output_tables()
        # The immutable ledger is streamed from one database while all derived
        # rows are appended to a separate model database.  DuckDB otherwise
        # (correctly) waits for a long read cursor before accepting a write.
        cursor = self.connection.execute(self._match_query())
        current_day: str | None = None
        day_rows: list[tuple[Any, ...]] = []
        rated_buffer: list[tuple[Any, ...]] = []
        previous_year: int | None = None
        processed = 0

        def flush_rated() -> None:
            if self.write_tables and rated_buffer:
                self._bulk_copy("rated_matches", rated_buffer)
                rated_buffer.clear()

        def process_day(rows: list[tuple[Any, ...]]) -> None:
            nonlocal previous_year, processed
            if not rows:
                return
            day_text = rows[0][1]
            ordinal = date.fromisoformat(day_text).toordinal()
            year = int(day_text[:4])
            if self.write_tables and previous_year != year:
                opening_day = date(year, 1, 1).toordinal()
                self._bulk_copy("year_openings", self._opening_rows(year, opening_day))
                previous_year = year

            club_changes: defaultdict[int, float] = defaultdict(float)
            club_information: defaultdict[int, float] = defaultdict(float)
            association_changes: defaultdict[int, float] = defaultdict(float)
            association_information: defaultdict[int, float] = defaultdict(float)
            temporary: list[dict[str, Any]] = []
            for row in rows:
                (
                    match_id, _, season, home, away, home_goals, away_goals,
                    competition, competition_key, kind, home_tier, away_tier,
                    neutral, cross_border, status, leg, tie_key, round_name,
                    source, source_ref, aggregate_before, aggregate_after,
                ) = row
                home, away = int(home), int(away)
                home_tier, away_tier = int(home_tier), int(away_tier)
                self._project_club(home, year, home_tier)
                self._project_club(away, year, away_tier)
                home_association = self._association(home)
                away_association = self._association(away)
                self._project_association(home_association, year)
                self._project_association(away_association, year)
                pre_home_mean = self.mean(home)
                pre_away_mean = self.mean(away)
                home_se = self.uncertainty(home, ordinal)
                away_se = self.uncertainty(away, ordinal)
                home_rating = pre_home_mean - float(self.config["uncertainty_penalty"]) * home_se
                away_rating = pre_away_mean - float(self.config["uncertainty_penalty"]) * away_se
                difference = pre_home_mean - pre_away_mean + self._home_advantage(
                    bool(cross_border), bool(neutral)
                )
                probabilities = three_way_probabilities(difference, float(self.config["draw_peak"]))
                expected = logistic10(difference)
                score = self._score(int(home_goals), int(away_goals), str(status))
                aggregate_weight = aggregate_leg_weight(
                    integer_or_none(aggregate_before), integer_or_none(aggregate_after),
                    float(self.config["aggregate_floor"]), float(self.config["aggregate_scale"]),
                    score,
                )
                evidence = self._evidence_weight(str(kind), str(status), aggregate_weight)
                margin = 0 if str(status) == "P" else abs(int(home_goals) - int(away_goals))
                movement = float(self.config["k_factor"]) * evidence * margin_multiplier(
                    margin, float(self.config["margin_scale"])
                ) * (score - expected)
                if bool(cross_border) and home_association is not None and away_association is not None and home_association != away_association:
                    share = float(self.config["association_share"])
                    club_changes[home] += (1.0 - share) * movement
                    club_changes[away] -= (1.0 - share) * movement
                    association_changes[home_association] += share * movement
                    association_changes[away_association] -= share * movement
                    association_information[home_association] += evidence * share
                    association_information[away_association] += evidence * share
                else:
                    club_changes[home] += movement
                    club_changes[away] -= movement
                club_information[home] += evidence
                club_information[away] += evidence
                probability = self._outcome_probability(score, *probabilities)
                if self.eval_first <= ordinal <= self.eval_last:
                    self._record_metric("all", probability, probabilities, score)
                    if ordinal - max(self.recent_second_leg[home], self.recent_second_leg[away]) <= 120:
                        self._record_metric("post_tie", probability, probabilities, score)
                    if ordinal - max(
                        self.recent_controlled_second_leg[home],
                        self.recent_controlled_second_leg[away],
                    ) <= 120:
                        self._record_metric(
                            "post_controlled_tie", probability, probabilities, score
                        )
                    if int(leg) == 2 and aggregate_before is not None:
                        self._record_metric("second_leg", probability, probabilities, score)
                temporary.append({
                    "base": row,
                    "ordinal": ordinal,
                    "home": home,
                    "away": away,
                    "pre_home_mean": pre_home_mean,
                    "pre_away_mean": pre_away_mean,
                    "home_rating": home_rating,
                    "away_rating": away_rating,
                    "home_se": home_se,
                    "away_se": away_se,
                    "probabilities": probabilities,
                    "score": score,
                    "movement": movement,
                    "aggregate_weight": aggregate_weight,
                    "evidence": evidence,
                    "surprise": -math.log(max(1e-15, probability)),
                })

            for club, change in club_changes.items():
                self.residual[club] += change
                decayed = self._club_effective(club, ordinal)
                self.effective[club] = decayed + club_information[club]
                self.last_day[club] = ordinal
            for association, change in association_changes.items():
                self.association_rating[association] += change
                decayed = self._association_effective(association, ordinal)
                self.association_effective[association] = decayed + association_information[association]
                self.association_last_day[association] = ordinal
                self.association_matches[association] += 1
            for item in temporary:
                home, away = item["home"], item["away"]
                for club in (home, away):
                    self.matches_played[club] += 1
                    self.first_day[club] = ordinal if self.first_day[club] < 0 else min(self.first_day[club], ordinal)
                    self.last_match_day[club] = max(self.last_match_day[club], ordinal)
                row = item["base"]
                if int(row[15]) == 2 and row[20] is not None:
                    self.recent_second_leg[home] = ordinal
                    self.recent_second_leg[away] = ordinal
                    before = integer_or_none(row[20])
                    after = integer_or_none(row[21])
                    if (
                        before is not None and after is not None
                        and before * after > 0 and abs(before) >= 2
                        and (item["score"] - 0.5)
                        * ((1.0 if after > 0 else 0.0) - 0.5) < 0.0
                    ):
                        self.recent_controlled_second_leg[home] = ordinal
                        self.recent_controlled_second_leg[away] = ordinal
                if self.write_tables:
                    post_home_mean, post_away_mean = self.mean(home), self.mean(away)
                    post_home_se, post_away_se = self.uncertainty(home, ordinal), self.uncertainty(away, ordinal)
                    rated_buffer.append((
                        row[0], row[1], row[2], home, away, row[5], row[6], row[7], row[8], row[9],
                        row[10], row[11], row[12], row[13], row[14], row[15], row[16], row[17], row[18],
                        row[19], row[20], row[21], item["aggregate_weight"], item["evidence"],
                        item["pre_home_mean"], item["pre_away_mean"], item["home_rating"],
                        item["away_rating"], item["home_se"], item["away_se"],
                        item["probabilities"][0], item["probabilities"][1], item["probabilities"][2],
                        item["score"], item["movement"], post_home_mean, post_away_mean,
                        post_home_mean - float(self.config["uncertainty_penalty"]) * post_home_se,
                        post_away_mean - float(self.config["uncertainty_penalty"]) * post_away_se,
                        post_home_se, post_away_se, item["surprise"],
                    ))
                    if len(rated_buffer) >= 25_000:
                        flush_rated()
                processed += 1

        while True:
            batch = cursor.fetchmany(50_000)
            if not batch:
                break
            for row in batch:
                if current_day is None:
                    current_day = row[1]
                if row[1] != current_day:
                    process_day(day_rows)
                    day_rows.clear()
                    current_day = row[1]
                day_rows.append(row)
        process_day(day_rows)
        flush_rated()
        if self.write_tables:
            self._write_current_tables()
            self._deduplicate_output_tables(processed)
            assert self.output_connection is not None
        return self.summary(processed)

    def _deduplicate_output_tables(self, expected_matches: int) -> None:
        """Defend derived tables against a repeated bulk-copy result batch."""
        assert self.output_connection is not None
        target = self.output_connection
        for table, keys in (
            ("rated_matches", "match_id"),
            ("year_openings", "year,club"),
            ("current_club_ratings", "club"),
            ("current_association_ratings", "country"),
        ):
            clean = f"{table}_unique"
            target.execute(f"DROP TABLE IF EXISTS {clean}")
            target.execute(
                f"CREATE TABLE {clean} AS "
                f"SELECT * FROM {table} QUALIFY "
                f"row_number() OVER (PARTITION BY {keys})=1"
            )
            target.execute(f"DROP TABLE {table}")
            target.execute(f"ALTER TABLE {clean} RENAME TO {table}")
        stored = int(target.execute("SELECT count(*) FROM rated_matches").fetchone()[0])
        if stored != expected_matches:
            raise RuntimeError(
                f"club model wrote {stored:,} unique matches; expected {expected_matches:,}"
            )
        target.execute(
            "CREATE UNIQUE INDEX rated_matches_match_id_unique "
            "ON rated_matches(match_id)"
        )
        target.execute(
            "CREATE UNIQUE INDEX year_openings_year_club_unique "
            "ON year_openings(year,club)"
        )
        target.execute(
            "CREATE UNIQUE INDEX current_club_ratings_club_unique "
            "ON current_club_ratings(club)"
        )
        target.execute(
            "CREATE UNIQUE INDEX current_association_ratings_country_unique "
            "ON current_association_ratings(country)"
        )

    def _write_current_tables(self) -> None:
        assert self.output_connection is not None
        target = self.output_connection
        target.execute("DROP TABLE IF EXISTS current_club_ratings")
        target.execute(
            """
            CREATE TABLE current_club_ratings(
                club INTEGER,mean DOUBLE,rating DOUBLE,se DOUBLE,matches INTEGER,
                first_day INTEGER,last_day INTEGER,tier SMALLINT
            )
            """
        )
        maximum = self.connection.execute("SELECT max(day) FROM matches").fetchone()[0]
        ordinal = maximum.toordinal()
        rows = []
        for club in range(len(self.clubs)):
            if not self.initialised[club]:
                continue
            rows.append((
                club, self.mean(club), self.public_rating(club, ordinal),
                self.uncertainty(club, ordinal), self.matches_played[club],
                self.first_day[club], self.last_match_day[club], self.last_tier[club],
            ))
        self._bulk_copy("current_club_ratings", rows)
        target.execute("DROP TABLE IF EXISTS current_association_ratings")
        target.execute(
            """
            CREATE TABLE current_association_ratings(
                country VARCHAR,rating DOUBLE,se DOUBLE,international_updates INTEGER
            )
            """
        )
        inverse = sorted(self.association_index, key=self.association_index.get)
        association_rows = []
        for index, country in enumerate(inverse):
            se = float(self.config["association_prior_sd"]) / math.sqrt(
                1.0 + self._association_effective(index, ordinal) / 4.0
            )
            association_rows.append((country, self.association_rating[index], se, self.association_matches[index]))
        self._bulk_copy("current_association_ratings", association_rows)

    def summary(self, processed: int) -> dict[str, Any]:
        metrics = {}
        for name, values in self.metrics.items():
            count = int(values[3])
            metrics[name] = {
                "matches": count,
                "log_loss": None if not count else values[0] / count,
                "brier": None if not count else values[1] / count,
                "accuracy": None if not count else values[2] / count,
            }
        return {
            "matches": processed,
            "clubs": sum(self.initialised),
            "associations": len(self.association_index),
            "metrics": metrics,
        }


def integer_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def run_club_model(
    database: Path,
    config: dict[str, Any],
    *,
    write_tables: bool = True,
    output_database: Path | None = None,
    replay_from: str | None = None,
    evaluation_start: str | None = None,
    evaluation_end: str | None = None,
) -> dict[str, Any]:
    connection = duckdb.connect(str(database), read_only=True)
    output_connection: duckdb.DuckDBPyConnection | None = None
    if write_tables:
        output_database = output_database or database.with_name("club-model.duckdb")
        output_database.parent.mkdir(parents=True, exist_ok=True)
        output_database.unlink(missing_ok=True)
        output_connection = duckdb.connect(str(output_database))
    result: dict[str, Any] | None = None
    transaction_open = False
    try:
        if output_connection is not None:
            output_connection.execute("BEGIN TRANSACTION")
            transaction_open = True
        model = ClubRatingModel(
            connection, config, write_tables=write_tables,
            output_connection=output_connection, replay_from=replay_from,
            evaluation_start=evaluation_start, evaluation_end=evaluation_end,
        )
        result = model.replay()
        if output_database is not None:
            result["model_database"] = str(output_database)
        if output_connection is not None:
            output_connection.execute("COMMIT")
            transaction_open = False
            output_connection.execute("CHECKPOINT").fetchall()
    except Exception:
        if output_connection is not None and transaction_open:
            output_connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
        if output_connection is not None:
            output_connection.close()
    assert result is not None
    if write_tables and output_database is not None:
        verifier = duckdb.connect(str(output_database), read_only=True)
        try:
            tables = {str(row[0]) for row in verifier.execute("SHOW TABLES").fetchall()}
            required = {
                "rated_matches", "year_openings", "current_club_ratings",
                "current_association_ratings",
            }
            if not required.issubset(tables):
                raise RuntimeError(
                    "club model persistence check failed; missing "
                    + ", ".join(sorted(required - tables))
                )
            stored = int(verifier.execute("SELECT count(*) FROM rated_matches").fetchone()[0])
            if stored != int(result["matches"]):
                raise RuntimeError(
                    f"club model reopened {stored:,} matches; "
                    f"expected {int(result['matches']):,}"
                )
        finally:
            verifier.close()
    return result


__all__ = [
    "ClubRatingModel",
    "aggregate_leg_weight",
    "load_club_config",
    "logistic10",
    "margin_multiplier",
    "run_club_model",
    "three_way_probabilities",
]
