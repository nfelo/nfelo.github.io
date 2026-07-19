#!/usr/bin/env python3
"""Replay the deployed score layer with all same-date matches forecast jointly."""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd


def metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float | int]:
    one = np.eye(3)[outcomes]
    cumulative = np.cumsum(probabilities, axis=1)[:, :2] - np.cumsum(one, axis=1)[:, :2]
    return {
        "matches": int(len(outcomes)),
        "log_loss": float(-np.log(np.maximum(probabilities[np.arange(len(outcomes)), outcomes], 1e-15)).mean()),
        "brier": float(np.square(probabilities - one).sum(axis=1).mean()),
        "rps": float(0.5 * np.square(cumulative).sum(axis=1).mean()),
        "accuracy": float((probabilities.argmax(axis=1) == outcomes).mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo / "scripts"))
    from forecast_layer import (  # noqa: E402
        ForecastObservation,
        ScoreParameters,
        ScoreState,
        calibrated_score_probabilities,
        fit_calibration,
        outcome_preserving_pool,
    )

    source = np.load(args.source)
    network_frame = pd.read_csv(args.network, sep="\t")
    if len(network_frame) != len(source["year"]):
        raise RuntimeError("network and source row counts differ")
    network = network_frame[["pw", "pd", "pl"]].to_numpy(float)
    expected = network_frame["expected"].to_numpy(float)
    configuration = json.loads(
        (args.repo / "config" / "forecast_layer.json").read_text(encoding="utf-8")
    )
    parameters = tuple(
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
    states = {item.name: ScoreState(len(source["teams"]), item) for item in parameters}
    state_names = [item.name for item in parameters]
    state_index = {name: index for index, name in enumerate(state_names)}

    count = len(source["year"])
    all_raw = np.empty((count, len(parameters), 3), dtype=float)
    calibrated = np.empty((count, 3), dtype=float)
    ungated = np.empty((count, 3), dtype=float)
    final = np.empty((count, 3), dtype=float)
    calibration_values = np.full((count, 4), np.nan, dtype=float)
    reverted = np.zeros(count, dtype=bool)
    releases = np.full(count, "", dtype="U21")
    base_goals = np.empty(count, dtype=float)

    goal_window: deque[tuple[int, int]] = deque()
    window_goals = 0
    current_year: int | None = None
    current_release: ScoreParameters | None = None
    current_calibration = None
    window_years = int(configuration["calibration_window_years"])
    environment_years = int(configuration["goal_environment_years"])
    prior_matches = int(configuration["goal_prior_matches"])
    prior_per_team = float(configuration["goal_prior_per_team"])

    def release_for_year(year: int) -> ScoreParameters | None:
        if year < int(configuration["active_from_year"]):
            return None
        return next(
            item for item in parameters
            if year >= item.first_year and (item.last_year is None or year <= item.last_year)
        )

    start = 0
    while start < count:
        day = int(source["day"][start])
        end = start + 1
        while end < count and int(source["day"][end]) == day:
            end += 1
        year = int(source["year"][start])
        if year != current_year:
            first_training_year = year - window_years
            for state in states.values():
                state.trim_observations(first_training_year)
            current_year = year
            current_release = release_for_year(year)
            current_calibration = None if current_release is None else fit_calibration(
                list(states[current_release.name].observations), first_training_year, year - 1
            )

        while goal_window and goal_window[0][0] < year - environment_years:
            _, goals = goal_window.popleft()
            window_goals -= goals
        prior_goals = 2.0 * prior_matches * prior_per_team
        base_goal = float(np.clip(
            (prior_goals + window_goals) / (2.0 * prior_matches + 2.0 * len(goal_window)),
            0.55,
            2.50,
        ))

        lambdas = np.empty((end - start, len(parameters), 2), dtype=float)
        for row in range(start, end):
            first = int(source["first"][row])
            second = int(source["second"][row])
            for item in parameters:
                raw, lambda1, lambda2 = states[item.name].predict(first, second, day, expected[row], base_goal)
                index = state_index[item.name]
                all_raw[row, index] = raw
                lambdas[row - start, index] = (lambda1, lambda2)
            base_goals[row] = base_goal
            if current_release is None or current_calibration is None:
                calibrated[row] = network[row]
                ungated[row] = network[row]
                final[row] = network[row]
                continue
            releases[row] = current_release.name
            raw = all_raw[row, state_index[current_release.name]]
            score = calibrated_score_probabilities(
                raw,
                bool(source["friendly"][row]),
                current_calibration.draw_log_tilt,
                current_calibration.friendly_temperature,
                current_calibration.competitive_temperature,
            )
            calibrated[row] = score
            calibration_values[row] = (
                current_calibration.draw_log_tilt,
                current_calibration.friendly_temperature,
                current_calibration.competitive_temperature,
                current_calibration.nfelo_weight,
            )
            candidate = current_calibration.nfelo_weight * network[row] + (1.0 - current_calibration.nfelo_weight) * score
            candidate /= candidate.sum()
            ungated[row] = candidate
            final[row], reverted[row] = outcome_preserving_pool(network[row], score, current_calibration.nfelo_weight)

        # Only after every forecast on the date is frozen do results enter the
        # score state and the rolling goal environment.
        for row in range(start, end):
            first = int(source["first"][row])
            second = int(source["second"][row])
            outcome = int(source["outcome"][row])
            for item in parameters:
                index = state_index[item.name]
                raw = all_raw[row, index]
                states[item.name].observations.append(ForecastObservation(
                    year=year,
                    score_probabilities=tuple(float(value) for value in raw),
                    nfelo_probabilities=tuple(float(value) for value in network[row]),
                    outcome=outcome,
                    friendly=bool(source["friendly"][row]),
                ))
                states[item.name].update(
                    first,
                    second,
                    int(source["goals1"][row]),
                    int(source["goals2"][row]),
                    float(lambdas[row - start, index, 0]),
                    float(lambdas[row - start, index, 1]),
                )
            goals = int(source["goals1"][row]) + int(source["goals2"][row])
            goal_window.append((year, goals))
            window_goals += goals
        start = end

    values = {key: source[key] for key in source.files if key not in {
        "network", "score_raw", "score_calibrated", "ungated", "final", "calibration",
        "reverted", "release", "base_goal", "all_score_raw", "score_state_names", "expected_score",
    }}
    values.update({
        "network": network,
        "score_raw": np.asarray([
            all_raw[row, state_index[releases[row]]] if releases[row] else network[row]
            for row in range(count)
        ]),
        "score_calibrated": calibrated,
        "ungated": ungated,
        "final": final,
        "calibration": calibration_values,
        "reverted": reverted,
        "release": releases,
        "base_goal": base_goals,
        "all_score_raw": all_raw,
        "score_state_names": np.asarray(state_names),
        "expected_score": expected,
    })
    np.savez_compressed(args.output, **values)
    cutoff = (source["year"].astype(int) >= 1960) & (source["date"] <= "2026-07-11")
    print(json.dumps({
        "network": metrics(network[cutoff], source["outcome"][cutoff].astype(int)),
        "ungated": metrics(ungated[cutoff], source["outcome"][cutoff].astype(int)),
        "gated": metrics(final[cutoff], source["outcome"][cutoff].astype(int)),
        "reversions": int(reverted[cutoff].sum()),
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
