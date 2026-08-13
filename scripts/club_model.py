#!/usr/bin/env python3
"""Hierarchical, globally connected Elo model for the competitive club ledger.

The club model is deliberately independent from the national-team covariance
model.  Every forecast is pre-match and every date is processed from one frozen
start-of-day state.  Results update club strength plus at most one real
boundary: domestic tier, association, or confederation.
"""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import date
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
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

CURRENT_TABLES = (
    "current_club_ratings",
    "current_country_ratings",
    "current_confederation_ratings",
)
PERSISTED_TABLES = (
    "rated_matches",
    "year_openings",
    *CURRENT_TABLES,
)

BOUNDARY_KINDS = {"continental", "intercontinental", "global", "super_cup"}
CONFEDERATION_KINDS = {"intercontinental", "global"}


def load_club_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "base_rating", "k_factor", "home_advantage_domestic",
        "home_advantage_cross_border", "draw_peak", "margin_scale",
        "club_retention", "tier_retention", "tier_share", "tier_gap",
        "country_retention", "country_share", "country_anchor_quantile",
        "confederation_retention",
        "confederation_share", "extra_time_weight", "penalty_weight",
        "aggregate_floor", "aggregate_scale",
        "effective_matches_half_life_days", "club_prior_sd", "tier_prior_sd",
        "country_prior_sd", "confederation_prior_sd", "uncertainty_penalty",
        "competition_weights",
    }
    missing = required - value.keys()
    if missing:
        raise ValueError(f"Club model config is missing {sorted(missing)}")
    for key in ("tier_share", "country_share", "confederation_share"):
        if not 0.0 <= float(value[key]) <= 1.0:
            raise ValueError(f"{key} must be between zero and one")
    if not 0.0 <= float(value["aggregate_floor"]) <= 1.0:
        raise ValueError("aggregate_floor must be between zero and one")
    if not 0.5 <= float(value["country_anchor_quantile"]) <= 1.0:
        raise ValueError("country_anchor_quantile must be between 0.5 and one")
    return value


def logistic10(difference: float) -> float:
    exponent = max(-12.0, min(12.0, -difference / 400.0))
    return 1.0 / (1.0 + 10.0**exponent)


def three_way_probabilities(
    difference: float,
    draw_peak: float,
) -> tuple[float, float, float]:
    expected = logistic10(difference)
    draw = draw_peak * 4.0 * expected * (1.0 - expected)
    home = expected - 0.5 * draw
    away = 1.0 - expected - 0.5 * draw
    floor = 1e-12
    total = max(floor, home) + max(floor, draw) + max(floor, away)
    return (
        max(floor, home) / total,
        max(floor, draw) / total,
        max(floor, away) / total,
    )


