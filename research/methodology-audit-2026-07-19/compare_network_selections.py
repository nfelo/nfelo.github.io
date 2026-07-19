#!/usr/bin/env python3
"""Materialise rolling selected forecasts and paired year-cluster comparisons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd


FOLDS = (
    (1940, 1959, 1960, 1979),
    (1960, 1979, 1980, 1999),
    (1980, 1999, 2000, 2009),
    (2000, 2009, 2010, 2019),
    (2010, 2019, 2020, 2026),
)
EPS = 1e-15


def end_day(year: int) -> int:
    return 2026 * 400 + 7 * 32 + 11 if year == 2026 else year * 400 + 12 * 32 + 31


def metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float | int]:
    one = np.eye(3)[outcomes]
    cumulative = np.cumsum(probabilities, axis=1)[:, :2] - np.cumsum(one, axis=1)[:, :2]
    return {
        "matches": int(len(outcomes)),
        "log_loss": float(-np.log(np.maximum(probabilities[np.arange(len(outcomes)), outcomes], EPS)).mean()),
        "brier": float(np.square(probabilities - one).sum(axis=1).mean()),
        "rps": float(0.5 * np.square(cumulative).sum(axis=1).mean()),
        "accuracy": float((probabilities.argmax(axis=1) == outcomes).mean()),
    }


def transform(probabilities: np.ndarray, friendly: np.ndarray, friendly_t: float, competitive_t: float) -> np.ndarray:
    powers = np.where(friendly, friendly_t, competitive_t)
    values = np.power(np.maximum(probabilities, EPS), powers[:, None])
    return values / values.sum(axis=1, keepdims=True)


def command(
    executable: Path,
    matches: Path,
    candidate: dict[str, object],
    fold: tuple[int, int, int, int],
    output: Path,
) -> list[str]:
    fit_first, fit_last, test_first, test_last = fold
    values = [
        str(executable), str(matches),
        "--prior", str(candidate["prior"]), "--drift", str(candidate["drift"]),
        "--quality", str(candidate["quality"]),
        "--friendly-ratio", str(candidate.get("friendly_ratio", 1.0)),
        "--margin", str(candidate.get("margin", "current")),
        "--fit-temperatures", "--fit-first-year", str(fit_first),
        "--fit-last-day", str(end_day(fit_last)), "--score-first-year", str(test_first),
        "--score-last-day", str(end_day(test_last)), "--output", str(output),
    ]
    if "scale" in candidate:
        values.extend((
            "--constant-scale", str(candidate["scale"]),
            "--constant-home", str(candidate["home"]),
            "--constant-draw", str(candidate["draw"]),
        ))
    mode = str(candidate.get("mode", "sequential"))
    if mode == "batch_day":
        values.extend(("--batch-predict-day", "--day-debut", "--joint-debut"))
    elif mode == "simultaneous_day":
        values.extend(("--simultaneous-day-update", "--day-debut", "--joint-debut"))
    elif mode == "joint_debut":
        values.append("--joint-debut")
    elif mode != "sequential":
        raise ValueError(mode)
    return values


def materialise(
    executable: Path,
    matches_path: Path,
    candidates: dict[int, dict[str, object]],
    days: np.ndarray,
    years: np.ndarray,
    friendly: np.ndarray,
) -> np.ndarray:
    result = np.full((len(years), 3), np.nan, dtype=float)
    with TemporaryDirectory(prefix="nfelo-selection-") as directory:
        for fold_index, fold in enumerate(FOLDS):
            output = Path(directory) / f"fold-{fold_index}.tsv"
            completed = subprocess.run(
                command(executable, matches_path, candidates[fold_index], fold, output),
                check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            evaluation = json.loads(completed.stdout)
            frame = pd.read_csv(output, sep="\t")
            raw = frame[["pw", "pd", "pl"]].to_numpy(float)
            transformed = transform(
                raw, friendly,
                float(evaluation["friendly_temperature"]),
                float(evaluation["competitive_temperature"]),
            )
            _, _, test_first, test_last = fold
            selected = (years >= test_first) & (days <= end_day(test_last))
            result[selected] = transformed[selected]
    return result


def bootstrap(
    candidate: np.ndarray,
    reference: np.ndarray,
    outcomes: np.ndarray,
    years: np.ndarray,
    draws: int = 20_000,
) -> dict[str, float | int]:
    difference = -np.log(np.maximum(candidate[np.arange(len(outcomes)), outcomes], EPS)) + np.log(
        np.maximum(reference[np.arange(len(outcomes)), outcomes], EPS)
    )
    unique = np.unique(years)
    sums = np.asarray([difference[years == year].sum() for year in unique])
    counts = np.asarray([(years == year).sum() for year in unique])
    rng = np.random.default_rng(20260719)
    selected = rng.integers(0, len(unique), size=(draws, len(unique)))
    sampled = sums[selected].sum(axis=1) / counts[selected].sum(axis=1)
    return {
        "candidate_minus_reference": float(difference.mean()),
        "ci95_lower": float(np.quantile(sampled, 0.025)),
        "ci95_upper": float(np.quantile(sampled, 0.975)),
        "probability_candidate_better": float((sampled < 0).mean()),
        "draws": draws,
        "note": "Conditional on the selected models; fitting and search are not repeated inside bootstrap draws.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--selected-key", default="selected")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.search.read_text(encoding="utf-8"))
    matches = pd.read_csv(
        args.matches, sep="\t", comment="#", header=None,
        names=("id", "day", "year", "month", "dom", "a", "b", "ga", "gb", "home", "friendly", "level", "official_a", "official_b"),
    )
    days = matches.day.to_numpy(int)
    years = matches.year.to_numpy(int)
    friendly = matches.friendly.to_numpy(bool)
    outcomes = np.where(matches.ga > matches.gb, 0, np.where(matches.ga == matches.gb, 1, 2)).astype(int)
    cutoff = (years >= 1960) & (days <= end_day(2026))
    selected = {
        int(fold): row["candidate"]
        for fold, row in payload[args.selected_key]["folds"].items()
    }
    if "baseline" in payload:
        reference = {int(fold): row["candidate"] for fold, row in payload["baseline"]["folds"].items()}
        reference_name = "deployed_structure_rolling_temperatures"
    else:
        reference = {
            fold: {
                "prior": 300.0, "drift": 20.0, "quality": 1.75,
                "scale": 1.0, "home": 85.0, "draw": 0.30,
                "friendly_ratio": 1.0, "margin": "current", "mode": "batch_day",
            }
            for fold in range(len(FOLDS))
        }
        reference_name = "fixed_constant_observation_reference"
    selected_prediction = materialise(
        args.executable.resolve(), args.matches.resolve(), selected, days, years, friendly
    )
    reference_prediction = materialise(
        args.executable.resolve(), args.matches.resolve(), reference, days, years, friendly
    )
    if not np.all(np.isfinite(selected_prediction[cutoff])) or not np.all(np.isfinite(reference_prediction[cutoff])):
        raise RuntimeError("incomplete prediction materialisation")
    result = {
        "selected_key": args.selected_key,
        "selected": metrics(selected_prediction[cutoff], outcomes[cutoff]),
        "reference_name": reference_name,
        "reference": metrics(reference_prediction[cutoff], outcomes[cutoff]),
        "comparison": bootstrap(
            selected_prediction[cutoff], reference_prediction[cutoff], outcomes[cutoff], years[cutoff]
        ),
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
