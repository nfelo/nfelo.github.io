#!/usr/bin/env python3
"""Deployed opponent-network rating model and record-rating layer."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np

from ledger import Match, read_dictionary, read_matches, read_successors


KNOT_YEARS = (1900, 1930, 1960, 1990, 2020)
CALIBRATION_SCALE = (
    1.9329803161851784,
    1.5602143637570678,
    1.3044459799655215,
    1.1218570234757215,
    1.0,
)
HOME_ADVANTAGE = (
    73.123115543503,
    96.74246793815797,
    112.89558566270792,
    112.66052421548639,
    83.53363897913016,
)
DRAW_PROBABILITY = (
    0.18451738305372078,
    0.2174334339602218,
    0.25965582882029153,
    0.30867595078868215,
    0.32513463832148676,
)

G_DRAW = 3.486642593835564
G_TWO = 1.755270459152449
G_THREE = 2.20104735688078
G_TAIL = 1.467767822525712
MARGIN_ENVIRONMENT_POWER = 1.880272889370813
NEWCOMER_OFFSET = -192.90021991733568
ACTIVE_POOL_SLOPE = -84.24860586823341
PRIOR_SD = 299.99999999999994
DRIFT_SD = 19.750212594949737
QUALITY_SCALE = 1.7440260583320362
FRIENDLY_TEMPERATURE = 0.9697407083655329
COMPETITIVE_TEMPERATURE = 1.0635626456560392

CONFIDENCE = 0.95
CONFIDENCE_Z = NormalDist().inv_cdf(CONFIDENCE)
BREADTH_HALF_LIFE = 8.0
BREADTH_PRIOR = 4.0
MINIMUM_RECORD_MATCHES = 30

# Exact 11-point physicists' Gauss-Hermite nodes and weights / sqrt(pi).
QUADRATURE_NODES = np.asarray(
    (
        -3.6684708465595826,
        -2.7832900997816514,
        -2.0259480158257555,
        -1.3265570844949328,
        -0.6568095668820998,
        0.0,
        0.6568095668820998,
        1.3265570844949328,
        2.0259480158257555,
        2.7832900997816514,
        3.6684708465595826,
    ),
    dtype=np.float64,
)
QUADRATURE_WEIGHTS = np.asarray(
    (
        0.0000008121849790214923,
        0.00019567193027122338,
        0.0067202852355372645,
        0.06613874607105782,
        0.24224029987396992,
        0.36940836940836935,
        0.24224029987396992,
        0.06613874607105782,
        0.0067202852355372645,
        0.00019567193027122338,
        0.0000008121849790214923,
    ),
    dtype=np.float64,
)


def interpolate(year: int, values: tuple[float, ...] | list[float]) -> float:
    if year <= KNOT_YEARS[0]:
        return float(values[0])
    if year >= KNOT_YEARS[-1]:
        return float(values[-1])
    right = next(index for index, knot in enumerate(KNOT_YEARS) if year <= knot)
    left = right - 1
    fraction = (year - KNOT_YEARS[left]) / (KNOT_YEARS[right] - KNOT_YEARS[left])
    return float(values[left] + fraction * (values[right] - values[left]))


def calibration_scale(year: int) -> float:
    return math.exp(interpolate(year, [math.log(value) for value in CALIBRATION_SCALE]))


def home_advantage(year: int) -> float:
    return interpolate(year, HOME_ADVANTAGE)


def draw_probability(year: int) -> float:
    transformed = []
    for value in DRAW_PROBABILITY:
        unit = (value - 0.05) / 0.40
        transformed.append(math.log(unit / (1.0 - unit)))
    logit = interpolate(year, transformed)
    return 0.05 + 0.40 / (1.0 + math.exp(-logit))


def logistic10(value: np.ndarray | float) -> np.ndarray | float:
    array = np.asarray(value, dtype=np.float64)
    result = 1.0 / (1.0 + np.power(10.0, -array / 400.0))
    return float(result) if result.ndim == 0 else result


def goal_weight(margin: int, environment: float) -> float:
    if margin == 0:
        return G_DRAW
    raw_margin = min(margin, 7)
    effective = 1.0 + (raw_margin - 1.0) * (
        1.10 / max(0.10, environment)
    ) ** MARGIN_ENVIRONMENT_POWER
    effective = min(7.0, effective)
    if effective <= 1.0:
        return 1.0
    if effective <= 2.0:
        return 1.0 + (effective - 1.0) * (G_TWO - 1.0)
    if effective <= 3.0:
        return G_TWO + (effective - 2.0) * (G_THREE - G_TWO)
    return G_THREE + G_TAIL * (effective - 3.0)


def three_way_probabilities(
    difference: float,
    difference_variance: float,
    year: int,
    *,
    friendly: bool,
) -> np.ndarray:
    """Expectation-preserving W/D/L probabilities integrated over uncertainty."""

    scale = calibration_scale(year)
    sampled_sd = scale * math.sqrt(max(0.0, difference_variance))
    sampled = difference + math.sqrt(2.0) * sampled_sd * QUADRATURE_NODES
    expectation = np.asarray(logistic10(sampled), dtype=np.float64)
    draws = draw_probability(year) * 4.0 * expectation * (1.0 - expectation)
    base = np.asarray(
        (
            QUADRATURE_WEIGHTS @ (expectation - 0.5 * draws),
            QUADRATURE_WEIGHTS @ draws,
            QUADRATURE_WEIGHTS @ (1.0 - expectation - 0.5 * draws),
        ),
        dtype=np.float64,
    )
    base = np.maximum(base, 1e-15)
    temperature = FRIENDLY_TEMPERATURE if friendly else COMPETITIVE_TEMPERATURE
    adjusted = np.power(base, temperature)
    return adjusted / adjusted.sum()


@dataclass(slots=True)
class ReplayOutput:
    summary: dict[str, Any]
    state: dict[str, Any]
    matches: list[dict[str, Any]]
    team_pages: dict[str, dict[str, Any]]


class NetworkEloReplay:
    def __init__(self, source: Path, config: Path) -> None:
        self.source = source
        self.config = config
        self.successors = read_successors(source / "teams.tsv")
        self.matches = read_matches(
            source / "elo_pages",
            self.successors,
            source / "supplemental_results.csv",
        )
        self.team_names = read_dictionary(source / "en.teams.tsv", skip_locations=True)
        self.tournament_names = read_dictionary(source / "en.tournaments.tsv")
        supplemental_tournaments = source / "supplemental_tournaments.json"
        if supplemental_tournaments.exists():
            self.tournament_names.update(
                json.loads(supplemental_tournaments.read_text(encoding="utf-8"))
            )
        metadata = json.loads((config / "elo_matches.json").read_text(encoding="utf-8"))
        self.levels: dict[str, int] = {
            str(code): int(level)
            for code, level in metadata.get("tournament_levels", {}).items()
        }
        self.teams = sorted({m.team1 for m in self.matches} | {m.team2 for m in self.matches})
        self.team_index = {team: index for index, team in enumerate(self.teams)}
        self.count = len(self.teams)
        if len(self.matches) < 50_000 or self.count < 240:
            raise ValueError(
                f"Source integrity check failed: {len(self.matches)} matches, {self.count} teams"
            )

        self.mean = np.full(self.count, np.nan, dtype=np.float64)
        self.covariance = np.zeros((self.count, self.count), dtype=np.float64)
        self.games = np.zeros(self.count, dtype=np.int32)
        self.last_year = np.full(self.count, -10_000, dtype=np.int32)
        self.last_day = np.full(self.count, -1, dtype=np.int32)
        self.breadth_day = np.full(self.count, -1, dtype=np.int32)
        self.opponent_weights: list[dict[int, float]] = [dict() for _ in range(self.count)]

        self.stats: list[dict[str, Any]] = [
            {"wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0, "last5": []}
            for _ in range(self.count)
        ]
        self.histories: list[list[dict[str, Any]]] = [[] for _ in range(self.count)]
        self.team_matches: list[list[dict[str, Any]]] = [[] for _ in range(self.count)]
        self.peaks: dict[str, dict[str, Any]] = {}
        self.high_matches: list[dict[str, Any]] = []
        self.match_rows: list[dict[str, Any]] = []
        self.margin_window: deque[tuple[int, float]] = deque()
        self.margin_excess_sum = 0.0

    def name(self, code: str) -> str:
        return self.team_names.get(code, code)

    def tournament_name(self, code: str) -> str:
        return self.tournament_names.get(code, code)

    def level(self, tournament: str) -> int:
        # The state-update information ratio is one at every level. For a new
        # source code, only the friendly/competitive forecast temperature is
        # material, and F is the source's friendly code.
        return self.levels.get(tournament, 0 if tournament == "F" else 1)

    def active_indices(self, year: int, years: int) -> list[int]:
        return [
            index
            for index in range(self.count)
            if not np.isnan(self.mean[index]) and year - int(self.last_year[index]) <= years
        ]

    @staticmethod
    def median(values: list[float]) -> float:
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return 0.5 * (ordered[middle - 1] + ordered[middle])

    def debut_mean(self, year: int) -> float:
        active = self.active_indices(year, 4)
        mature = [float(self.mean[i]) for i in active if self.games[i] >= 30]
        established = [float(self.mean[i]) for i in active if self.games[i] >= 10]
        reference = mature if len(mature) >= 5 else established
        if not reference:
            return 0.0
        return (
            self.median(reference)
            + NEWCOMER_OFFSET
            + ACTIVE_POOL_SLOPE * math.log((len(active) + 10.0) / 50.0)
        )

    def initialise(self, index: int, year: int, day: int) -> None:
        if not np.isnan(self.mean[index]):
            return
        self.mean[index] = self.debut_mean(year)
        self.covariance[index, index] = PRIOR_SD**2
        self.last_day[index] = day
        self.breadth_day[index] = day

    def add_drift(self, index: int, day: int) -> None:
        elapsed = max(0.0, (day - int(self.last_day[index])) / 400.0)
        self.covariance[index, index] += DRIFT_SD**2 * elapsed
        self.last_day[index] = day

    def decay_breadth(self, index: int, day: int) -> None:
        previous = int(self.breadth_day[index])
        if previous < 0:
            self.breadth_day[index] = day
            return
        elapsed = max(0.0, (day - previous) / 400.0)
        factor = 0.5 ** (elapsed / BREADTH_HALF_LIFE)
        if factor < 1.0:
            values = self.opponent_weights[index]
            for opponent in list(values):
                decayed = values[opponent] * factor
                if decayed < 1e-10:
                    del values[opponent]
                else:
                    values[opponent] = decayed
        self.breadth_day[index] = day

    def effective_opponents(self, index: int) -> float:
        values = list(self.opponent_weights[index].values())
        if not values:
            return 0.0
        total = sum(values)
        return total * total / sum(value * value for value in values)

    def breadth(self, index: int) -> tuple[float, float]:
        effective = self.effective_opponents(index)
        return effective, effective / (effective + BREADTH_PRIOR)

    def reference(self, year: int, include: tuple[int, ...] = ()) -> float | None:
        eligible = {
            index
            for index in self.active_indices(year, 8)
            if self.games[index] >= MINIMUM_RECORD_MATCHES
        }
        eligible.update(
            index for index in include if self.games[index] >= MINIMUM_RECORD_MATCHES
        )
        if len(eligible) < 2:
            return None
        values = sorted((float(self.mean[index]) for index in eligible), reverse=True)
        elite = values[:10]
        return sum(elite) / len(elite)

    def record_values(self, index: int, baseline: float) -> dict[str, float]:
        effective, reliability = self.breadth(index)
        mean_rating = 2000.0 + reliability * (float(self.mean[index]) - baseline)
        standard_error = math.sqrt(max(0.0, float(self.covariance[index, index])))
        return {
            "mean": mean_rating,
            "se": standard_error,
            "rating": mean_rating - CONFIDENCE_Z * standard_error,
            "breadth": effective,
            "reliability": reliability,
            "latent": 1500.0 + float(self.mean[index]),
        }

    def record_for_pair(self, i: int, j: int, baseline: float) -> dict[str, float]:
        first = self.record_values(i, baseline)
        second = self.record_values(j, baseline)
        variance = max(
            0.0,
            float(
                self.covariance[i, i]
                + self.covariance[j, j]
                + 2.0 * self.covariance[i, j]
            ),
        )
        se = math.sqrt(variance)
        return {
            "rating1": first["rating"],
            "rating2": second["rating"],
            "mean1": first["mean"],
            "mean2": second["mean"],
            "combined_mean": first["mean"] + second["mean"],
            "combined_se": se,
            "combined": first["mean"] + second["mean"] - CONFIDENCE_Z * se,
        }

    def update_stats(self, i: int, j: int, match: Match) -> None:
        for index, gf, ga in ((i, match.score1, match.score2), (j, match.score2, match.score1)):
            stats = self.stats[index]
            stats["gf"] += gf
            stats["ga"] += ga
            if gf > ga:
                stats["wins"] += 1
                form = "W"
            elif gf < ga:
                stats["losses"] += 1
                form = "L"
            else:
                stats["draws"] += 1
                form = "D"
            stats["last5"] = (stats["last5"] + [form])[-5:]

    def replay(self) -> ReplayOutput:
        for match_id, match in enumerate(self.matches):
            while self.margin_window and self.margin_window[0][0] < match.year - 20:
                _, excess = self.margin_window.popleft()
                self.margin_excess_sum -= excess
            margin_environment = (20.0 * 1.10 + self.margin_excess_sum) / (
                20.0 + len(self.margin_window)
            )

            i, j = self.team_index[match.team1], self.team_index[match.team2]
            self.initialise(i, match.year, match.day)
            self.initialise(j, match.year, match.day)
            self.add_drift(i, match.day)
            self.add_drift(j, match.day)
            self.decay_breadth(i, match.day)
            self.decay_breadth(j, match.day)

            baseline = self.reference(match.year, (i, j))
            pre_first = self.record_values(i, baseline) if baseline is not None and self.games[i] >= 30 else None
            pre_second = self.record_values(j, baseline) if baseline is not None and self.games[j] >= 30 else None
            pre_pair = (
                self.record_for_pair(i, j, baseline)
                if baseline is not None and self.games[i] >= 30 and self.games[j] >= 30
                else None
            )

            scale = calibration_scale(match.year)
            difference = scale * (float(self.mean[i]) - float(self.mean[j])) + home_advantage(
                match.year
            ) * match.home_sign
            expected_score = float(logistic10(difference))
            difference_variance = max(
                0.0,
                float(
                    self.covariance[i, i]
                    + self.covariance[j, j]
                    - 2.0 * self.covariance[i, j]
                ),
            )
            level = self.level(match.tournament)
            probabilities = three_way_probabilities(
                difference,
                difference_variance,
                match.year,
                friendly=level == 0,
            )

            if pre_pair is not None:
                self.high_matches.append(
                    {
                        "id": match_id,
                        "date": match.date_text,
                        "team1": self.name(match.team1_code),
                        "team2": self.name(match.team2_code),
                        "canonical1": self.name(match.team1),
                        "canonical2": self.name(match.team2),
                        "code1": match.team1,
                        "code2": match.team2,
                        "score": f"{match.score1}-{match.score2}",
                        "tournament": self.tournament_name(match.tournament),
                        **pre_pair,
                    }
                )

            weight = QUALITY_SCALE * goal_weight(match.margin, margin_environment)
            beta = math.log(10.0) * scale / 400.0
            direction = self.covariance[:, i] - self.covariance[:, j]
            information = max(1e-8, expected_score * (1.0 - expected_score))
            curvature = weight * beta * beta * information
            denominator = 1.0 + curvature * difference_variance
            self.mean += direction * (
                weight * beta * (match.result - expected_score) / denominator
            )
            self.covariance -= np.outer(direction, direction) * (curvature / denominator)
            if match_id % 1000 == 0:
                self.covariance[:] = 0.5 * (self.covariance + self.covariance.T)

            self.games[i] += 1
            self.games[j] += 1
            self.last_year[i] = match.year
            self.last_year[j] = match.year
            self.opponent_weights[i][j] = self.opponent_weights[i].get(j, 0.0) + 1.0
            self.opponent_weights[j][i] = self.opponent_weights[j].get(i, 0.0) + 1.0
            if match.margin > 0:
                excess = float(min(match.margin, 7) - 1)
                self.margin_window.append((match.year, excess))
                self.margin_excess_sum += excess
            self.update_stats(i, j, match)

            post_baseline = self.reference(match.year)
            post_first = self.record_values(i, post_baseline) if post_baseline is not None and self.games[i] >= 30 else None
            post_second = self.record_values(j, post_baseline) if post_baseline is not None and self.games[j] >= 30 else None

            row = {
                "id": match_id,
                "date": match.date_text,
                "year": match.year,
                "a": match.team1,
                "b": match.team2,
                "an": self.name(match.team1_code),
                "bn": self.name(match.team2_code),
                "ac": self.name(match.team1),
                "bc": self.name(match.team2),
                "sa": match.score1,
                "sb": match.score2,
                "tc": match.tournament,
                "t": self.tournament_name(match.tournament),
                "level": level,
                "venue": self.name(match.venue) if match.venue else self.name(match.team1),
                "home": match.home_sign,
                "p": probabilities.tolist(),
                "expected": expected_score,
                "pre_a": None if pre_first is None else pre_first["rating"],
                "pre_b": None if pre_second is None else pre_second["rating"],
                "post_a": None if post_first is None else post_first["rating"],
                "post_b": None if post_second is None else post_second["rating"],
                "combined": None if pre_pair is None else pre_pair["combined"],
            }
            self.match_rows.append(row)

            for index, opponent, gf, ga, pre, post in (
                (i, j, match.score1, match.score2, pre_first, post_first),
                (j, i, match.score2, match.score1, pre_second, post_second),
            ):
                team_match = {
                    "id": match_id,
                    "date": match.date_text,
                    "opponent": self.name(self.teams[opponent]),
                    "opponent_code": self.teams[opponent],
                    "gf": gf,
                    "ga": ga,
                    "result": "W" if gf > ga else "L" if gf < ga else "D",
                    "tournament": self.tournament_name(match.tournament),
                    "level": level,
                    "venue": row["venue"],
                    "site": "N" if match.home_sign == 0 else (
                        "H" if (index == i and match.home_sign == 1) or (index == j and match.home_sign == -1) else "A"
                    ),
                    "pre": None if pre is None else pre["rating"],
                    "post": None if post is None else post["rating"],
                }
                self.team_matches[index].append(team_match)
                if post is not None:
                    point = {
                        "id": match_id,
                        "date": match.date_text,
                        "rating": post["rating"],
                        "mean": post["mean"],
                        "se": post["se"],
                        "latent": post["latent"],
                        "matches": int(self.games[index]),
                        "form": list(self.stats[index]["last5"]),
                        "opponent": self.name(self.teams[opponent]),
                        "score": f"{gf}-{ga}",
                    }
                    self.histories[index].append(point)
                    team = self.teams[index]
                    old_peak = self.peaks.get(team)
                    if old_peak is None or post["rating"] > old_peak["rating"]:
                        self.peaks[team] = {
                            "nation": self.name(team),
                            "code": team,
                            "historical_name": self.name(
                                match.team1_code if index == i else match.team2_code
                            ),
                            "rating": post["rating"],
                            "mean": post["mean"],
                            "se": post["se"],
                            "date": match.date_text,
                            "opponent": self.name(self.teams[opponent]),
                            "score": f"{gf}-{ga}",
                            "tournament": self.tournament_name(match.tournament),
                            "matches_played": int(self.games[index]),
                        }

        self.covariance[:] = 0.5 * (self.covariance + self.covariance.T)
        return self.finish()

    def finish(self) -> ReplayOutput:
        current_year = self.matches[-1].year
        baseline = self.reference(current_year)
        if baseline is None:
            raise RuntimeError("No current elite reference pool")

        all_teams: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        for index, team in enumerate(self.teams):
            if np.isnan(self.mean[index]):
                continue
            values = self.record_values(index, baseline)
            stats = self.stats[index]
            item = {
                "nation": self.name(team),
                "code": team,
                "rating": values["rating"],
                "mean": values["mean"],
                "se": values["se"],
                "latent": values["latent"],
                "breadth": values["breadth"],
                "reliability": values["reliability"],
                "matches": int(self.games[index]),
                "wins": stats["wins"],
                "draws": stats["draws"],
                "losses": stats["losses"],
                "gf": stats["gf"],
                "ga": stats["ga"],
                "form": stats["last5"],
                "last_year": int(self.last_year[index]),
                "peak": self.peaks.get(team),
            }
            all_teams.append(item)
            if (
                self.games[index] >= MINIMUM_RECORD_MATCHES
                and current_year - int(self.last_year[index]) <= 4
            ):
                current.append(item)

        current.sort(key=lambda item: (-item["rating"], item["nation"]))
        for rank, item in enumerate(current, start=1):
            item["rank"] = rank
        all_teams.sort(key=lambda item: item["nation"])
        peaks = sorted(self.peaks.values(), key=lambda item: (-item["rating"], item["nation"]))
        top_matches = sorted(
            self.high_matches,
            key=lambda item: (-item["combined"], item["date"], item["team1"]),
        )

        team_pages: dict[str, dict[str, Any]] = {}
        current_by_code = {item["code"]: item for item in all_teams}
        for index, team in enumerate(self.teams):
            team_pages[team] = {
                "team": current_by_code[team],
                "history": self.histories[index],
                "matches": list(reversed(self.team_matches[index])),
            }

        last_match = self.matches[-1]
        source_hash = hashlib.sha256()
        for path in sorted((self.source / "elo_pages").glob("*.tsv")):
            source_hash.update(path.name.encode("utf-8"))
            source_hash.update(path.read_bytes())
        supplemental = self.source / "supplemental_results.csv"
        if supplemental.exists():
            source_hash.update(supplemental.name.encode("utf-8"))
            source_hash.update(supplemental.read_bytes())

        summary = {
            "meta": {
                "model": "Network Football Elo — shared-opponent uncertainty model",
                "results_through": last_match.date_text,
                "matches": len(self.matches),
                "teams": self.count,
                "minimum_record_matches": MINIMUM_RECORD_MATCHES,
                "source_sha256": source_hash.hexdigest(),
                "confidence": CONFIDENCE,
                "generated_from_first_party_tsv": not bool(
                    (self.source / "supplemental_results.csv").exists()
                    and (self.source / "supplemental_results.csv").stat().st_size > 200
                ),
                "source_model": "validated WFE snapshot plus independently checked public-result feeds",
            },
            "current": current,
            "teams": all_teams,
            "peaks": peaks,
            "top_matches": top_matches[:500],
            "parameters": {
                "knot_years": KNOT_YEARS,
                "calibration_scale": CALIBRATION_SCALE,
                "home_advantage": HOME_ADVANTAGE,
                "draw_probability": DRAW_PROBABILITY,
                "goal_margin": {
                    "draw": G_DRAW,
                    "one": 1.0,
                    "two": G_TWO,
                    "three": G_THREE,
                    "tail": G_TAIL,
                    "environment_power": MARGIN_ENVIRONMENT_POWER,
                },
                "debut": {"offset": NEWCOMER_OFFSET, "pool_slope": ACTIVE_POOL_SLOPE},
                "network": {
                    "prior_sd": PRIOR_SD,
                    "drift_sd": DRIFT_SD,
                    "quality_scale": QUALITY_SCALE,
                    "competition_information_ratios": [1, 1, 1, 1, 1],
                },
                "forecast_temperature": {
                    "friendly": FRIENDLY_TEMPERATURE,
                    "competitive": COMPETITIVE_TEMPERATURE,
                },
            },
            "validation": {
                "matches": 46_801,
                "log_loss": 0.8842187104883077,
                "brier": 0.5205728970927473,
                "rps": 0.17317944421892195,
                "accuracy": 0.5909489113480482,
                "published_wfe_log_loss": 0.9026185159798847,
            },
        }
        state = {
            "year": current_year,
            "baseline": baseline,
            "codes": self.teams,
            "means": self.mean.tolist(),
            "covariance": self.covariance.reshape(-1).tolist(),
            "scale": calibration_scale(current_year),
            "home": home_advantage(current_year),
            "draw": draw_probability(current_year),
            "friendly_temperature": FRIENDLY_TEMPERATURE,
            "competitive_temperature": COMPETITIVE_TEMPERATURE,
            "nodes": QUADRATURE_NODES.tolist(),
            "weights": QUADRATURE_WEIGHTS.tolist(),
        }

        if not np.all(np.isfinite(self.mean[~np.isnan(self.mean)])):
            raise RuntimeError("Non-finite posterior means")
        if float(np.min(np.diag(self.covariance))) < -1e-6:
            raise RuntimeError("Negative posterior variance")
        return ReplayOutput(summary, state, self.match_rows, team_pages)


def run_replay(source: Path, config: Path) -> ReplayOutput:
    return NetworkEloReplay(source, config).replay()