def aggregate_leg_weight(
    before_home: int | None,
    after_home: int | None,
    floor: float,
    scale: float,
    score: float | None = None,
) -> float:
    """Retain less information only for a controlled loss while still ahead.

    Thus a 4-0 first leg followed by a 0-1 second leg is primarily represented
    by the 4-1 aggregate balance.  Confirming wins, level ties and comebacks
    always retain ordinary match weight.
    """
    if before_home is None or after_home is None:
        return 1.0
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

        rows = connection.execute(
            """
            SELECT club,code,name,country,country_name,country_code,continent,resolution
            FROM clubs ORDER BY club
            """
        ).fetchall()
        self.clubs = [ClubMeta(*row) for row in rows]
        size = len(self.clubs)
        self.club_rating = [0.0] * size
        self.club_effective = [0.0] * size
        self.club_info_day = [-1] * size
        self.club_year = [-1] * size
        self.last_tier = [1] * size
        self.initialised = [False] * size
        self.matches_played = [0] * size
        self.first_day = [-1] * size
        self.last_match_day = [-1] * size

        countries = sorted({club.country for club in self.clubs if club.country})
        self.country_index = {
            country: index for index, country in enumerate(countries)
        }
        self.country_confederation: list[str] = [""] * len(countries)
        for club in self.clubs:
            index = self.country_index.get(club.country)
            if index is not None and club.continent:
                self.country_confederation[index] = club.continent
        confederations = sorted(
            {value for value in self.country_confederation if value}
        )
        self.confederation_index = {
            confederation: index
            for index, confederation in enumerate(confederations)
        }

        self.country_rating = [0.0] * len(countries)
        self.country_effective = [0.0] * len(countries)
        self.country_info_day = [-1] * len(countries)
        self.country_year = [-1] * len(countries)
        self.country_matches = [0] * len(countries)
        self.country_bridge_effective = [0.0] * len(countries)
        self.country_bridge_info_day = [-1] * len(countries)

        self.confederation_rating = [0.0] * len(confederations)
        self.confederation_effective = [0.0] * len(confederations)
        self.confederation_info_day = [-1] * len(confederations)
        self.confederation_year = [-1] * len(confederations)
        self.confederation_matches = [0] * len(confederations)

        self.tier_rating: dict[tuple[str, int], float] = {}
        self.tier_effective: dict[tuple[str, int], float] = {}
        self.tier_info_day: dict[tuple[str, int], int] = {}
        self.tier_year: dict[tuple[str, int], int] = {}
        self.tier_matches: defaultdict[tuple[str, int], int] = defaultdict(int)

        self.recent_second_leg = [-100_000] * size
        self.recent_controlled_second_leg = [-100_000] * size
        self.metrics: dict[str, list[float]] = {
            name: [0.0, 0.0, 0.0, 0.0, 0.0]
            for name in (
                "all", "club", "tier", "country", "confederation",
                "cross_group", "post_tie", "post_controlled_tie", "second_leg",
            )
        }
        self.minimum_day = (
            0 if not replay_from else date.fromisoformat(replay_from).toordinal()
        )
        self.eval_first = (
            date.min.toordinal()
            if evaluation_start is None
            else date.fromisoformat(evaluation_start).toordinal()
        )
        self.eval_last = (
            date.max.toordinal()
            if evaluation_end is None
            else date.fromisoformat(evaluation_end).toordinal()
        )
        self.projected_year = -1

    def _country(self, club: int) -> int | None:
        return self.country_index.get(self.clubs[club].country)

    def _confederation(self, club: int) -> int | None:
        country = self._country(club)
        if country is None:
            return None
        return self.confederation_index.get(
            self.country_confederation[country]
        )

    def _tier_key(self, club: int, tier: int | None = None) -> tuple[str, int]:
        return (
            self.clubs[club].country,
            max(1, self.last_tier[club] if tier is None else int(tier)),
        )

    def _ensure_tier(self, key: tuple[str, int], year: int) -> None:
        if key not in self.tier_rating:
            self.tier_rating[key] = 0.0
            self.tier_effective[key] = 0.0
            self.tier_info_day[key] = -1
            self.tier_year[key] = year

    def _project_club(self, club: int, year: int, tier: int) -> None:
        tier = max(1, int(tier))
        if not self.initialised[club]:
            self.initialised[club] = True
            self.club_year[club] = year
        elif year > self.club_year[club]:
            self.club_rating[club] *= float(self.config["club_retention"]) ** (
                year - self.club_year[club]
            )
            self.club_year[club] = year
        self.last_tier[club] = tier
        self._ensure_tier(self._tier_key(club, tier), year)

    def _project_all_to_year(self, year: int) -> None:
        if year <= self.projected_year:
            return
        for club in range(len(self.clubs)):
            if self.initialised[club] and year > self.club_year[club]:
                self.club_rating[club] *= float(self.config["club_retention"]) ** (
                    year - self.club_year[club]
                )
                self.club_year[club] = year
        for key, previous in list(self.tier_year.items()):
            if year > previous:
                self.tier_rating[key] *= float(
                    self.config["tier_retention"]
                ) ** (year - previous)
                self.tier_year[key] = year
        for index, previous in enumerate(self.country_year):
            if previous < 0:
                self.country_year[index] = year
            elif year > previous:
                self.country_rating[index] *= float(
                    self.config["country_retention"]
                ) ** (year - previous)
                self.country_year[index] = year
        for index, previous in enumerate(self.confederation_year):
            if previous < 0:
                self.confederation_year[index] = year
            elif year > previous:
                self.confederation_rating[index] *= float(
                    self.config["confederation_retention"]
                ) ** (year - previous)
                self.confederation_year[index] = year
        self.projected_year = year

    def _decay(self, value: float, previous_day: int, day: int) -> float:
        if previous_day < 0 or day <= previous_day:
            return value
        half_life = float(self.config["effective_matches_half_life_days"])
        return value * 0.5 ** ((day - previous_day) / half_life)

    def _publication_anchor(self) -> float:
        values = []
        for country, country_value in enumerate(self.country_rating):
            confederation = self.confederation_index.get(
                self.country_confederation[country]
            )
            confederation_value = (
                0.0
                if confederation is None
                else self.confederation_rating[confederation]
            )
            values.append(country_value + confederation_value)
        return max(values, default=0.0)

    def components(
        self,
        club: int,
        publication_anchor: float | None = None,
    ) -> tuple[float, float, float, float]:
        anchor = (
            self._publication_anchor()
            if publication_anchor is None
            else publication_anchor
        )
        country = self._country(club)
        confederation = self._confederation(club)
        key = self._tier_key(club)
        tier = (
            -(max(1, self.last_tier[club]) - 1) * float(self.config["tier_gap"])
            + self.tier_rating.get(key, 0.0)
        )
        country_value = (
            0.0 if country is None else self.country_rating[country]
        )
        confederation_value = (
            0.0
            if confederation is None
            else self.confederation_rating[confederation]
        )
        return (
            self.club_rating[club],
            tier,
            country_value,
            confederation_value - anchor,
        )

    def mean(
        self,
        club: int,
        publication_anchor: float | None = None,
    ) -> float:
        return float(self.config["base_rating"]) + sum(
            self.components(club, publication_anchor)
        )

    def component_standard_errors(
        self,
        club: int,
        day: int,
    ) -> tuple[float, float, float, float]:
        country = self._country(club)
        confederation = self._confederation(club)
        tier_key = self._tier_key(club)
        club_information = self._decay(
            self.club_effective[club], self.club_info_day[club], day
        )
        tier_information = self._decay(
            self.tier_effective.get(tier_key, 0.0),
            self.tier_info_day.get(tier_key, -1),
            day,
        )
        country_information = (
            0.0
            if country is None
            else self._decay(
                self.country_effective[country],
                self.country_info_day[country],
                day,
            )
        )
        confederation_information = (
            0.0
            if confederation is None
            else self._decay(
                self.confederation_effective[confederation],
                self.confederation_info_day[confederation],
                day,
            )
        )
        club_sd = float(self.config["club_prior_sd"]) / math.sqrt(
            1.0 + club_information / 6.0
        )
        tier_sd = (
            0.0
            if float(self.config["tier_share"]) == 0.0
            else float(self.config["tier_prior_sd"])
            / math.sqrt(1.0 + tier_information / 4.0)
        )
        country_sd = (
            0.0
            if country is None
            else float(self.config["country_prior_sd"])
            / math.sqrt(1.0 + country_information / 4.0)
        )
        confederation_sd = (
            0.0
            if confederation is None
            else float(self.config["confederation_prior_sd"])
            / math.sqrt(1.0 + confederation_information / 3.0)
        )
        return club_sd, tier_sd, country_sd, confederation_sd

    def uncertainty(self, club: int, day: int) -> float:
        return math.sqrt(
            sum(value * value for value in self.component_standard_errors(club, day))
        )

    def public_rating(
        self,
        club: int,
        day: int,
        publication_anchor: float | None = None,
    ) -> float:
        return self.mean(club, publication_anchor) - float(
            self.config["uncertainty_penalty"]
        ) * self.uncertainty(club, day)

    def hierarchy_level(
        self,
        home: int,
        away: int,
        home_tier: int,
        away_tier: int,
        cross_border: bool,
        kind: str,
    ) -> str:
        home_country = self.clubs[home].country
        away_country = self.clubs[away].country
        if home_country == away_country:
            if not cross_border and int(home_tier) != int(away_tier):
                return "tier"
            return "club"
        if not cross_border or kind not in BOUNDARY_KINDS:
            return "club"
        home_confederation = self.clubs[home].continent
        away_confederation = self.clubs[away].continent
        if home_confederation != away_confederation:
            return (
                "confederation"
                if kind in CONFEDERATION_KINDS
                else "club"
            )
        return "country"

    def _home_advantage(
        self,
        cross_border: bool,
        neutral: bool,
        kind: str = "",
    ) -> float:
        if neutral or kind == "global":
            return 0.0
        key = (
            "home_advantage_cross_border"
            if cross_border
            else "home_advantage_domestic"
        )
        return float(self.config[key])

    def _evidence_weight(
        self,
        kind: str,
        status: str,
        aggregate_weight: float,
    ) -> float:
        competition = float(
            self.config["competition_weights"].get(kind, 1.0)
        )
        duration = 1.0
        if status == "E":
            duration = float(self.config["extra_time_weight"])
        elif status.startswith("P"):
            duration = float(self.config["penalty_weight"])
        return competition * duration * aggregate_weight

    @staticmethod
    def _score(home_goals: int, away_goals: int, status: str) -> float:
        if status.startswith("P") or home_goals == away_goals:
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

    def _record_metric(
        self,
        bucket: str,
        probability: float,
        probabilities: tuple[float, float, float],
        score: float,
    ) -> None:
        values = self.metrics[bucket]
        loss = -math.log(max(1e-15, probability))
        values[0] += loss
        values[1] += loss * loss
        outcome = (
            (1.0, 0.0, 0.0)
            if score == 1.0
            else ((0.0, 0.0, 1.0) if score == 0.0 else (0.0, 1.0, 0.0))
        )
        values[2] += sum(
            (predicted - observed) ** 2
            for predicted, observed in zip(probabilities, outcome)
        )
        values[3] += (
            1.0
            if probabilities.index(max(probabilities))
            == outcome.index(max(outcome))
            else 0.0
        )
        values[4] += 1.0

    def _centre_country_components(self, day: int) -> None:
        """Identify association effects relative to the continental elite.

        Global club tournaments select champions and other leading clubs, not
        an average association.  Anchoring each confederation at an upper,
        evidence-weighted association quantile therefore puts its independent
        global bridge on the same level as the matches that estimate it.  A
        quantile rather than a raw maximum is robust to one sparse outlier.
        """
        by_confederation: defaultdict[str, list[int]] = defaultdict(list)
        for index, confederation in enumerate(self.country_confederation):
            if confederation:
                by_confederation[confederation].append(index)
        for confederation_name, countries in by_confederation.items():
            values: list[tuple[float, float]] = []
            for country in countries:
                weight = self._decay(
                    self.country_bridge_effective[country],
                    self.country_bridge_info_day[country],
                    day,
                )
                if weight > 0.0:
                    values.append((self.country_rating[country], weight))
            evidence = sum(weight for _, weight in values)
            if evidence <= 0.0:
                continue
            threshold = evidence * float(
                self.config["country_anchor_quantile"]
            )
            cumulative = 0.0
            centre = max(value for value, _ in values)
            for value, weight in sorted(values):
                cumulative += weight
                if cumulative >= threshold:
                    centre = value
                    break
            for country in countries:
                self.country_rating[country] -= centre

    def _centre_tier_components(self) -> None:
        """Keep every association's tier-one level at the zero reference.

        Domestic cup matches identify the *gap* between divisions, but they
        cannot identify an association's absolute strength.  Without this
        constraint, equal-and-opposite tier updates let a successful top
        division acquire a positive global offset from purely domestic games.
        Recentring preserves every learned inter-tier gap while preventing
        that unidentifiable offset from leaking into global comparisons.
        """
        tier_one = {
            country: value
            for (country, tier), value in self.tier_rating.items()
            if tier == 1
        }
        for key in list(self.tier_rating):
            country, _ = key
            if country in tier_one:
                self.tier_rating[key] -= tier_one[country]

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

    def _bulk_copy(
        self,
        table: str,
        rows: Iterable[tuple[Any, ...]],
    ) -> int:
        assert self.output_connection is not None
        target = self.output_connection
        count = 0
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=Path(target.execute("PRAGMA database_list").fetchone()[2]).parent,
            prefix=f".{table}-",
            delete=False,
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
                f"COPY {table} FROM ? "
                "(FORMAT CSV, DELIM '\\t', HEADER false, NULLSTR '\\N')",
                [str(path)],
            ).fetchall()
        finally:
            path.unlink(missing_ok=True)
        return count

    def _opening_rows(
        self,
        year: int,
        day: int,
    ) -> Iterator[tuple[Any, ...]]:
        anchor = self._publication_anchor()
        for club in range(len(self.clubs)):
            if not self.initialised[club]:
                continue
            yield (
                year,
                club,
                self.mean(club, anchor),
                self.public_rating(club, day, anchor),
                self.uncertainty(club, day),
                self.last_match_day[club],
                self.matches_played[club],
                self.last_tier[club],
            )

    def _match_query(self) -> str:
        condition = ""
        if self.replay_from:
            condition = f"WHERE day >= DATE '{self.replay_from}'"
        return f"""
            SELECT match_id,cast(day as varchar),season,home,away,home_goals,away_goals,
                   competition,competition_key,kind,home_tier,away_tier,
                   neutral OR kind='global' neutral,cross_border,status,leg,tie_key,
                   round_name,source,source_ref,aggregate_before_home,
                   aggregate_after_home
            FROM matches {condition} ORDER BY day,match_id
        """

    def replay(self) -> dict[str, Any]:
        if self.write_tables:
            self._create_output_tables()
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
            self._project_all_to_year(year)
            if self.write_tables and previous_year != year:
                opening_day = date(year, 1, 1).toordinal()
                self._bulk_copy(
                    "year_openings",
                    self._opening_rows(year, opening_day),
                )
                previous_year = year

            for row in rows:
                self._project_club(int(row[3]), year, int(row[10]))
                self._project_club(int(row[4]), year, int(row[11]))
            pre_anchor = self._publication_anchor()

            club_changes: defaultdict[int, float] = defaultdict(float)
            club_information: defaultdict[int, float] = defaultdict(float)
            tier_changes: defaultdict[tuple[str, int], float] = defaultdict(float)
            tier_information: defaultdict[tuple[str, int], float] = defaultdict(float)
            country_changes: defaultdict[int, float] = defaultdict(float)
            country_information: defaultdict[int, float] = defaultdict(float)
            confederation_changes: defaultdict[int, float] = defaultdict(float)
            confederation_information: defaultdict[int, float] = defaultdict(float)
            bridge_information: defaultdict[int, float] = defaultdict(float)
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
                kind = str(kind)
                pre_home_mean = self.mean(home, pre_anchor)
                pre_away_mean = self.mean(away, pre_anchor)
                home_se = self.uncertainty(home, ordinal)
                away_se = self.uncertainty(away, ordinal)
                home_rating = pre_home_mean - float(
                    self.config["uncertainty_penalty"]
                ) * home_se
                away_rating = pre_away_mean - float(
                    self.config["uncertainty_penalty"]
                ) * away_se
                difference = (
                    pre_home_mean
                    - pre_away_mean
                    + self._home_advantage(
                        bool(cross_border), bool(neutral), kind
                    )
                )
                probabilities = three_way_probabilities(
                    difference, float(self.config["draw_peak"])
                )
                expected = logistic10(difference)
                score = self._score(
                    int(home_goals), int(away_goals), str(status)
                )
                aggregate_weight = aggregate_leg_weight(
                    integer_or_none(aggregate_before),
                    integer_or_none(aggregate_after),
                    float(self.config["aggregate_floor"]),
                    float(self.config["aggregate_scale"]),
                    score,
                )
                evidence = self._evidence_weight(
                    kind, str(status), aggregate_weight
                )
                margin = (
                    0
                    if str(status).startswith("P")
                    else abs(int(home_goals) - int(away_goals))
                )
                movement = (
                    float(self.config["k_factor"])
                    * evidence
                    * margin_multiplier(
                        margin, float(self.config["margin_scale"])
                    )
                    * (score - expected)
                )
                hierarchy = self.hierarchy_level(
                    home,
                    away,
                    home_tier,
                    away_tier,
                    bool(cross_border),
                    kind,
                )
                share = (
                    0.0
                    if hierarchy == "club"
                    else float(self.config[f"{hierarchy}_share"])
                )
                club_share = 1.0 - share
                club_changes[home] += club_share * movement
                club_changes[away] -= club_share * movement
                club_information[home] += club_share * evidence
                club_information[away] += club_share * evidence

                if hierarchy == "tier":
                    home_key = self._tier_key(home, home_tier)
                    away_key = self._tier_key(away, away_tier)
                    tier_changes[home_key] += share * movement
                    tier_changes[away_key] -= share * movement
                    tier_information[home_key] += share * evidence
                    tier_information[away_key] += share * evidence
                elif hierarchy == "country":
                    home_country = self._country(home)
                    away_country = self._country(away)
                    if home_country is not None and away_country is not None:
                        country_changes[home_country] += share * movement
                        country_changes[away_country] -= share * movement
                        country_information[home_country] += share * evidence
                        country_information[away_country] += share * evidence
                elif hierarchy == "confederation":
                    home_confederation = self._confederation(home)
                    away_confederation = self._confederation(away)
                    if (
                        home_confederation is not None
                        and away_confederation is not None
                    ):
                        confederation_changes[home_confederation] += share * movement
                        confederation_changes[away_confederation] -= share * movement
                        confederation_information[home_confederation] += share * evidence
                        confederation_information[away_confederation] += share * evidence

                home_country = self._country(home)
                away_country = self._country(away)
                if (
                    bool(cross_border)
                    and home_country is not None
                    and away_country is not None
                    and home_country != away_country
                ):
                    bridge_information[home_country] += evidence
                    bridge_information[away_country] += evidence

                probability = self._outcome_probability(
                    score, *probabilities
                )
                if self.eval_first <= ordinal <= self.eval_last:
                    self._record_metric(
                        "all", probability, probabilities, score
                    )
                    self._record_metric(
                        hierarchy, probability, probabilities, score
                    )
                    if hierarchy != "club":
                        self._record_metric(
                            "cross_group", probability, probabilities, score
                        )
                    if ordinal - max(
                        self.recent_second_leg[home],
                        self.recent_second_leg[away],
                    ) <= 120:
                        self._record_metric(
                            "post_tie", probability, probabilities, score
                        )
                    if ordinal - max(
                        self.recent_controlled_second_leg[home],
                        self.recent_controlled_second_leg[away],
                    ) <= 120:
                        self._record_metric(
                            "post_controlled_tie",
                            probability,
                            probabilities,
                            score,
                        )
                    if int(leg) == 2 and aggregate_before is not None:
                        self._record_metric(
                            "second_leg", probability, probabilities, score
                        )
                temporary.append(
                    {
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
                    }
                )

            for club, change in club_changes.items():
                self.club_rating[club] += change
                self.club_effective[club] = (
                    self._decay(
                        self.club_effective[club],
                        self.club_info_day[club],
                        ordinal,
                    )
                    + club_information[club]
                )
                self.club_info_day[club] = ordinal
            for key, change in tier_changes.items():
                self.tier_rating[key] = self.tier_rating.get(key, 0.0) + change
                self.tier_effective[key] = (
                    self._decay(
                        self.tier_effective.get(key, 0.0),
                        self.tier_info_day.get(key, -1),
                        ordinal,
                    )
                    + tier_information[key]
                )
                self.tier_info_day[key] = ordinal
                self.tier_matches[key] += 1
            for country, change in country_changes.items():
                self.country_rating[country] += change
                self.country_effective[country] = (
                    self._decay(
                        self.country_effective[country],
                        self.country_info_day[country],
                        ordinal,
                    )
                    + country_information[country]
                )
                self.country_info_day[country] = ordinal
                self.country_matches[country] += 1
            for confederation, change in confederation_changes.items():
                self.confederation_rating[confederation] += change
                self.confederation_effective[confederation] = (
                    self._decay(
                        self.confederation_effective[confederation],
                        self.confederation_info_day[confederation],
                        ordinal,
                    )
                    + confederation_information[confederation]
                )
                self.confederation_info_day[confederation] = ordinal
                self.confederation_matches[confederation] += 1
            for country, information in bridge_information.items():
                self.country_bridge_effective[country] = (
                    self._decay(
                        self.country_bridge_effective[country],
                        self.country_bridge_info_day[country],
                        ordinal,
                    )
                    + information
                )
                self.country_bridge_info_day[country] = ordinal

            self._centre_tier_components()
            self._centre_country_components(ordinal)
            post_anchor = self._publication_anchor()
            for item in temporary:
                home, away = item["home"], item["away"]
                for club in (home, away):
                    self.matches_played[club] += 1
                    self.first_day[club] = (
                        ordinal
                        if self.first_day[club] < 0
                        else min(self.first_day[club], ordinal)
                    )
                    self.last_match_day[club] = max(
                        self.last_match_day[club], ordinal
                    )
                row = item["base"]
                if int(row[15]) == 2 and row[20] is not None:
                    self.recent_second_leg[home] = ordinal
                    self.recent_second_leg[away] = ordinal
                    before = integer_or_none(row[20])
                    after = integer_or_none(row[21])
                    if (
                        before is not None
                        and after is not None
                        and before * after > 0
                        and abs(before) >= 2
                        and (item["score"] - 0.5)
                        * ((1.0 if after > 0 else 0.0) - 0.5)
                        < 0.0
                    ):
                        self.recent_controlled_second_leg[home] = ordinal
                        self.recent_controlled_second_leg[away] = ordinal
                if self.write_tables:
                    post_home_mean = self.mean(home, post_anchor)
                    post_away_mean = self.mean(away, post_anchor)
                    post_home_se = self.uncertainty(home, ordinal)
                    post_away_se = self.uncertainty(away, ordinal)
                    rated_buffer.append(
                        (
                            row[0], row[1], row[2], home, away, row[5], row[6],
                            row[7], row[8], row[9], row[10], row[11], row[12],
                            row[13], row[14], row[15], row[16], row[17], row[18],
                            row[19], row[20], row[21],
                            item["aggregate_weight"], item["evidence"],
                            item["pre_home_mean"], item["pre_away_mean"],
                            item["home_rating"], item["away_rating"],
                            item["home_se"], item["away_se"],
                            item["probabilities"][0], item["probabilities"][1],
                            item["probabilities"][2], item["score"],
                            item["movement"], post_home_mean, post_away_mean,
                            post_home_mean
                            - float(self.config["uncertainty_penalty"])
                            * post_home_se,
                            post_away_mean
                            - float(self.config["uncertainty_penalty"])
                            * post_away_se,
                            post_home_se, post_away_se, item["surprise"],
                        )
                    )
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
            self._validate_output_tables(processed)
        return self.summary(processed)

    def _validate_output_tables(self, expected_matches: int) -> None:
        """Prove output keys are unique without rewriting completed tables.

        The replay consumes the already-unique ledger exactly once and writes
        one current row per entity, so a duplicate is a model bug and must stop
        publication.  An earlier defensive implementation rebuilt every table
        and renamed it with ``ALTER TABLE``.  On large DuckDB 1.4.x databases,
        those final catalog renames could remain in a WAL that intermittently
        failed to replay after a clean-clone checkpoint.  Validation plus
        unique indexes gives the same invariant without a fragile final
        catalog rewrite.
        """
        assert self.output_connection is not None
        target = self.output_connection
        for table, keys in (
            ("rated_matches", "match_id"),
            ("year_openings", "year,club"),
            ("current_club_ratings", "club"),
            ("current_country_ratings", "country"),
            ("current_confederation_ratings", "confederation"),
        ):
            duplicate_groups = int(target.execute(
                f"SELECT count(*) FROM ("
                f"SELECT {keys} FROM {table} GROUP BY {keys} "
                f"HAVING count(*)>1) duplicates"
            ).fetchone()[0])
            if duplicate_groups:
                raise RuntimeError(
                    f"club model produced {duplicate_groups:,} duplicate "
                    f"key groups in {table}"
                )
        stored = int(
            target.execute("SELECT count(*) FROM rated_matches").fetchone()[0]
        )
        if stored != expected_matches:
            raise RuntimeError(
                f"club model wrote {stored:,} unique matches; "
                f"expected {expected_matches:,}"
            )
        for name, table, keys in (
            ("rated_matches_match_id_unique", "rated_matches", "match_id"),
            ("year_openings_year_club_unique", "year_openings", "year,club"),
            ("current_club_ratings_club_unique", "current_club_ratings", "club"),
            ("current_country_ratings_country_unique", "current_country_ratings", "country"),
            (
                "current_confederation_ratings_confederation_unique",
                "current_confederation_ratings",
                "confederation",
            ),
        ):
            target.execute(f"CREATE UNIQUE INDEX {name} ON {table}({keys})")
        target.execute("DROP VIEW IF EXISTS current_association_ratings")
        target.execute(
            "CREATE VIEW current_association_ratings AS "
            "SELECT country,rating,se,cross_border_updates AS international_updates "
            "FROM current_country_ratings"
        )

    def _write_current_tables(self) -> None:
        assert self.output_connection is not None
        target = self.output_connection
        maximum = self.connection.execute(
            "SELECT max(day) FROM matches"
        ).fetchone()[0]
        ordinal = maximum.toordinal()
        anchor = self._publication_anchor()

        target.execute("DROP TABLE IF EXISTS current_club_ratings")
        target.execute(
            """
            CREATE TABLE current_club_ratings(
                club INTEGER,mean DOUBLE,rating DOUBLE,se DOUBLE,matches INTEGER,
                first_day INTEGER,last_day INTEGER,tier SMALLINT,
                club_component DOUBLE,tier_component DOUBLE,country_component DOUBLE,
                confederation_component DOUBLE,club_se DOUBLE,tier_se DOUBLE,
                country_se DOUBLE,confederation_se DOUBLE
            )
            """
        )
        club_rows = []
        for club in range(len(self.clubs)):
            if not self.initialised[club]:
                continue
            components = self.components(club, anchor)
            component_se = self.component_standard_errors(club, ordinal)
            club_rows.append(
                (
                    club,
                    self.mean(club, anchor),
                    self.public_rating(club, ordinal, anchor),
                    self.uncertainty(club, ordinal),
                    self.matches_played[club],
                    self.first_day[club],
                    self.last_match_day[club],
                    self.last_tier[club],
                    *components,
                    *component_se,
                )
            )
        self._bulk_copy("current_club_ratings", club_rows)

        target.execute("DROP TABLE IF EXISTS current_country_ratings")
        target.execute(
            """
            CREATE TABLE current_country_ratings(
                country VARCHAR,confederation VARCHAR,country_rating DOUBLE,
                confederation_rating DOUBLE,rating DOUBLE,country_se DOUBLE,
                confederation_se DOUBLE,se DOUBLE,international_updates INTEGER,
                interconfederation_updates INTEGER,cross_border_updates INTEGER,
                bridge_evidence DOUBLE
            )
            """
        )
        inverse_countries = sorted(
            self.country_index, key=self.country_index.get
        )
        country_rows = []
        for index, country in enumerate(inverse_countries):
            information = self._decay(
                self.country_effective[index],
                self.country_info_day[index],
                ordinal,
            )
            se = float(self.config["country_prior_sd"]) / math.sqrt(
                1.0 + information / 4.0
            )
            confederation_name = self.country_confederation[index]
            confederation = self.confederation_index.get(confederation_name)
            if confederation is None:
                confederation_rating = -anchor
                confederation_se = float(self.config["confederation_prior_sd"])
                interconfederation_updates = 0
            else:
                confederation_information = self._decay(
                    self.confederation_effective[confederation],
                    self.confederation_info_day[confederation],
                    ordinal,
                )
                confederation_rating = (
                    self.confederation_rating[confederation] - anchor
                )
                confederation_se = float(
                    self.config["confederation_prior_sd"]
                ) / math.sqrt(1.0 + confederation_information / 3.0)
                interconfederation_updates = self.confederation_matches[confederation]
            bridge = self._decay(
                self.country_bridge_effective[index],
                self.country_bridge_info_day[index],
                ordinal,
            )
            country_rows.append(
                (
                    country,
                    confederation_name,
                    self.country_rating[index],
                    confederation_rating,
                    self.country_rating[index] + confederation_rating,
                    se,
                    confederation_se,
                    math.hypot(se, confederation_se),
                    self.country_matches[index],
                    interconfederation_updates,
                    self.country_matches[index] + interconfederation_updates,
                    bridge,
                )
            )
        self._bulk_copy("current_country_ratings", country_rows)

        target.execute("DROP TABLE IF EXISTS current_confederation_ratings")
        target.execute(
            """
            CREATE TABLE current_confederation_ratings(
                confederation VARCHAR,rating DOUBLE,se DOUBLE,
                interconfederation_updates INTEGER
            )
            """
        )
        inverse_confederations = sorted(
            self.confederation_index,
            key=self.confederation_index.get,
        )
        confederation_rows = []
        for index, confederation in enumerate(inverse_confederations):
            information = self._decay(
                self.confederation_effective[index],
                self.confederation_info_day[index],
                ordinal,
            )
            se = float(self.config["confederation_prior_sd"]) / math.sqrt(
                1.0 + information / 3.0
            )
            confederation_rows.append(
                (
                    confederation,
                    self.confederation_rating[index] - anchor,
                    se,
                    self.confederation_matches[index],
                )
            )
        self._bulk_copy(
            "current_confederation_ratings", confederation_rows
        )

    def summary(self, processed: int) -> dict[str, Any]:
        metrics = {}
        for name, values in self.metrics.items():
            count = int(values[4])
            mean_loss = None if not count else values[0] / count
            variance = (
                0.0
                if count < 2
                else max(
                    0.0,
                    (values[1] - count * float(mean_loss) ** 2)
                    / (count - 1),
                )
            )
            metrics[name] = {
                "matches": count,
                "log_loss": mean_loss,
                "log_loss_se": (
                    None if not count else math.sqrt(variance / count)
                ),
                "brier": None if not count else values[2] / count,
                "accuracy": None if not count else values[3] / count,
            }
        return {
            "matches": processed,
            "clubs": sum(self.initialised),
            "countries": len(self.country_index),
            "confederations": len(self.confederation_index),
            "metrics": metrics,
        }


