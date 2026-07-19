#!/usr/bin/env python3
"""Capture the deployed replay's pre-match forecast components for audit work."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scripts = args.repo / "scripts"
    sys.path.insert(0, str(scripts))

    import forecast_layer as forecast_module
    import model as model_module

    class CapturingForecastLayer(forecast_module.ForecastLayer):
        def __init__(self, team_count: int, configuration: dict[str, object]) -> None:
            super().__init__(team_count, configuration)
            self.audit_rows: list[dict[str, object]] = []

        def predict_and_update(self, **kwargs: object) -> np.ndarray:
            year = int(kwargs["year"])
            if year != self.current_year:
                self._start_year(year)
            first = int(kwargs["first"])
            second = int(kwargs["second"])
            day = int(kwargs["day"])
            expected_score = float(kwargs["expected_score"])
            friendly = bool(kwargs["friendly"])
            network = np.asarray(kwargs["nfelo_probabilities"], dtype=np.float64)
            base_goal = self._base_goal(year)
            predictions = {
                name: state.predict(first, second, day, expected_score, base_goal)
                for name, state in self.states.items()
            }

            raw = np.full(3, np.nan, dtype=np.float64)
            active_lambda = (np.nan, np.nan)
            score = np.full(3, np.nan, dtype=np.float64)
            ungated = network.copy()
            calibration = (np.nan, np.nan, np.nan, 1.0)
            would_revert = False
            release = ""
            if self.current_release is not None and self.current_calibration is not None:
                release = self.current_release.name
                raw = predictions[release][0]
                active_lambda = (predictions[release][1], predictions[release][2])
                c = self.current_calibration
                score = forecast_module.calibrated_score_probabilities(
                    raw,
                    friendly,
                    c.draw_log_tilt,
                    c.friendly_temperature,
                    c.competitive_temperature,
                )
                ungated = c.nfelo_weight * network + (1.0 - c.nfelo_weight) * score
                ungated /= ungated.sum()
                would_revert = int(np.argmax(ungated)) != int(np.argmax(network))
                calibration = (
                    c.draw_log_tilt,
                    c.friendly_temperature,
                    c.competitive_temperature,
                    c.nfelo_weight,
                )

            self.audit_rows.append(
                {
                    "network": network.copy(),
                    "score_raw": raw.copy(),
                    "score_calibrated": score.copy(),
                    "ungated": ungated.copy(),
                    "calibration": calibration,
                    "revert": would_revert,
                    "release": release,
                    "base_goal": base_goal,
                    "score_lambda": active_lambda,
                    "all_score_raw": np.asarray(
                        [predictions[parameters.name][0] for parameters in self.parameters],
                        dtype=np.float64,
                    ),
                    "all_score_lambda": np.asarray(
                        [predictions[parameters.name][1:] for parameters in self.parameters],
                        dtype=np.float64,
                    ),
                }
            )
            return super().predict_and_update(**kwargs)

    model_module.ForecastLayer = CapturingForecastLayer
    started = time.perf_counter()
    replay = model_module.NetworkEloReplay(args.repo / "source", args.repo / "config")
    output = replay.replay()
    elapsed = time.perf_counter() - started
    captures = replay.forecast_layer.audit_rows
    if len(captures) != len(output.matches):
        raise RuntimeError(f"capture mismatch: {len(captures)} vs {len(output.matches)}")

    outcomes = np.asarray(
        [0 if row["sa"] > row["sb"] else 1 if row["sa"] == row["sb"] else 2 for row in output.matches],
        dtype=np.int8,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        day=np.asarray([match.day for match in replay.matches], dtype=np.int32),
        year=np.asarray([row["year"] for row in output.matches], dtype=np.int16),
        date=np.asarray([row["date"] for row in output.matches]),
        first=np.asarray([replay.team_index[match.team1] for match in replay.matches], dtype=np.int16),
        second=np.asarray([replay.team_index[match.team2] for match in replay.matches], dtype=np.int16),
        goals1=np.asarray([row["sa"] for row in output.matches], dtype=np.int16),
        goals2=np.asarray([row["sb"] for row in output.matches], dtype=np.int16),
        home=np.asarray([row["home"] for row in output.matches], dtype=np.int8),
        friendly=np.asarray([row["level"] == 0 for row in output.matches], dtype=bool),
        outcome=outcomes,
        network=np.asarray([row["network"] for row in captures], dtype=np.float64),
        score_raw=np.asarray([row["score_raw"] for row in captures], dtype=np.float64),
        score_calibrated=np.asarray([row["score_calibrated"] for row in captures], dtype=np.float64),
        ungated=np.asarray([row["ungated"] for row in captures], dtype=np.float64),
        final=np.asarray([row["p"] for row in output.matches], dtype=np.float64),
        calibration=np.asarray([row["calibration"] for row in captures], dtype=np.float64),
        reverted=np.asarray([row["revert"] for row in captures], dtype=bool),
        release=np.asarray([row["release"] for row in captures]),
        base_goal=np.asarray([row["base_goal"] for row in captures], dtype=np.float64),
        score_lambda=np.asarray([row["score_lambda"] for row in captures], dtype=np.float64),
        all_score_raw=np.asarray([row["all_score_raw"] for row in captures], dtype=np.float64),
        all_score_lambda=np.asarray([row["all_score_lambda"] for row in captures], dtype=np.float64),
        score_state_names=np.asarray([parameters.name for parameters in replay.forecast_layer.parameters]),
        expected_score=np.asarray([row["expected"] for row in output.matches], dtype=np.float64),
        pre_rating1=np.asarray(
            [np.nan if row["pre_a"] is None else row["pre_a"] for row in output.matches],
            dtype=np.float64,
        ),
        pre_rating2=np.asarray(
            [np.nan if row["pre_b"] is None else row["pre_b"] for row in output.matches],
            dtype=np.float64,
        ),
        official_pre1=np.asarray([match.official_pre1 for match in replay.matches], dtype=np.int16),
        official_pre2=np.asarray([match.official_pre2 for match in replay.matches], dtype=np.int16),
        teams=np.asarray(replay.teams),
    )
    print(f"captured={len(captures)} elapsed_seconds={elapsed:.3f} output={args.output}")


if __name__ == "__main__":
    main()
