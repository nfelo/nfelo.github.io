#!/usr/bin/env python3
"""Deployed opponent-network rating model and record-rating layer."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np

from forecast_layer import ForecastLayer
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
RETROSPECTIVE_FIRST_YEAR = 1960
RETROSPECTIVE_CUTOFF = "2026-07-11"

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


def joint_gaussian_update(
    mean: np.ndarray,
    covariance: np.ndarray,
    observations: list[tuple[int, int, float, float]],
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Apply frozen same-date observations as one Gaussian information update.

    Each observation is ``(first, second, curvature, gradient)``.  Curvatures
    and gradients must have been evaluated from the shared pre-date state.  The
    rank-one covariance calculations are a Woodbury implementation of

        C' = [C^-1 + sum(c_k x_k x_k^T)]^-1
        m' = m + C' sum(g_k x_k)

    and are therefore invariant to within-date row order apart from floating
    point round-off.  Per-observation mean contributions sum to the complete
    mean movement and are used only to attribute upset points.
    """
    updated = np.asarray(covariance, dtype=np.float64).copy()
    score = np.zeros(len(mean), dtype=np.float64)
    for first, second, curvature, gradient in observations:
        score[first] += gradient
        score[second] -= gradient
        direction = updated[:, first] - updated[:, second]
        variance = max(
            0.0,
            float(
                updated[first, first]
                + updated[second, second]
                - 2.0 * updated[first, second]
            ),
        )
        factor = curvature / (1.0 + curvature * variance)
        updated -= np.outer(direction, direction) * factor
    updated = 0.5 * (updated + updated.T)
    result_mean = np.asarray(mean, dtype=np.float64) + updated @ score
    contributions = [
        (updated[:, first] - updated[:, second]) * gradient
        for first, second, _, gradient in observations
    ]
    return result_mean, updated, contributions