def integer_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _replay_model_once(
    database: Path,
    config: dict[str, Any],
    *,
    write_tables: bool,
    output_database: Path | None = None,
    snapshot_directory: Path | None = None,
    replay_from: str | None = None,
    evaluation_start: str | None = None,
    evaluation_end: str | None = None,
) -> dict[str, Any]:
    """Replay in the current process; the caller owns process isolation."""

    connection = duckdb.connect(str(database), read_only=True)
    output_connection: duckdb.DuckDBPyConnection | None = None
    if write_tables:
        if output_database is None or snapshot_directory is None:
            raise ValueError(
                "an output database and snapshot directory are required "
                "for a persistent club replay"
            )
        output_database.parent.mkdir(parents=True, exist_ok=True)
        snapshot_directory.mkdir(parents=True, exist_ok=True)
        output_connection = duckdb.connect(str(output_database))
    try:
        model = ClubRatingModel(
            connection,
            config,
            write_tables=write_tables,
            output_connection=output_connection,
            replay_from=replay_from,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
        )
        result = model.replay()
        if output_database is not None:
            result["model_database"] = str(output_database)
        if output_connection is not None:
            # The replay database is deliberately disposable. DuckDB 1.4.x can
            # lose earlier COPY batches when a large, repeatedly appended file
            # is checkpointed and cold-reopened. Export every completed table
            # while the writer's catalog is known-good; another process builds
            # the publication database from these immutable snapshots.
            assert snapshot_directory is not None
            result["year_openings"] = int(
                output_connection.execute(
                    "SELECT count(*) FROM year_openings"
                ).fetchone()[0]
            )
            for table in PERSISTED_TABLES:
                output_connection.execute(
                    f"COPY {table} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(snapshot_directory / f"{table}.parquet")],
                )
        return result
    finally:
        connection.close()
        if output_connection is not None:
            output_connection.close()


