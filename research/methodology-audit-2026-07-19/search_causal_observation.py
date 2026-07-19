#!/usr/bin/env python3
"""Rolling search with no era parameter estimated from a future match."""

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
    scale: float
    home: float
    draw: float
    friendly_ratio: float = 1.0
    margin: str = "current"
    mode: str = "batch_day"


def end_day(year: int) -> int:
    return 2026 * 400 + 7 * 32 + 11 if year == 2026 else year * 400 + 12 * 32 + 31


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--candidates", type=int, default=120)
    parser.add_argument("--local", type=int, default=40)
    return parser.parse_args()


def command(args: argparse.Namespace, candidate: Candidate, fold: int) -> list[str]:
    fit_first, fit_last, test_first, test_last = FOLDS[fold]
    values = [
        str(args.executable.resolve()), str(args.matches.resolve()),
        "--prior", str(candidate.prior), "--drift", str(candidate.drift),
        "--quality", str(candidate.quality), "--friendly-ratio", str(candidate.friendly_ratio),
        "--margin", candidate.margin,
        "--constant-scale", str(candidate.scale), "--constant-home", str(candidate.home),
        "--constant-draw", str(candidate.draw),
        "--fit-temperatures", "--fit-first-year", str(fit_first), "--fit-last-day", str(end_day(fit_last)),
        "--score-first-year", str(test_first), "--score-last-day", str(end_day(test_last)),
    ]
    if candidate.mode == "batch_day": values.extend(("--batch-predict-day", "--day-debut", "--joint-debut"))
    elif candidate.mode == "joint_debut": values.append("--joint-debut")
    elif candidate.mode != "sequential": raise ValueError(candidate.mode)
    return values


def evaluate(args: argparse.Namespace, candidate: Candidate, fold: int) -> dict[str, Any]:
    completed = subprocess.run(command(args, candidate, fold), check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"fold": fold, "candidate": asdict(candidate), "metrics": json.loads(completed.stdout)}


def run(args: argparse.Namespace, tasks: list[tuple[Candidate, int]], label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(evaluate, args, candidate, fold) for candidate, fold in tasks]
        for index, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if index % 40 == 0 or index == len(tasks): print(f"{label}: {index}/{len(tasks)}", flush=True)
    return rows


def best(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {fold: min((row for row in rows if row["fold"] == fold), key=lambda row: row["metrics"]["fit_log_loss"])
            for fold in range(len(FOLDS))}


def aggregate(rows: dict[int, dict[str, Any]]) -> dict[str, float | int]:
    count = sum(row["metrics"]["matches"] for row in rows.values())
    result: dict[str, float | int] = {"matches": int(count)}
    for key in ("log_loss", "brier", "rps", "accuracy"):
        result[key] = float(sum(row["metrics"][key] * row["metrics"]["matches"] for row in rows.values()) / count)
    return result


def initial_candidates(count: int) -> list[Candidate]:
    sample = qmc.LatinHypercube(d=6, seed=20260719).random(count)
    rows = []
    for value in sample:
        rows.append(Candidate(
            prior=float(math.exp(math.log(75.0) + value[0] * math.log(12.0))),
            drift=float(value[1] * 90.0),
            quality=float(math.exp(math.log(0.25) + value[2] * math.log(28.0))),
            scale=float(0.65 + value[3] * 1.10),
            home=float(35.0 + value[4] * 125.0),
            draw=float(0.16 + value[5] * 0.24),
        ))
    rows.extend((
        Candidate(300.0, 20.0, 1.75, 1.0, 85.0, 0.30),
        Candidate(300.0, 20.0, 1.75, 1.2, 100.0, 0.28),
        Candidate(200.0, 10.0, 1.0, 1.0, 100.0, 0.30),
    ))
    return rows


def main() -> None:
    args = parse_args()
    stage1_candidates = initial_candidates(args.candidates)
    stage1 = run(args, [(candidate, fold) for candidate in stage1_candidates for fold in range(5)], "causal continuous")
    stage1_best = best(stage1)

    stage2_tasks: list[tuple[Candidate, int]] = []
    for fold, row in stage1_best.items():
        base = Candidate(**row["candidate"])
        for margin in ("current", "none", "log", "sqrt", "wfe"):
            for ratio in (0.60, 0.80, 1.00, 1.20, 1.40):
                for mode in ("batch_day", "sequential", "joint_debut"):
                    stage2_tasks.append((Candidate(base.prior, base.drift, base.quality, base.scale, base.home, base.draw,
                                                     ratio, margin, mode), fold))
    stage2 = run(args, stage2_tasks, "causal structure")
    stage2_best = best(stage2)
    stage2_batch_best = best([row for row in stage2 if row["candidate"]["mode"] == "batch_day"])

    local_tasks: list[tuple[Candidate, int]] = []
    for fold in range(len(FOLDS)):
        bases = [Candidate(**stage2_best[fold]["candidate"]), Candidate(**stage2_batch_best[fold]["candidate"])]
        # Refine the strict same-day batch model independently even when the
        # unrestricted inner-block winner is sequential.
        for base_index, base in enumerate(dict.fromkeys(bases)):
            local_tasks.append((base, fold))
            local_rng = np.random.default_rng(20260719 + 1000 * fold + 100 * base_index)
            for _ in range(args.local):
                local_tasks.append((Candidate(
                    prior=float(np.clip(base.prior * math.exp(local_rng.normal(0, 0.22)), 40, 1400)),
                    drift=float(np.clip(base.drift * math.exp(local_rng.normal(0, 0.25)) if base.drift else local_rng.uniform(0, 12), 0, 140)),
                    quality=float(np.clip(base.quality * math.exp(local_rng.normal(0, 0.22)), 0.10, 12)),
                    scale=float(np.clip(base.scale + local_rng.normal(0, 0.10), 0.45, 2.0)),
                    home=float(np.clip(base.home + local_rng.normal(0, 10), 10, 190)),
                    draw=float(np.clip(base.draw + local_rng.normal(0, 0.025), 0.10, 0.46)),
                    friendly_ratio=float(np.clip(base.friendly_ratio + local_rng.normal(0, 0.10), 0.30, 1.8)),
                    margin=base.margin, mode=base.mode,
                ), fold))
    stage3 = run(args, local_tasks, "causal local")
    selected = best(stage2 + stage3)
    selected_batch = best([row for row in stage1 + stage2 + stage3 if row["candidate"]["mode"] == "batch_day"])

    payload = {
        "protocol": {
            "folds": FOLDS,
            "description": "Every constant, temperature, and structural choice is selected on the immediately preceding block; same-day forecasts are batched when that mode is selected.",
            "future_fitted_era_curves_used": False,
        },
        "selected": {"aggregate": aggregate(selected), "folds": selected},
        "selected_batch_only": {"aggregate": aggregate(selected_batch), "folds": selected_batch},
        "stage1_best": stage1_best,
        "stage2_best": stage2_best,
        "stage1_results": stage1,
        "stage2_results": stage2,
        "stage3_results": stage3,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "aggregate": payload["selected"]["aggregate"],
        "batch_only_aggregate": payload["selected_batch_only"]["aggregate"],
        "selected_candidates": {fold: row["candidate"] for fold, row in selected.items()},
        "output": str(args.output),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
