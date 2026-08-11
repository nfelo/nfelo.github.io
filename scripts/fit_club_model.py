#!/usr/bin/env python3
"""Reproducible chronological bake-off for the frozen club coefficients."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from club_model import load_club_config, run_club_model


GRID: tuple[tuple[str, tuple[float, ...], str], ...] = (
    ("draw_peak", (0.285, 0.300, 0.315), "all"),
    ("home_advantage_domestic", (25.0, 35.0, 45.0, 55.0), "all"),
    ("home_advantage_cross_border", (65.0, 80.0, 95.0, 110.0, 125.0), "all"),
    ("k_factor", (16.0, 18.0, 20.0), "all"),
    ("margin_scale", (0.60, 0.75, 0.90), "all"),
    ("season_retention", (0.70, 0.77, 0.84, 0.89), "all"),
    ("association_share", (0.30, 0.40, 0.50, 0.60, 0.70), "all"),
    ("tier_gap", (55.0, 65.0, 75.0), "all"),
    ("aggregate_floor", (0.10, 0.25, 0.40, 0.60, 1.00), "post_controlled_tie"),
    ("aggregate_scale", (0.60, 1.00, 1.45, 2.00), "post_controlled_tie"),
)


def evaluate(payload: tuple[str, dict[str, Any], str, str, str]) -> tuple[str, dict[str, Any]]:
    database, config, replay_from, first, last = payload
    result = run_club_model(
        Path(database), config, write_tables=False, replay_from=replay_from,
        evaluation_start=first, evaluation_end=last,
    )
    return json.dumps(config, sort_keys=True), result


def fit(
    database: Path,
    initial: dict[str, Any],
    *,
    workers: int,
    replay_from: str,
    validation_start: str,
    validation_end: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected = deepcopy(initial)
    audit: list[dict[str, Any]] = []
    for parameter, values, metric_bucket in GRID:
        candidates = []
        for value in values:
            candidate = deepcopy(selected)
            candidate[parameter] = value
            candidates.append(candidate)
        results: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    evaluate,
                    (
                        str(database), candidate, replay_from,
                        validation_start, validation_end,
                    ),
                ): candidate
                for candidate in candidates
            }
            for future in as_completed(futures):
                candidate = futures[future]
                _, result = future.result()
                score = result["metrics"][metric_bucket]["log_loss"]
                if score is None:
                    raise RuntimeError(f"No {metric_bucket} validation matches for {parameter}")
                results.append((float(score), candidate, result))
                print(
                    json.dumps(
                        {
                            "parameter": parameter,
                            "value": candidate[parameter],
                            "bucket": metric_bucket,
                            "log_loss": score,
                            "matches": result["metrics"][metric_bucket]["matches"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        results.sort(key=lambda item: (item[0], float(item[1][parameter])))
        best_score, selected, best_result = results[0]
        audit.append(
            {
                "parameter": parameter,
                "selected": selected[parameter],
                "bucket": metric_bucket,
                "log_loss": best_score,
                "candidates": [
                    {"value": item[1][parameter], "log_loss": item[0]}
                    for item in sorted(results, key=lambda item: float(item[1][parameter]))
                ],
            }
        )
        print(
            f"selected {parameter}={selected[parameter]} "
            f"({metric_bucket} log loss {best_score:.9f})",
            flush=True,
        )
    return selected, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path(".club-cache/club-ledger.duckdb"))
    parser.add_argument("--config", type=Path, default=Path("config/club_model.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--replay-from", default="2000-01-01")
    parser.add_argument("--validation-start", default="2018-01-01")
    parser.add_argument("--validation-end", default="2022-12-31")
    parser.add_argument("--test-start", default="2023-01-01")
    parser.add_argument("--test-end", default="2026-12-31")
    args = parser.parse_args()
    initial = load_club_config(args.config)
    selected, grid_audit = fit(
        args.database, initial, workers=max(1, args.workers),
        replay_from=args.replay_from, validation_start=args.validation_start,
        validation_end=args.validation_end,
    )
    selected_validation = run_club_model(
        args.database, selected, write_tables=False, replay_from=args.replay_from,
        evaluation_start=args.validation_start, evaluation_end=args.validation_end,
    )
    selected_test = run_club_model(
        args.database, selected, write_tables=False, replay_from=args.replay_from,
        evaluation_start=args.test_start, evaluation_end=args.test_end,
    )
    ordinary_test_config = deepcopy(selected)
    ordinary_test_config["aggregate_floor"] = 1.0
    ordinary_test_config["aggregate_scale"] = 1.0
    ordinary_validation = run_club_model(
        args.database, ordinary_test_config, write_tables=False,
        replay_from=args.replay_from, evaluation_start=args.validation_start,
        evaluation_end=args.validation_end,
    )
    ordinary_test = run_club_model(
        args.database, ordinary_test_config, write_tables=False,
        replay_from=args.replay_from, evaluation_start=args.test_start,
        evaluation_end=args.test_end,
    )
    report = {
        "protocol": {
            "replay_from": args.replay_from,
            "validation": [args.validation_start, args.validation_end],
            "test": [args.test_start, args.test_end],
            "selection": "one-pass chronological coordinate grid; log loss",
            "aggregate_selection_bucket": "matches within 120 days after a controlled-loss second leg",
        },
        "selected": {
            key: selected[key]
            for key, _, _ in GRID
        },
        "grid": grid_audit,
        "validation": selected_validation["metrics"],
        "test": selected_test["metrics"],
        "ordinary_leg_validation": ordinary_validation["metrics"],
        "ordinary_leg_test": ordinary_test["metrics"],
    }
    print("CLUB_FIT_RESULT=" + json.dumps(report, sort_keys=True), flush=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
