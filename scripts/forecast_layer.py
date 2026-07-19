#!/usr/bin/env python3
"""Causal score-based probability layer for the deployed NFELO replay.

The opponent-network rating is deliberately untouched.  This module keeps a
parallel attack/defence state, calibrates it from earlier completed years, and
combines only the resulting W/D/L probabilities with the network forecast.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar


EPSILON = 1e-15
MAX_POISSON_GOALS = 40


@dataclass(frozen=True, slots=True)
class ScoreParameters:
    name: str
    first_year: int
    last_year: int | None
    gap_scale: float
    learning_rate: float
    annual_decay: float


@dataclass(frozen=True, slots=True)
class Calibration:
    draw_log_tilt: float
    friendly_temperature: float
    competitive_temperature: float
    nfelo_weight: float
    training_first_year: int
    training_last_year: int
    training_matches: int


@dataclass(frozen=True, slots=True)
class ForecastObservation:
    year: int
    score_probabilities: tuple[float, float, float]
    nfelo_probabilities: tuple[float, float, float]
    outcome: int
    friendly: bool


def poisson_wdl(lambda1: float, lambda2: float) -> np.ndarray:
    """Independent-Poisson W/D/L probabilities with negligible truncated tail."""
    first = np.empty(MAX_POISSON_GOALS + 1, dtype=np.float64)
    second = np.empty(MAX_POISSON_GOALS + 1, dtype=np.float64)
    first[0] = math.exp(-lambda1)
    second[0] = math.exp(-lambda2)
    for goals in range(1, MAX_POISSON_GOALS + 1):
        first[goals] = first[goals - 1] * lambda1 / goals
        second[goals] = second[goals - 1] * lambda2 / goals
    first_cumulative = np.cumsum(first)
    second_cumulative = np.cumsum(second)
    win = float(np.sum(first[1:] * second_cumulative[:-1]))
    draw = float(first @ second)
    loss = float(np.sum(second[1:] * first_cumulative[:-1]))
    probabilities = np.asarray((win, draw, loss), dtype=np.float64)
    probabilities = np.maximum(probabilities, EPSILON)
    return probabilities / probabilities.sum()


def raked_score_matrix(
    lambda1: float,
    lambda2: float,
    final_probabilities: np.ndarray,
    maximum: int = MAX_POISSON_GOALS,
) -> np.ndarray:
    """Return scoreline cells whose W/D/L regions equal the final forecast.

    The independent-Poisson matrix supplies the relative scoreline shape.  Each
    win/draw/loss region is then rescaled to its final displayed probability.
    ``maximum=40`` leaves negligible omitted tail mass for deployed lambdas.
    """
    first = np.empty(maximum + 1, dtype=np.float64)
    second = np.empty(maximum + 1, dtype=np.float64)
    first[0] = math.exp(-lambda1)
    second[0] = math.exp(-lambda2)
    for goals in range(1, maximum + 1):
        first[goals] = first[goals - 1] * lambda1 / goals
        second[goals] = second[goals - 1] * lambda2 / goals
    raw = np.outer(first, second)
    rows, columns = np.indices(raw.shape)
    masks = (rows > columns, rows == columns, rows < columns)
    final = np.asarray(final_probabilities, dtype=np.float64)
    if final.shape != (3,) or np.any(final < 0.0) or not np.isfinite(final).all():
        raise ValueError("final_probabilities must be a finite three-element vector")
    final = final / final.sum()
    result = np.zeros_like(raw)
    for probability, mask in zip(final, masks):
        region = float(raw[mask].sum())
        if region <= 0.0:
            raise ValueError("Poisson score region has no probability mass")
        result[mask] = raw[mask] * probability / region
    return result


def calibrated_score_probabilities(
    raw: np.ndarray,
    friendly: np.ndarray | bool,
    draw_log_tilt: float,
    friendly_temperature: float,
    competitive_temperature: float,
) -> np.ndarray:
    """Apply the fitted draw tilt and match-class sharpness."""
    values = np.asarray(raw, dtype=np.float64)
    scalar = values.ndim == 1
    matrix = values[None, :].copy() if scalar else values.copy()
    matrix[:, 1] *= math.exp(float(np.clip(draw_log_tilt, -3.0, 3.0)))
    matrix /= matrix.sum(axis=1, keepdims=True)
    flags = np.asarray(friendly, dtype=bool)
    flags = np.asarray((bool(flags),)) if flags.ndim == 0 else flags
    temperatures = np.where(flags, friendly_temperature, competitive_temperature)
    matrix = np.power(np.maximum(matrix, EPSILON), temperatures[:, None])
    matrix /= matrix.sum(axis=1, keepdims=True)
    return matrix[0] if scalar else matrix


def outcome_preserving_pool(
    nfelo: np.ndarray, score: np.ndarray, nfelo_weight: float
) -> tuple[np.ndarray, bool]:
    """Move toward the score pool as far as the network's top pick permits.

    The previous release discarded the complete score correction whenever the
    linear pool crossed an argmax boundary.  The audited boundary gate keeps
    the same top outcome while retaining the largest safe fraction of that
    correction.  ``changed`` records whether clipping was required.
    """
    base = np.asarray(nfelo, dtype=np.float64)
    candidate = nfelo_weight * base + (1.0 - nfelo_weight) * np.asarray(score)
    candidate /= candidate.sum()
    winner = int(np.argmax(base))
    changed = int(np.argmax(candidate)) != winner
    if not changed:
        return candidate, False
    delta = candidate - base
    fraction = 1.0
    for competitor in range(3):
        if competitor == winner:
            continue
        closing = float(delta[competitor] - delta[winner])
        if closing > 0.0:
            fraction = min(
                fraction,
                float(base[winner] - base[competitor]) / closing,
            )
    fraction = max(0.0, min(1.0, fraction * (1.0 - 1e-10)))
    result = base + fraction * delta
    result = np.maximum(result, EPSILON)
    result /= result.sum()
    return result, True


def _log_loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    selected = probabilities[np.arange(len(outcomes)), outcomes]
    return float(-np.log(np.maximum(selected, EPSILON)).mean())


def fit_calibration(
    observations: list[ForecastObservation], first_year: int, last_year: int
) -> Calibration:
    """Fit calibration and pool weight using only the supplied prior matches."""
    selected = [
        observation
        for observation in observations
        if first_year <= observation.year <= last_year
    ]
    if len(selected) < 500:
        raise RuntimeError(
            f"Forecast calibration has only {len(selected)} matches for "
            f"{first_year}-{last_year}"
        )
    score = np.asarray([item.score_probabilities for item in selected], dtype=np.float64)
    nfelo = np.asarray([item.nfelo_probabilities for item in selected], dtype=np.float64)
    outcomes = np.asarray([item.outcome for item in selected], dtype=np.int8)
    friendly = np.asarray([item.friendly for item in selected], dtype=bool)

    def calibration_objective(vector: np.ndarray) -> float:
        probabilities = calibrated_score_probabilities(
            score, friendly, float(vector[0]), float(vector[1]), float(vector[2])
        )
        return _log_loss(probabilities, outcomes)

    fitted = minimize(
        calibration_objective,
        np.asarray((0.10, 0.95, 1.05), dtype=np.float64),
        method="Powell",
        bounds=((-0.35, 0.35), (0.75, 1.30), (0.75, 1.30)),
        options={"maxiter": 32, "xtol": 1e-7, "ftol": 1e-12},
    )
    draw_log_tilt, friendly_temperature, competitive_temperature = (
        float(value) for value in fitted.x
    )
    calibrated = calibrated_score_probabilities(
        score,
        friendly,
        draw_log_tilt,
        friendly_temperature,
        competitive_temperature,
    )
    weight_fit = minimize_scalar(
        lambda weight: _log_loss(
            float(weight) * nfelo + (1.0 - float(weight)) * calibrated,
            outcomes,
        ),
        method="bounded",
        bounds=(0.0, 1.0),
        options={"xatol": 1e-10},
    )
    # Powell can report its iteration cap after returning a valid finite point;
    # the audited fitting protocol accepts that point.  A non-finite objective
    # or a failed one-dimensional pool fit still stops publication.
    if not math.isfinite(float(fitted.fun)) or not weight_fit.success:
        raise RuntimeError(
            f"Forecast calibration failed: {fitted.message}; {weight_fit.message}"
        )
    values = (
        draw_log_tilt,
        friendly_temperature,
        competitive_temperature,
        float(weight_fit.x),
    )
    if not all(math.isfinite(value) for value in values):
        raise RuntimeError("Forecast calibration produced a non-finite value")
    return Calibration(
        draw_log_tilt=draw_log_tilt,
        friendly_temperature=friendly_temperature,
        competitive_temperature=competitive_temperature,
        nfelo_weight=float(weight_fit.x),
        training_first_year=first_year,
        training_last_year=last_year,
        training_matches=len(selected),
    )


class ScoreState:
    def __init__(self, team_count: int, parameters: ScoreParameters) -> None:
        self.parameters = parameters
        self.attack = np.zeros(team_count, dtype=np.float64)
        self.defence = np.zeros(team_count, dtype=np.float64)
        self.last_day = np.full(team_count, -1, dtype=np.int32)
        self.observations: deque[ForecastObservation] = deque()

    def trim_observations(self, first_year: int) -> None:
        while self.observations and self.observations[0].year < first_year:
            self.observations.popleft()

    def predict(
        self,
        first: int,
        second: int,
        day: int,
        expected_score: float,
        base_goal: float,
    ) -> tuple[np.ndarray, float, float]:
        for team in (first, second):
            previous = int(self.last_day[team])
            if previous >= 0:
                elapsed = max(0.0, (day - previous) / 400.0)
                decay = math.exp(-self.parameters.annual_decay * elapsed)
                self.attack[team] *= decay
                self.defence[team] *= decay
            self.last_day[team] = day
        expected = float(np.clip(expected_score, 1e-8, 1.0 - 1e-8))
        gap = 0.5 * self.parameters.gap_scale * math.log(expected / (1.0 - expected))
        lambda1 = float(np.clip(
            math.exp(math.log(base_goal) + gap + self.attack[first] - self.defence[second]),
            0.05,
            8.0,
        ))
        lambda2 = float(np.clip(
            math.exp(math.log(base_goal) - gap + self.attack[second] - self.defence[first]),
            0.05,
            8.0,
        ))
        return poisson_wdl(lambda1, lambda2), lambda1, lambda2

    def update(
        self,
        first: int,
        second: int,
        goals1: int,
        goals2: int,
        lambda1: float,
        lambda2: float,
    ) -> None:
        residual1 = float(np.clip(min(goals1, 7) - lambda1, -4.0, 4.0))
        residual2 = float(np.clip(min(goals2, 7) - lambda2, -4.0, 4.0))
        step = 0.5 * self.parameters.learning_rate
        self.attack[first] += step * residual1
        self.defence[second] -= step * residual1
        self.attack[second] += step * residual2
        self.defence[first] -= step * residual2


class ForecastLayer:
    """Parallel causal score states plus the fixed release-selection schedule."""

    def __init__(self, team_count: int, configuration: dict[str, Any]) -> None:
        self.active_from_year = int(configuration["active_from_year"])
        self.calibration_window_years = int(configuration["calibration_window_years"])
        self.goal_environment_years = int(configuration["goal_environment_years"])
        self.goal_prior_matches = int(configuration["goal_prior_matches"])
        self.goal_prior_per_team = float(configuration["goal_prior_per_team"])
        self.parameters = tuple(
            ScoreParameters(
                name=str(item["name"]),
                first_year=int(item["first_year"]),
                last_year=None if item.get("last_year") is None else int(item["last_year"]),
                gap_scale=float(item["gap_scale"]),
                learning_rate=float(item["learning_rate"]),
                annual_decay=float(item["annual_decay"]),
            )
            for item in configuration["release_schedule"]
        )
        self.states = {
            parameters.name: ScoreState(team_count, parameters)
            for parameters in self.parameters
        }
        self.current_year: int | None = None
        self.current_release: ScoreParameters | None = None
        self.current_calibration: Calibration | None = None
        self.calibrations: dict[int, Calibration] = {}
        self.goal_window: deque[tuple[int, int]] = deque()
        self.window_goals = 0
        self.last_day = -1
        self.gate_reversions = 0

    def release_for_year(self, year: int) -> ScoreParameters | None:
        if year < self.active_from_year:
            return None
        for parameters in self.parameters:
            if year >= parameters.first_year and (
                parameters.last_year is None or year <= parameters.last_year
            ):
                return parameters
        raise RuntimeError(f"No forecast-layer release covers {year}")

    def _start_year(self, year: int) -> None:
        first_training_year = year - self.calibration_window_years
        for state in self.states.values():
            state.trim_observations(first_training_year)
        self.current_year = year
        self.current_release = self.release_for_year(year)
        if self.current_release is None:
            self.current_calibration = None
            return
        state = self.states[self.current_release.name]
        self.current_calibration = fit_calibration(
            list(state.observations), first_training_year, year - 1
        )
        self.calibrations[year] = self.current_calibration

    def _base_goal(self, year: int) -> float:
        while self.goal_window and self.goal_window[0][0] < year - self.goal_environment_years:
            _, goals = self.goal_window.popleft()
            self.window_goals -= goals
        prior_goals = 2.0 * self.goal_prior_matches * self.goal_prior_per_team
        value = (prior_goals + self.window_goals) / (
            2.0 * self.goal_prior_matches + 2.0 * len(self.goal_window)
        )
        return float(np.clip(value, 0.55, 2.50))

    def ensure_calibration_year(self, year: int) -> None:
        """Advance calibration when a new year begins before its first result."""
        if self.current_year is None or year > self.current_year:
            self._start_year(year)

    def predict_day(
        self,
        rows: list[dict[str, Any]],
    ) -> list[np.ndarray]:
        """Forecast a complete date from one frozen state, then learn from it."""
        if not rows:
            return []
        year = int(rows[0]["year"])
        day = int(rows[0]["day"])
        if any(int(row["year"]) != year or int(row["day"]) != day for row in rows):
            raise ValueError("A forecast batch must contain exactly one complete date")
        if year != self.current_year:
            self._start_year(year)
        base_goal = self._base_goal(year)
        pending: list[tuple[dict[str, Any], dict[str, tuple[np.ndarray, float, float]]]] = []
        results: list[np.ndarray] = []
        for row in rows:
            first = int(row["first"])
            second = int(row["second"])
            expected_score = float(row["expected_score"])
            friendly = bool(row["friendly"])
            predictions = {
                name: state.predict(first, second, day, expected_score, base_goal)
                for name, state in self.states.items()
            }
            final = np.asarray(row["nfelo_probabilities"], dtype=np.float64)
            if self.current_release is not None and self.current_calibration is not None:
                raw = predictions[self.current_release.name][0]
                score = calibrated_score_probabilities(
                    raw,
                    friendly,
                    self.current_calibration.draw_log_tilt,
                    self.current_calibration.friendly_temperature,
                    self.current_calibration.competitive_temperature,
                )
                final, changed = outcome_preserving_pool(
                    final, score, self.current_calibration.nfelo_weight
                )
                self.gate_reversions += int(changed)
            results.append(final)
            pending.append((row, predictions))

        # No result enters any score state until every forecast is stored.
        for row, predictions in pending:
            first = int(row["first"])
            second = int(row["second"])
            goals1 = int(row["goals1"])
            goals2 = int(row["goals2"])
            friendly = bool(row["friendly"])
            network = np.asarray(row["nfelo_probabilities"], dtype=np.float64)
            outcome = 0 if goals1 > goals2 else 1 if goals1 == goals2 else 2
            for name, state in self.states.items():
                raw, lambda1, lambda2 = predictions[name]
                state.observations.append(ForecastObservation(
                    year=year,
                    score_probabilities=tuple(float(value) for value in raw),
                    nfelo_probabilities=tuple(float(value) for value in network),
                    outcome=outcome,
                    friendly=friendly,
                ))
                state.update(first, second, goals1, goals2, lambda1, lambda2)
            goals = goals1 + goals2
            self.goal_window.append((year, goals))
            self.window_goals += goals
        self.last_day = day
        return results

    def predict_and_update(
        self,
        *,
        first: int,
        second: int,
        day: int,
        year: int,
        goals1: int,
        goals2: int,
        expected_score: float,
        nfelo_probabilities: np.ndarray,
        friendly: bool,
    ) -> np.ndarray:
        """Compatibility wrapper for callers forecasting a single match."""
        return self.predict_day([{
            "first": first,
            "second": second,
            "day": day,
            "year": year,
            "goals1": goals1,
            "goals2": goals2,
            "expected_score": expected_score,
            "nfelo_probabilities": nfelo_probabilities,
            "friendly": friendly,
        }])[0]

    def historical_context(self) -> dict[str, Any]:
        """Compact causal score context for a completed historical matchday."""
        context: dict[str, Any] = {
            "year": self.current_year,
            "release": None,
            "base_goal": self._base_goal(int(self.current_year)),
            "as_of_day": self.last_day,
            "parameters": None,
            "calibration": None,
        }
        if self.current_release is None or self.current_calibration is None:
            return context
        calibration = self.current_calibration
        context["release"] = self.current_release.name
        context["parameters"] = {
            "gap_scale": self.current_release.gap_scale,
            "annual_decay": self.current_release.annual_decay,
        }
        context["calibration"] = {
            "draw_log_tilt": calibration.draw_log_tilt,
            "friendly_temperature": calibration.friendly_temperature,
            "competitive_temperature": calibration.competitive_temperature,
            "nfelo_weight": calibration.nfelo_weight,
            "score_weight": 1.0 - calibration.nfelo_weight,
        }
        return context

    def historical_team_state(self, team: int) -> dict[str, Any] | None:
        if self.current_release is None or self.current_calibration is None:
            return None
        state = self.states[self.current_release.name]
        return {
            "release": self.current_release.name,
            "attack": float(state.attack[team]),
            "defence": float(state.defence[team]),
            "last_day": int(state.last_day[team]),
        }

    def export(self) -> dict[str, Any]:
        if self.current_release is None or self.current_calibration is None:
            raise RuntimeError("Forecast layer has no current calibrated release")
        state = self.states[self.current_release.name]
        calibration = self.current_calibration
        base_goal = self._base_goal(int(self.current_year))
        return {
            "active_from_year": self.active_from_year,
            "calibration_window_years": self.calibration_window_years,
            "goal_environment_years": self.goal_environment_years,
            "goal_prior_matches": self.goal_prior_matches,
            "goal_prior_per_team": self.goal_prior_per_team,
            "release": self.current_release.name,
            "parameters": {
                "gap_scale": self.current_release.gap_scale,
                "learning_rate": self.current_release.learning_rate,
                "annual_decay": self.current_release.annual_decay,
                "goal_update_cap": 7,
                "goal_residual_cap": 4,
            },
            "calibration": {
                "year": self.current_year,
                "training_first_year": calibration.training_first_year,
                "training_last_year": calibration.training_last_year,
                "training_matches": calibration.training_matches,
                "draw_log_tilt": calibration.draw_log_tilt,
                "friendly_temperature": calibration.friendly_temperature,
                "competitive_temperature": calibration.competitive_temperature,
                "nfelo_weight": calibration.nfelo_weight,
                "score_weight": 1.0 - calibration.nfelo_weight,
            },
            "attack": state.attack.tolist(),
            "defence": state.defence.tolist(),
            "last_day": state.last_day.tolist(),
            "base_goal": base_goal,
            "as_of_day": self.last_day,
            "gate_reversions": self.gate_reversions,
        }

    def public_parameters(self) -> dict[str, Any]:
        exported = self.export()
        return {
            key: exported[key]
            for key in (
                "active_from_year",
                "calibration_window_years",
                "goal_environment_years",
                "goal_prior_matches",
                "goal_prior_per_team",
                "release",
                "parameters",
                "calibration",
                "gate_reversions",
            )
        }


def forecast_from_snapshot(
    *,
    snapshot: dict[str, Any],
    first: int,
    second: int,
    day: int,
    expected_score: float,
    nfelo_probabilities: np.ndarray,
    friendly: bool,
) -> np.ndarray:
    """Use the exported current score state for fixtures and calculators."""
    parameters = snapshot["parameters"]
    decay_rate = float(parameters["annual_decay"])

    def decayed(values: list[float], team: int) -> float:
        previous = int(snapshot["last_day"][team])
        elapsed = 0.0 if previous < 0 else max(0.0, (day - previous) / 400.0)
        return float(values[team]) * math.exp(-decay_rate * elapsed)

    expected = float(np.clip(expected_score, 1e-8, 1.0 - 1e-8))
    gap = 0.5 * float(parameters["gap_scale"]) * math.log(expected / (1.0 - expected))
    attack1 = decayed(snapshot["attack"], first)
    attack2 = decayed(snapshot["attack"], second)
    defence1 = decayed(snapshot["defence"], first)
    defence2 = decayed(snapshot["defence"], second)
    base_goal = float(snapshot["base_goal"])
    lambda1 = float(np.clip(math.exp(math.log(base_goal) + gap + attack1 - defence2), 0.05, 8.0))
    lambda2 = float(np.clip(math.exp(math.log(base_goal) - gap + attack2 - defence1), 0.05, 8.0))
    raw = poisson_wdl(lambda1, lambda2)
    calibration = snapshot["calibration"]
    score = calibrated_score_probabilities(
        raw,
        friendly,
        float(calibration["draw_log_tilt"]),
        float(calibration["friendly_temperature"]),
        float(calibration["competitive_temperature"]),
    )
    return outcome_preserving_pool(
        np.asarray(nfelo_probabilities, dtype=np.float64),
        score,
        float(calibration["nfelo_weight"]),
    )[0]