def _atomic_worker(payload_path: Path) -> None:
    """Write a raw model and snapshots, then let interpreter exit release it."""

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    result = _replay_model_once(
        Path(payload["database"]),
        payload["config"],
        write_tables=True,
        output_database=Path(payload["working_database"]),
        snapshot_directory=Path(payload["snapshot_directory"]),
        replay_from=payload.get("replay_from"),
        evaluation_start=payload.get("evaluation_start"),
        evaluation_end=payload.get("evaluation_end"),
    )
    Path(payload["result_path"]).write_text(
        json.dumps(result, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
    """Replay ratings, publishing persistent databases across process boundaries.

    DuckDB 1.4.x can retain a closed database instance until its interpreter
    exits.  On a million-row replay that stale instance can recreate an old WAL
    after a second connection has checkpointed the final catalog.  Persistent
    builds therefore run the complete writer in a child process; only after it
    exits do separate processes finalize and verify the atomic database.
    """

    if not write_tables:
        return _replay_model_once(
            database,
            config,
            write_tables=False,
            replay_from=replay_from,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
        )

    output_database = output_database or database.with_name(
        "club-model.duckdb"
    )
    output_database.parent.mkdir(parents=True, exist_ok=True)
    working_directory = Path(tempfile.mkdtemp(
        prefix=f".{output_database.name}.building-",
        dir=output_database.parent,
    ))
    raw_database = working_directory / "writer.duckdb"
    working_database = working_directory / output_database.name
    snapshot_directory = working_directory / "current-snapshots"
    payload_path = working_directory / "worker-input.json"
    result_path = working_directory / "worker-result.json"
    payload_path.write_text(
        json.dumps(
            {
                "database": str(database.resolve()),
                "config": config,
                "working_database": str(raw_database.resolve()),
                "snapshot_directory": str(snapshot_directory.resolve()),
                "result_path": str(result_path.resolve()),
                "replay_from": replay_from,
                "evaluation_start": evaluation_start,
                "evaluation_end": evaluation_end,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result: dict[str, Any] | None = None
    try:
        writer = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--atomic-worker",
                str(payload_path.resolve()),
            ],
            text=True,
            capture_output=True,
        )
        if writer.returncode:
            detail = (writer.stderr or writer.stdout).strip()
            raise RuntimeError(
                "isolated club model writer failed"
                + (f": {detail}" if detail else "")
            )
        if not result_path.is_file() or not raw_database.is_file():
            raise RuntimeError(
                "isolated club model writer did not produce its result and database"
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["model_database"] = str(output_database)

        def database_helper(mode: str, path: Path) -> None:
            """Finalize or verify in another fresh interpreter process."""
            assert result is not None
            helper = r"""
import duckdb
from pathlib import Path
import sys

mode, path, expected_matches, expected_openings, expected_clubs, expected_countries, expected_confederations, snapshots = sys.argv[1:9]
expected = {
    "rated_matches": int(expected_matches),
    "year_openings": int(expected_openings),
    "current_club_ratings": int(expected_clubs),
    "current_country_ratings": int(expected_countries),
    "current_confederation_ratings": int(expected_confederations),
}
if mode == "finalize":
    connection = duckdb.connect(path)
    try:
        for table in (
            "rated_matches",
            "year_openings",
            "current_club_ratings",
            "current_country_ratings",
            "current_confederation_ratings",
        ):
            source = str(Path(snapshots) / f"{table}.parquet")
            if not Path(source).is_file():
                raise SystemExit(f"missing final snapshot {source}")
            connection.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?)",
                [source],
            )
        for name, table, keys in (
            ("rated_matches_match_id_unique", "rated_matches", "match_id"),
            ("year_openings_year_club_unique", "year_openings", "year,club"),
            ("current_club_ratings_club_unique", "current_club_ratings", "club"),
            ("current_country_ratings_country_unique", "current_country_ratings", "country"),
            (
                "current_confederation_ratings_confederation_unique",
                "current_confederation_ratings",
                "confederation",
            ),
        ):
            connection.execute(f"CREATE UNIQUE INDEX {name} ON {table}({keys})")
        connection.execute(
            "CREATE VIEW current_association_ratings AS "
            "SELECT country,rating,se,cross_border_updates AS international_updates "
            "FROM current_country_ratings"
        )
        connection.execute("FORCE CHECKPOINT").fetchall()
    finally:
        connection.close()
else:
    connection = duckdb.connect(path, read_only=True)
    try:
        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        required = {
            "rated_matches", "year_openings", "current_club_ratings",
            "current_country_ratings", "current_confederation_ratings",
        }
        missing = sorted(required - tables)
        if missing:
            raise SystemExit("missing " + ", ".join(missing))
        for table, wanted in expected.items():
            stored = int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            if stored != wanted:
                raise SystemExit(
                    f"reopened {stored:,} rows from {table}; expected {wanted:,}"
                )
    finally:
        connection.close()
"""
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    helper,
                    mode,
                    str(path.resolve()),
                    str(int(result["matches"])),
                    str(int(result["year_openings"])),
                    str(int(result["clubs"])),
                    str(int(result["countries"])),
                    str(int(result["confederations"])),
                    str(snapshot_directory.resolve()),
                ],
                text=True,
                capture_output=True,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(
                    f"club model persistence {mode} failed"
                    + (f": {detail}" if detail else "")
                )

        def verify_model(path: Path) -> None:
            database_helper("verify", path)

        def finalize_model(path: Path) -> None:
            """Build a new durable database solely from verified snapshots."""
            database_helper("finalize", path)

        finalize_model(working_database)
        verify_model(working_database)
        working_wal = Path(f"{working_database}.wal")
        if working_wal.exists():
            raise RuntimeError(
                "club model finalizer left a write-ahead log beside the "
                "verified atomic database"
            )
        # The destination is a generated cache artifact. A WAL left by an
        # interrupted earlier replay must not be paired with the new file.
        Path(f"{output_database}.wal").unlink(missing_ok=True)
        os.replace(working_database, output_database)
        verify_model(output_database)
        return result
    finally:
        try:
            shutil.rmtree(working_directory)
        except FileNotFoundError:
            pass
        if working_directory.exists():
            raise RuntimeError(
                f"atomic club model workspace was not removed: {working_directory}"
            )


__all__ = [
    "ClubRatingModel",
    "aggregate_leg_weight",
    "load_club_config",
    "logistic10",
    "margin_multiplier",
    "run_club_model",
    "three_way_probabilities",
]


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--atomic-worker":
        raise SystemExit("club_model.py is an internal module")
    _atomic_worker(Path(sys.argv[2]))
