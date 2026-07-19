#!/usr/bin/env python3
"""Rolling-origin search over NFELO network hyperparameters and safe variants."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import numpy as np
from scipy.stats import qmc


FOLDS = (
    (1940, 1959, 1960, 1979),
    (1960, 1979, 1980, 1999),
    (1980, 1999, 2000, 2009),
    (2000, 2009, 2010, 2019),
    (2010, 2019, 2020, 2026),
)


@dataclass(frozen=True)
class Candidate:
    prior: float
    drift: float
    quality: float
    friendly_ratio: float = 1.0
    margin: str = "current"
    mode: str = "sequential"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--stage1", type=int, default=80)
    parser.add_argument("--local", type=int, default=32)
    return parser.parse_args()


def last_day(year: int) -> int:
    return 2026 * 400 + 7 * 32 + 11 if year == 2026 else year * 400 + 12 * 32 + 31


def command(args: argparse.Namespace, candidate: Candidate, fold: tuple[int, int, int, int]) -> list[str]:
    fit_first, fit_last, test_first, test_last = fold
    values = [
        str(args.executable), str(args.matches),
        "--prior", str(candidate.prior),
        "--drift", str(candidate.drift),
        "--quality", str(candidate.quality),
        "--friendly-ratio", str(candidate.friendly_ratio),
        "--margin", candidate.margin,
        "--fit-temperatures",
        "--fit-first-year", str(fit_first),
        "--fit-last-day", str(last_day(fit_last)),
        "--score-first-year", str(test_first),
        "--score-last-day", str(last_day(test_last)),
    ]
    if candidate.mode == "joint_debut":
        values.append("--joint-debut")
    elif candidate.mode == "batch_day":
        values.extend(("--batch-predict-day", "--day-debut", "--joint-debut"))
    elif candidate.mode != "sequential":
        raise ValueError(candidate.mode)
    return values


def evaluate(args: argparse.Namespace, candidate: Candidate, fold_index: int) -> dict[str, Any]:
    completed = subprocess.run(
        command(args, candidate, FOLDS[fold_index]),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    metrics = json.loads(completed.stdout)
    return {"fold": fold_index, "candidate": asdict(candidate), "metrics": metrics}


def run_tasks(
    args: argparse.Namespace, tasks: list[tuple[Candidate, int]], label: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(evaluate, args, candidate, fold): (candidate, fold) for candidate, fold in tasks}
        complete = 0
        for future in as_completed(futures):
            results.append(future.result())
            complete += 1
            if complete % 40 == 0 or complete == len(tasks):
                print(f"{label}: {complete}/{len(tasks)}", flush=True)
    return results


def stage_one_candidates(count: int) -> list[Candidate]:
    sampler = qmc.LatinHypercube(d=3, seed=20260719)
    sample = sampler.random(count)
    candidates = [
        Candidate(
            prior=float(math.exp(math.log(80.0) + row[0] * math.log(10.0))),
            drift=float(row[1] * 80.0),
            quality=float(math.exp(math.log(0.30) + row[2] * math.log(20.0))),
        )
        for row in sample
    ]
    candidates.extend(
        (
            Candidate(300.0, 19.750212594949737, 1.7440260583320362),
            Candidate(300.0, 0.0, 1.7440260583320362),
            Candidate(150.0, 20.0, 1.75),
            Candidate(600.0, 20.0, 1.75),
            Candidate(300.0, 50.0, 1.75),
        )
    )
    return candidates


def best_by_fit(results: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        fold: min((row for row in results if row["fold"] == fold), key=lambda row: row["metrics"]["fit_log_loss"])
        for fold in range(len(FOLDS))
    }


def aggregate(selected: dict[int, dict[str, Any]]) -> dict[str, float | int]:
    total = sum(row["metrics"]["matches"] for row in selected.values())
    result: dict[str, float | int] = {"matches": int(total)}
    for metric in ("log_loss", "brier", "rps", "accuracy"):
        result[metric] = float(sum(row["metrics"][metric] * row["metrics"]["matches"] for row in selected.values()) / total)
    return result


def main() -> None:
    args = parse_args()
    args.executable = args.executable.resolve()
    args.matches = args.matches.resolve()

    stage1_candidates = stage_one_candidates(args.stage1)
    stage1 = run_tasks(
        args,
        [(candidate, fold) for candidate in stage1_candidates for fold in range(len(FOLDS))],
        "continuous search",
    )
    stage1_best = best_by_fit(stage1)

    stage2_tasks: list[tuple[Candidate, int]] = []
    for fold, row in stage1_best.items():
        base = Candidate(**row["candidate"])
        for margin in ("current", "none", "log", "sqrt", "wfe"):
            for ratio in (0.60, 0.80, 1.00, 1.20, 1.40):
                for mode in ("sequential", "joint_debut", "batch_day"):
                    stage2_tasks.append((Candidate(base.prior, base.drift, base.quality, ratio, margin, mode), fold))
    stage2 = run_tasks(args, stage2_tasks, "structural search")
    stage2_best = best_by_fit(stage2)

    rng = np.random.default_rng(20260719)
    stage3_tasks: list[tuple[Candidate, int]] = []
    for fold, row in stage2_best.items():
        base = Candidate(**row["candidate"])
        stage3_tasks.append((base, fold))
        for _ in range(args.local):
            stage3_tasks.append((Candidate(
                prior=float(np.clip(base.prior * math.exp(rng.normal(0.0, 0.25)), 50.0, 1200.0)),
                drift=float(np.clip(base.drift * math.exp(rng.normal(0.0, 0.30)) if base.drift > 0 else rng.uniform(0, 10), 0.0, 120.0)),
                quality=float(np.clip(base.quality * math.exp(rng.normal(0.0, 0.25)), 0.15, 10.0)),
                friendly_ratio=float(np.clip(base.friendly_ratio + rng.normal(0.0, 0.12), 0.35, 1.75)),
                margin=base.margin,
                mode=base.mode,
            ), fold))
    stage3 = run_tasks(args, stage3_tasks, "local search")
    final_best = best_by_fit(stage2 + stage3)
    batch_best = best_by_fit([row for row in stage2 + stage3 if row["candidate"]["mode"] == "batch_day"])

    baseline_candidate = Candidate(300.0, 19.750212594949737, 1.7440260583320362)
    baseline_rows = run_tasks(args, [(baseline_candidate, fold) for fold in range(len(FOLDS))], "baseline")
    baseline = {row["fold"]: row for row in baseline_rows}

    # Also evaluate immutable family comparisons without selecting them on outer data.
    family_candidates = {
        "default_batch_day": Candidate(300.0, 19.750212594949737, 1.7440260583320362, mode="batch_day"),
        "no_margin": Candidate(300.0, 19.750212594949737, 1.7440260583320362, margin="none"),
        "wfe_margin": Candidate(300.0, 19.750212594949737, 1.7440260583320362, margin="wfe"),
        "friendly_0_8": Candidate(300.0, 19.750212594949737, 1.7440260583320362, friendly_ratio=0.8),
        "friendly_1_2": Candidate(300.0, 19.750212594949737, 1.7440260583320362, friendly_ratio=1.2),
    }
    family: dict[str, Any] = {}
    for name, candidate in family_candidates.items():
        rows = run_tasks(args, [(candidate, fold) for fold in range(len(FOLDS))], name)
        selected = {row["fold"]: row for row in rows}
        family[name] = {"aggregate": aggregate(selected), "folds": selected}

    payload = {
        "protocol": {
            "folds": FOLDS,
            "selection_metric": "inner-block log loss after fitting friendly/competitive temperatures on that inner block",
            "outer_blocks_are_untouched_for_selection": True,
            "continuous_stage_candidates": len(stage1_candidates),
            "warning": "Era curves are the deployed curves and were originally estimated through 2026; this search audits network structure but is not a fully refitted observation model.",
        },
        "baseline": {"aggregate": aggregate(baseline), "folds": baseline},
        "selected": {"aggregate": aggregate(final_best), "folds": final_best},
        "selected_batch_only": {"aggregate": aggregate(batch_best), "folds": batch_best},
        "families": family,
        "stage1_best": stage1_best,
        "stage2_best": stage2_best,
        "stage1_results": stage1,
        "stage2_results": stage2,
        "stage3_results": stage3,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "baseline": payload["baseline"]["aggregate"],
        "selected": payload["selected"]["aggregate"],
        "selected_batch_only": payload["selected_batch_only"]["aggregate"],
        "selected_candidates": {fold: row["candidate"] for fold, row in final_best.items()},
        "output": str(args.output),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
