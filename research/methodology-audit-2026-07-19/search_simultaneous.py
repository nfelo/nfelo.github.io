#!/usr/bin/env python3
"""Targeted rolling search for the result-order-invariant same-date update."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import subprocess

import numpy as np


FOLDS = (
    (1940, 1959, 1960, 1979),
    (1960, 1979, 1980, 1999),
    (1980, 1999, 2000, 2009),
    (2000, 2009, 2010, 2019),
    (2010, 2019, 2020, 2026),
)


def end_day(year: int) -> int:
    return 2026 * 400 + 7 * 32 + 11 if year == 2026 else year * 400 + 12 * 32 + 31


def command(executable: Path, matches: Path, candidate: dict[str, object], fold: int) -> list[str]:
    fit_first, fit_last, test_first, test_last = FOLDS[fold]
    values = [
        str(executable), str(matches),
        "--prior", str(candidate["prior"]), "--drift", str(candidate["drift"]),
        "--quality", str(candidate["quality"]),
        "--friendly-ratio", str(candidate.get("friendly_ratio", 1.0)),
        "--margin", str(candidate.get("margin", "current")),
        "--simultaneous-day-update", "--day-debut", "--joint-debut",
        "--fit-temperatures", "--fit-first-year", str(fit_first),
        "--fit-last-day", str(end_day(fit_last)), "--score-first-year", str(test_first),
        "--score-last-day", str(end_day(test_last)),
    ]
    if "scale" in candidate:
        values.extend((
            "--constant-scale", str(candidate["scale"]),
            "--constant-home", str(candidate["home"]),
            "--constant-draw", str(candidate["draw"]),
        ))
    return values


def evaluate(executable: Path, matches: Path, candidate: dict[str, object], fold: int) -> dict[str, object]:
    completed = subprocess.run(
        command(executable, matches, candidate, fold), check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return {"fold": fold, "candidate": candidate, "metrics": json.loads(completed.stdout)}


def run(
    executable: Path,
    matches: Path,
    tasks: list[tuple[dict[str, object], int]],
    workers: int,
    label: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(evaluate, executable, matches, candidate, fold) for candidate, fold in tasks]
        for index, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if index % 40 == 0 or index == len(tasks):
                print(f"{label}: {index}/{len(tasks)}", flush=True)
    return rows


def best(rows: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    return {
        fold: min((row for row in rows if row["fold"] == fold), key=lambda row: row["metrics"]["fit_log_loss"])
        for fold in range(len(FOLDS))
    }


def aggregate(rows: dict[int, dict[str, object]]) -> dict[str, float | int]:
    count = sum(int(row["metrics"]["matches"]) for row in rows.values())
    result: dict[str, float | int] = {"matches": count}
    for key in ("log_loss", "brier", "rps", "accuracy"):
        result[key] = float(sum(
            float(row["metrics"][key]) * int(row["metrics"]["matches"])
            for row in rows.values()
        ) / count)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--local", type=int, default=24)
    args = parser.parse_args()
    prior = json.loads(args.search.read_text(encoding="utf-8"))
    bases = {int(fold): dict(row["candidate"]) for fold, row in prior["stage1_best"].items()}
    stage1_tasks: list[tuple[dict[str, object], int]] = []
    for fold, base in bases.items():
        for margin in ("current", "none", "log", "sqrt", "wfe"):
            for ratio in (0.60, 0.80, 1.00, 1.20, 1.40):
                candidate = dict(base)
                candidate.update({"friendly_ratio": ratio, "margin": margin, "mode": "simultaneous_day"})
                stage1_tasks.append((candidate, fold))
    stage1 = run(args.executable.resolve(), args.matches.resolve(), stage1_tasks, args.workers, "simultaneous structure")
    stage1_best = best(stage1)

    local_tasks: list[tuple[dict[str, object], int]] = []
    for fold, row in stage1_best.items():
        base = dict(row["candidate"])
        local_tasks.append((base, fold))
        rng = np.random.default_rng(20260719 + fold * 1000)
        for _ in range(args.local):
            candidate = dict(base)
            candidate.update({
                "prior": float(np.clip(float(base["prior"]) * math.exp(rng.normal(0, 0.22)), 40, 1400)),
                "drift": float(np.clip(float(base["drift"]) * math.exp(rng.normal(0, 0.25)) if float(base["drift"]) else rng.uniform(0, 12), 0, 140)),
                "quality": float(np.clip(float(base["quality"]) * math.exp(rng.normal(0, 0.22)), 0.10, 12)),
                "friendly_ratio": float(np.clip(float(base["friendly_ratio"]) + rng.normal(0, 0.10), 0.30, 1.8)),
            })
            if "scale" in base:
                candidate.update({
                    "scale": float(np.clip(float(base["scale"]) + rng.normal(0, 0.10), 0.45, 2.0)),
                    "home": float(np.clip(float(base["home"]) + rng.normal(0, 10), 10, 190)),
                    "draw": float(np.clip(float(base["draw"]) + rng.normal(0, 0.025), 0.10, 0.46)),
                })
            local_tasks.append((candidate, fold))
    local = run(args.executable.resolve(), args.matches.resolve(), local_tasks, args.workers, "simultaneous local")
    selected = best(stage1 + local)
    payload = {
        "protocol": {
            "source_search": str(args.search),
            "selection_metric": "inner-block log loss",
            "same_date_forecasts_and_state_update_are_order_invariant": True,
        },
        "selected": {"aggregate": aggregate(selected), "folds": selected},
        "stage1_best": stage1_best,
        "stage1_results": stage1,
        "local_results": local,
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "aggregate": payload["selected"]["aggregate"],
        "candidates": {fold: row["candidate"] for fold, row in selected.items()},
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