@dataclass(slots=True)
class ReplayOutput:
    summary: dict[str, Any]
    state: dict[str, Any]
    matches: list[dict[str, Any]]
    team_pages: dict[str, dict[str, Any]]
    prediction_contexts: list[dict[str, Any]]


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
        # WFER retains the obsolete label “Eastern Samoa”; use the current team name.
        self.team_names["AS"] = "American Samoa"
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

        forecast_configuration = json.loads(
            (config / "forecast_layer.json").read_text(encoding="utf-8")
        )
        self.forecast_layer = ForecastLayer(self.count, forecast_configuration)

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
        self.record_peaks: dict[str, dict[str, Any]] = {}
        self.high_matches: list[dict[str, Any]] = []
        self.match_rows: list[dict[str, Any]] = []
        self.prediction_contexts: list[dict[str, Any]] = []
        self.margin_window: deque[tuple[int, float]] = deque()
        self.margin_excess_sum = 0.0
        self.validation_totals = {
            "final": {"matches": 0, "log_loss": 0.0, "brier": 0.0, "rps": 0.0, "correct": 0},
            "network": {"matches": 0, "log_loss": 0.0, "brier": 0.0, "rps": 0.0, "correct": 0},
        }

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

    def initialise_with(self, index: int, day: int, value: float) -> None:
        if not np.isnan(self.mean[index]):
            return
        self.mean[index] = value
        self.covariance[index, index] = PRIOR_SD**2
        self.last_day[index] = day
        self.breadth_day[index] = day

    def initialise(self, index: int, year: int, day: int) -> None:
        self.initialise_with(index, day, self.debut_mean(year))

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

    def reference_context(
        self, year: int, include: tuple[int, ...] = ()
    ) -> tuple[float, tuple[int, ...]] | None:
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
        elite = tuple(sorted(eligible, key=lambda index: float(self.mean[index]), reverse=True)[:10])
        return sum(float(self.mean[index]) for index in elite) / len(elite), elite

    def reference(self, year: int, include: tuple[int, ...] = ()) -> float | None:
        context = self.reference_context(year, include)
        return None if context is None else context[0]

    def strength_variance(self, index: int, elite: tuple[int, ...]) -> float:
        count = len(elite)
        elite_block = self.covariance[np.ix_(elite, elite)]
        baseline_variance = float(elite_block.sum()) / (count * count)
        baseline_covariance = float(self.covariance[index, list(elite)].sum()) / count
        return max(
            0.0,
            float(self.covariance[index, index]) + baseline_variance - 2.0 * baseline_covariance,
        )

    def record_values(
        self, index: int, reference: tuple[float, tuple[int, ...]]
    ) -> dict[str, float]:
        baseline, elite = reference
        effective, reliability = self.breadth(index)
        deviation = float(self.mean[index]) - baseline
        strength_rating = 2000.0 + deviation
        strength_se = math.sqrt(self.strength_variance(index, elite))
        record_mean = 2000.0 + reliability * deviation
        record_se = reliability * strength_se
        return {
            "rating": strength_rating,
            "mean": strength_rating,
            "se": strength_se,
            "record_mean": record_mean,
            "record_se": record_se,
            "record_rating": record_mean - CONFIDENCE_Z * record_se,
            "breadth": effective,
            "reliability": reliability,
            "latent": 1500.0 + float(self.mean[index]),
        }

    def record_for_pair(
        self, i: int, j: int, reference: tuple[float, tuple[int, ...]]
    ) -> dict[str, float]:
        baseline, elite = reference
        first = self.record_values(i, reference)
        second = self.record_values(j, reference)
        count = len(elite)
        coefficients = np.zeros(self.count, dtype=np.float64)
        coefficients[i] += first["reliability"]
        coefficients[j] += second["reliability"]
        coefficients[list(elite)] -= (
            first["reliability"] + second["reliability"]
        ) / count
        record_variance = max(0.0, float(coefficients @ self.covariance @ coefficients))
        record_se = math.sqrt(record_variance)
        return {
            "rating1": first["rating"],
            "rating2": second["rating"],
            "combined_strength": first["rating"] + second["rating"],
            "record_rating1": first["record_rating"],
            "record_rating2": second["record_rating"],
            "combined_mean": first["record_mean"] + second["record_mean"],
            "combined_se": record_se,
            "combined": first["record_mean"] + second["record_mean"] - CONFIDENCE_Z * record_se,
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

    @staticmethod
    def add_validation_score(
        totals: dict[str, float | int], probabilities: np.ndarray, outcome: int
    ) -> None:
        one_hot = np.zeros(3, dtype=np.float64)
        one_hot[outcome] = 1.0
        difference = np.asarray(probabilities, dtype=np.float64) - one_hot
        cumulative = np.cumsum(difference)[:2]
        totals["matches"] += 1
        totals["log_loss"] += -math.log(max(float(probabilities[outcome]), 1e-15))
        totals["brier"] += float(difference @ difference)
        totals["rps"] += 0.5 * float(cumulative @ cumulative)
        totals["correct"] += int(int(np.argmax(probabilities)) == outcome)

    @staticmethod
    def finish_validation_score(totals: dict[str, float | int]) -> dict[str, float | int]:
        matches = int(totals["matches"])
        if matches == 0:
            raise RuntimeError("Retrospective validation window contains no matches")
        return {
            "matches": matches,
            "log_loss": float(totals["log_loss"]) / matches,
            "brier": float(totals["brier"]) / matches,
            "rps": float(totals["rps"]) / matches,
            "accuracy": int(totals["correct"]) / matches,
        }

    def replay(self) -> ReplayOutput:
        start = 0
        while start < len(self.matches):
            first_match = self.matches[start]
            complete_date = first_match.month > 0 and first_match.day_of_month > 0
            end = start + 1
            if complete_date:
                while (
                    end < len(self.matches)
                    and self.matches[end].day == first_match.day
                    and self.matches[end].month > 0
                    and self.matches[end].day_of_month > 0
                ):
                    end += 1
            day_matches = self.matches[start:end]
            year = first_match.year
            while self.margin_window and self.margin_window[0][0] < year - 20:
                _, excess = self.margin_window.popleft()
                self.margin_excess_sum -= excess
            margin_environment = (20.0 * 1.10 + self.margin_excess_sum) / (
                20.0 + len(self.margin_window)
            )

            participants = sorted({
                self.team_index[match.team1] for match in day_matches
            } | {
                self.team_index[match.team2] for match in day_matches
            })
            debut = self.debut_mean(year)
            for index in participants:
                self.initialise_with(index, first_match.day, debut)
            for index in participants:
                self.add_drift(index, first_match.day)
                self.decay_breadth(index, first_match.day)

            reference = self.reference_context(year, tuple(participants))
            pending: list[dict[str, Any]] = []
            score_rows: list[dict[str, Any]] = []
            for offset, match in enumerate(day_matches):
                match_id = start + offset
                i, j = self.team_index[match.team1], self.team_index[match.team2]
                pre_first = (
                    self.record_values(i, reference)
                    if reference is not None and self.games[i] >= 30 else None
                )
                pre_second = (
                    self.record_values(j, reference)
                    if reference is not None and self.games[j] >= 30 else None
                )
                pre_pair = (
                    self.record_for_pair(i, j, reference)
                    if reference is not None and self.games[i] >= 30 and self.games[j] >= 30
                    else None
                )
                scale = calibration_scale(match.year)
                difference = scale * (float(self.mean[i]) - float(self.mean[j]))
                difference += home_advantage(match.year) * match.home_sign
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
                network_probabilities = three_way_probabilities(
                    difference,
                    difference_variance,
                    match.year,
                    friendly=level == 0,
                )
                pending.append({
                    "id": match_id, "match": match, "i": i, "j": j,
                    "pre_first": pre_first, "pre_second": pre_second,
                    "pre_pair": pre_pair, "scale": scale,
                    "difference": difference, "expected": expected_score,
                    "variance": difference_variance, "level": level,
                    "network": network_probabilities,
                })
                score_rows.append({
                    "first": i, "second": j, "day": match.day, "year": match.year,
                    "goals1": match.score1, "goals2": match.score2,
                    "expected_score": expected_score,
                    "nfelo_probabilities": network_probabilities,
                    "friendly": level == 0,
                })

            probabilities = self.forecast_layer.predict_day(score_rows)
            for item, forecast in zip(pending, probabilities):
                item["probabilities"] = forecast
                match = item["match"]
                if (
                    match.year >= RETROSPECTIVE_FIRST_YEAR
                    and match.date_text <= RETROSPECTIVE_CUTOFF
                ):
                    outcome = 0 if match.score1 > match.score2 else 1 if match.score1 == match.score2 else 2
                    self.add_validation_score(
                        self.validation_totals["final"], forecast, outcome
                    )
                    self.add_validation_score(
                        self.validation_totals["network"], item["network"], outcome
                    )
                if item["pre_pair"] is not None:
                    self.high_matches.append({
                        "id": item["id"],
                        "date": match.date_text,
                        "team1": self.name(match.team1_code),
                        "team2": self.name(match.team2_code),
                        "canonical1": self.name(match.team1),
                        "canonical2": self.name(match.team2),
                        "code1": match.team1,
                        "code2": match.team2,
                        "score": f"{match.score1}-{match.score2}",
                        "tournament": self.tournament_name(match.tournament),
                        **item["pre_pair"],
                    })

            # Frozen gradients are combined with one joint Gaussian precision
            # update.  This is invariant to the source's within-date row order.
            observations: list[tuple[int, int, float, float]] = []
            for item in pending:
                match = item["match"]
                weight = QUALITY_SCALE * goal_weight(match.margin, margin_environment)
                beta = math.log(10.0) * item["scale"] / 400.0
                information = max(1e-8, item["expected"] * (1.0 - item["expected"]))
                curvature = weight * beta * beta * information
                gradient = weight * beta * (match.result - item["expected"])
                observations.append((item["i"], item["j"], curvature, gradient))
            self.mean, self.covariance, contributions = joint_gaussian_update(
                self.mean, self.covariance, observations
            )
            for item, contribution in zip(pending, contributions):
                item["mean_contribution"] = contribution

            for item in pending:
                match, i, j = item["match"], item["i"], item["j"]
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

            post_reference = self.reference_context(year)
            post_values = {
                index: (
                    self.record_values(index, post_reference)
                    if post_reference is not None and self.games[index] >= 30 else None
                )
                for index in participants
            }
            participant_events: dict[int, list[tuple[dict[str, Any], int]]] = {
                index: [] for index in participants
            }
            for item in pending:
                match, i, j = item["match"], item["i"], item["j"]
                pre_first, pre_second = item["pre_first"], item["pre_second"]
                post_first, post_second = post_values[i], post_values[j]
                pre_pair = item["pre_pair"]
                row = {
                    "id": item["id"], "date": match.date_text, "year": match.year,
                    "a": match.team1, "b": match.team2,
                    "an": self.name(match.team1_code), "bn": self.name(match.team2_code),
                    "ac": self.name(match.team1), "bc": self.name(match.team2),
                    "sa": match.score1, "sb": match.score2,
                    "tc": match.tournament, "t": self.tournament_name(match.tournament),
                    "level": item["level"],
                    "venue": self.name(match.venue) if match.venue else self.name(match.team1),
                    "home": match.home_sign,
                    "p": item["probabilities"].tolist(),
                    "expected": item["expected"],
                    "pre_a": None if pre_first is None else pre_first["rating"],
                    "pre_b": None if pre_second is None else pre_second["rating"],
                    "post_a": None if post_first is None else post_first["rating"],
                    "post_b": None if post_second is None else post_second["rating"],
                    "impact_a": float(item["mean_contribution"][i]),
                    "impact_b": float(item["mean_contribution"][j]),
                    "combined": None if pre_pair is None else pre_pair["combined_strength"],
                    "record_combined": None if pre_pair is None else pre_pair["combined"],
                }
                self.match_rows.append(row)
                for index, opponent, gf, ga, pre, post, opponent_pre, opponent_post in (
                    (i, j, match.score1, match.score2, pre_first, post_first, pre_second, post_second),
                    (j, i, match.score2, match.score1, pre_second, post_second, pre_first, post_first),
                ):
                    historical_team_code = match.team1_code if index == i else match.team2_code
                    historical_opponent_code = match.team2_code if index == i else match.team1_code
                    self.team_matches[index].append({
                        "id": item["id"], "date": match.date_text,
                        "team_name": self.name(historical_team_code),
                        "opponent": self.name(historical_opponent_code),
                        "opponent_code": self.teams[opponent],
                        "gf": gf, "ga": ga,
                        "result": "W" if gf > ga else "L" if gf < ga else "D",
                        "tournament": self.tournament_name(match.tournament),
                        "level": item["level"], "venue": row["venue"],
                        "site": "N" if match.home_sign == 0 else (
                            "H" if (index == i and match.home_sign == 1)
                            or (index == j and match.home_sign == -1) else "A"
                        ),
                        "pre": None if pre is None else pre["rating"],
                        "post": None if post is None else post["rating"],
                        "opponent_pre": None if opponent_pre is None else opponent_pre["rating"],
                        "opponent_post": None if opponent_post is None else opponent_post["rating"],
                    })
                    participant_events[index].append((item, opponent))

            # One ranking event per team and date.  If a team somehow played
            # twice, the event describes the complete matchday rather than an
            # arbitrary row order.
            for index, events in participant_events.items():
                post = post_values[index]
                if post is None:
                    continue
                item, opponent = events[-1]
                match = item["match"]
                historical_code = match.team1_code if index == item["i"] else match.team2_code
                if len(events) == 1:
                    gf = match.score1 if index == item["i"] else match.score2
                    ga = match.score2 if index == item["i"] else match.score1
                    opponent_name = self.name(self.teams[opponent])
                    score_text = f"{gf}-{ga}"
                    tournament_name = self.tournament_name(match.tournament)
                else:
                    opponent_name = "Multiple opponents"
                    score_text = f"{len(events)} matches"
                    tournament_name = "Multiple competitions"
                point = {
                    "id": max(event["id"] for event, _ in events),
                    "date": match.date_text,
                    "rating": post["rating"], "mean": post["mean"], "se": post["se"],
                    "record_rating": post["record_rating"],
                    "record_mean": post["record_mean"], "record_se": post["record_se"],
                    "latent": post["latent"], "reliability": post["reliability"],
                    "score_state": self.forecast_layer.historical_team_state(index),
                    "matches": int(self.games[index]), "form": list(self.stats[index]["last5"]),
                    "opponent": opponent_name, "historical_name": self.name(historical_code),
                    "score": score_text,
                }
                self.histories[index].append(point)
                team = self.teams[index]
                peak_payload = {
                    "nation": self.name(team), "code": team,
                    "historical_name": self.name(historical_code),
                    "rating": post["rating"], "mean": post["mean"], "se": post["se"],
                    "record_rating": post["record_rating"],
                    "record_mean": post["record_mean"], "record_se": post["record_se"],
                    "date": match.date_text, "opponent": opponent_name,
                    "score": score_text, "tournament": tournament_name,
                    "matches_played": int(self.games[index]),
                }
                old_peak = self.peaks.get(team)
                if old_peak is None or post["rating"] > old_peak["rating"]:
                    self.peaks[team] = dict(peak_payload)
                old_record_peak = self.record_peaks.get(team)
                if old_record_peak is None or post["record_rating"] > old_record_peak["record_rating"]:
                    self.record_peaks[team] = dict(peak_payload)

            post_margin_environment = (20.0 * 1.10 + self.margin_excess_sum) / (
                20.0 + len(self.margin_window)
            )
            self.prediction_contexts.append({
                "date": first_match.date_text,
                "context": self.forecast_layer.historical_context(),
                "margin_environment": post_margin_environment,
            })
            start = end

        self.covariance[:] = 0.5 * (self.covariance + self.covariance.T)
        return self.finish()

    def finish(self) -> ReplayOutput:
        current_year = self.matches[-1].year
        self.forecast_layer.ensure_calibration_year(max(current_year, date.today().year))
        reference = self.reference_context(current_year)
        if reference is None:
            raise RuntimeError("No current elite reference pool")
        baseline = reference[0]

        all_teams: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        for index, team in enumerate(self.teams):
            if np.isnan(self.mean[index]):
                continue
            values = self.record_values(index, reference)
            stats = self.stats[index]
            item = {
                "nation": self.name(team),
                "code": team,
                "rating": values["rating"],
                "mean": values["mean"],
                "se": values["se"],
                "record_rating": values["record_rating"],
                "record_mean": values["record_mean"],
                "record_se": values["record_se"],
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
                "record_peak": self.record_peaks.get(team),
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
        record_peaks = sorted(
            self.record_peaks.values(),
            key=lambda item: (-item["record_rating"], item["nation"]),
        )
        top_matches = sorted(
            self.high_matches,
            key=lambda item: (-item["combined"], item["date"], item["team1"]),
        )
        upsets: list[dict[str, Any]] = []
        for match in self.match_rows:
            if match["sa"] == match["sb"] or any(
                match[key] is None for key in ("pre_a", "pre_b", "post_a", "post_b")
            ):
                continue
            first_won = match["sa"] > match["sb"]
            winner_gain = match["impact_a"] if first_won else match["impact_b"]
            loser_loss = -match["impact_b"] if first_won else -match["impact_a"]
            points = 0.5 * (winner_gain + loser_loss)
            if winner_gain <= 0 or loser_loss <= 0:
                continue
            upsets.append({
                "id": match["id"], "date": match["date"],
                "team1": match["an"], "team2": match["bn"],
                "code1": match["a"], "code2": match["b"],
                "score": f'{match["sa"]}-{match["sb"]}',
                "tournament": match["t"], "points": points,
                "winner_gain": winner_gain, "loser_loss": loser_loss,
                "winner": match["an"] if first_won else match["bn"],
                "loser": match["bn"] if first_won else match["an"],
            })
        upsets.sort(key=lambda item: (-item["points"], item["date"], item["id"]))

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

        retrospective = self.finish_validation_score(self.validation_totals["final"])
        retrospective_network = self.finish_validation_score(
            self.validation_totals["network"]
        )
        if retrospective["matches"] != retrospective_network["matches"]:
            raise RuntimeError("Retrospective validation component counts differ")

        summary = {
            "meta": {
                "model": "Network Football Elo — shared-opponent uncertainty model",
                "methodology_version": "2026-07-19-audited-date-batch",
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
            "record_peaks": record_peaks,
            "top_matches": top_matches[:500],
            "upsets": upsets[:500],
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
                "forecast_layer": self.forecast_layer.public_parameters(),
            },
            "validation": {
                "primary_evidence": "nested_historical_holdout",
                "nested": {
                    "description": "Original five-block rolling historical holdout",
                    "matches": 46_801,
                    "log_loss": 0.8842187104883077,
                    "accuracy": 0.59095,
                    "best_scalar_elo_log_loss": 0.8929697600474259,
                    "published_wfe_log_loss": 0.9026185159798847,
                },
                "retrospective": {
                    "description": "Final constants replayed by the deployed chronology through the fixed audit cutoff",
                    **retrospective,
                    "network_only_log_loss": retrospective_network["log_loss"],
                    "network_only_brier": retrospective_network["brier"],
                    "network_only_rps": retrospective_network["rps"],
                    "network_only_accuracy": retrospective_network["accuracy"],
                    "cutoff": RETROSPECTIVE_CUTOFF,
                    "unknown_dates": "sequential",
                },
            },
        }
        forecast_state = self.forecast_layer.export()
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
            "forecast_layer": forecast_state,
        }

        if not np.all(np.isfinite(self.mean[~np.isnan(self.mean)])):
            raise RuntimeError("Non-finite posterior means")
        if float(np.min(np.diag(self.covariance))) < -1e-6:
            raise RuntimeError("Negative posterior variance")
        return ReplayOutput(
            summary, state, self.match_rows, team_pages, self.prediction_contexts
        )


def run_replay(source: Path, config: Path) -> ReplayOutput:
    return NetworkEloReplay(source, config).replay()
