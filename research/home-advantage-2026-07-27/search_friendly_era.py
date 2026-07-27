#!/usr/bin/env python3
"""Test whether NFELO's friendly information ratio should vary by era.

Candidate curves are screened on 2010-2019 after their probability
temperatures have been fitted only through 2009.  One winner from each
predeclared family is then refitted through 2019 and evaluated on the untouched
2020-2026 block.  The deployed constant is always included as the reference.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Iterable

import numpy as np


BASELINE_RATIO = 0.78621
LOWER_RATIO = 0.20
UPPER_RATIO = 1.40
TRAIN_FIRST_YEAR = 1960
SELECTION_FIT_LAST_YEAR = 2009
SELECTION_FIRST_YEAR = 2010
SELECTION_LAST_YEAR = 2019
CONFIRMATION_FIT_LAST_YEAR = 2019
CONFIRMATION_FIRST_YEAR = 2020
CONFIRMATION_LAST_DAY = 2026 * 400 + 7 * 32 + 11


@dataclass(frozen=True, slots=True)
class Candidate:
    family: str
    years: tuple[int, ...]
    values: tuple[float, ...]
    step: bool
    parameter_count: int

    @property
    def key(self) -> str:
        values = ",".join(f"{value:.9f}" for value in self.values)
        years = ",".join(str(year) for year in self.years)
        mode = "step" if self.step else "smooth"
        return f"{self.family}|{mode}|{years}|{values}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    return parser.parse_args()


def last_day(year: int) -> int:
    return year * 400 + 12 * 32 + 31


def log_uniform(
    rng: np.random.Generator,
    rows: int,
    columns: int,
) -> np.ndarray:
    return np.exp(
        rng.uniform(
            math.log(LOWER_RATIO),
            math.log(UPPER_RATIO),
            size=(rows, columns),
        )
    )


def rounded(values: Iterable[float]) -> tuple[float, ...]:
    return tuple(round(float(value), 9) for value in values)


def candidates() -> list[Candidate]:
    rng = np.random.default_rng(20260727)
    result: list[Candidate] = [
        Candidate("constant", (1900, 2020), (BASELINE_RATIO,) * 2, False, 1)
    ]

    for value in np.linspace(LOWER_RATIO, UPPER_RATIO, 49):
        result.append(
            Candidate("constant", (1900, 2020), (float(value),) * 2, False, 1)
        )

    # A monotone or reversing long-run trend with log-linear interpolation.
    for values in log_uniform(rng, 192, 2):
        result.append(
            Candidate("smooth_linear_trend", (1900, 2020), rounded(values), False, 2)
        )

    # A single discrete change.  The dates include historical changes in the
    # volume and status of international friendlies, but are not fitted to the
    # outcome data.
    for split in (1930, 1946, 1960, 1970, 1980, 1990, 2000, 2010):
        for values in log_uniform(rng, 64, 2):
            result.append(
                Candidate(
                    f"two_era_step_{split}",
                    (1872, split),
                    rounded(values),
                    True,
                    2,
                )
            )

    # Three broad eras, in both step and smooth forms.
    knot_sets = (
        (1930, 1960),
        (1946, 1980),
        (1960, 1990),
        (1970, 2000),
        (1980, 2010),
    )
    for first, second in knot_sets:
        for values in log_uniform(rng, 64, 3):
            result.append(
                Candidate(
                    f"three_era_step_{first}_{second}",
                    (1872, first, second),
                    rounded(values),
                    True,
                    3,
                )
            )
        for values in log_uniform(rng, 64, 3):
            result.append(
                Candidate(
                    f"three_knot_smooth_{first}_{second}",
                    (first, second, 2020),
                    rounded(values),
                    False,
                    3,
                )
            )

    # The same five knot dates used by the observation model.  Random-walk
    # candidates favour smooth local movement and are accompanied by a smaller
    # unstructured sample, so an implausibly jagged optimum can be diagnosed.
    for _ in range(192):
        start = rng.uniform(math.log(0.45), math.log(1.10))
        increments = rng.normal(0.0, 0.22, size=4)
        logs = np.concatenate(([start], start + np.cumsum(increments)))
        values = np.clip(np.exp(logs), LOWER_RATIO, UPPER_RATIO)
        result.append(
            Candidate(
                "five_knot_smooth_random_walk",
                (1900, 1930, 1960, 1990, 2020),
                rounded(values),
                False,
                5,
            )
        )
    for values in log_uniform(rng, 64, 5):
        result.append(
            Candidate(
                "five_knot_smooth_unstructured",
                (1900, 1930, 1960, 1990, 2020),
                rounded(values),
                False,
                5,
            )
        )

    # De-duplicate the baseline and any coincident grid points.
    unique: dict[str, Candidate] = {}
    for candidate in result:
        unique[candidate.key] = candidate
    return list(unique.values())


def command(
    args: argparse.Namespace,
    candidate: Candidate,
    fit_last_year: int,
    score_first_year: int,
    score_last_day: int,
) -> list[str]:
    values = [
        str(args.executable),
        str(args.matches),
        "--prior",
        "300",
        "--drift",
        "19.750212594949737",
        "--quality",
        "1.7440260583320362",
        "--friendly-ratio-years",
        ",".join(str(year) for year in candidate.years),
        "--friendly-ratio-values",
        ",".join(f"{value:.9f}" for value in candidate.values),
        "--simultaneous-day-update",
        "--day-debut",
        "--joint-debut",
        "--fit-temperatures",
        "--fit-first-year",
        str(TRAIN_FIRST_YEAR),
        "--fit-last-day",
        str(last_day(fit_last_year)),
        "--score-first-year",
        str(score_first_year),
        "--score-last-day",
        str(score_last_day),
    ]
    if candidate.step:
        values.append("--friendly-ratio-step")
    return values


def evaluate(
    args: argparse.Namespace,
    candidate: Candidate,
    fit_last_year: int,
    score_first_year: int,
    score_last_day: int,
) -> dict[str, object]:
    completed = subprocess.run(
        command(
            args,
            candidate,
            fit_last_year,
            score_first_year,
            score_last_day,
        ),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "candidate": asdict(candidate),
        "key": candidate.key,
        "metrics": json.loads(completed.stdout),
    }


def parallel_evaluate(
    args: argparse.Namespace,
    values: list[Candidate],
    *,
    fit_last_year: int,
    score_first_year: int,
    score_last_day: int,
    label: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                evaluate,
                args,
                candidate,
                fit_last_year,
                score_first_year,
                score_last_day,
            ): candidate
            for candidate in values
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if completed % 100 == 0 or completed == len(futures):
                print(f"{label}: {completed}/{len(futures)}", flush=True)
    return rows


def family_name(row: dict[str, object]) -> str:
    candidate = row["candidate"]
    assert isinstance(candidate, dict)
    family = str(candidate["family"])
    if family.startswith("two_era_step_"):
        return "two_era_step"
    if family.startswith("three_era_step_"):
        return "three_era_step"
    if family.startswith("three_knot_smooth_"):
        return "three_knot_smooth"
    return family


def main() -> None:
    args = parse_args()
    args.executable = args.executable.resolve()
    args.matches = args.matches.resolve()
    values = candidates()
    screening = parallel_evaluate(
        args,
        values,
        fit_last_year=SELECTION_FIT_LAST_YEAR,
        score_first_year=SELECTION_FIRST_YEAR,
        score_last_day=last_day(SELECTION_LAST_YEAR),
        label="2010-2019 selection",
    )
    groups: dict[str, list[dict[str, object]]] = {}
    for row in screening:
        groups.setdefault(family_name(row), []).append(row)
    winners = {
        family: min(rows, key=lambda row: row["metrics"]["log_loss"])
        for family, rows in groups.items()
    }

    confirmation_candidates: dict[str, Candidate] = {}
    baseline = Candidate(
        "constant",
        (1900, 2020),
        (BASELINE_RATIO,) * 2,
        False,
        1,
    )
    confirmation_candidates[baseline.key] = baseline
    for row in winners.values():
        candidate_data = row["candidate"]
        assert isinstance(candidate_data, dict)
        candidate = Candidate(
            family=str(candidate_data["family"]),
            years=tuple(int(value) for value in candidate_data["years"]),
            values=tuple(float(value) for value in candidate_data["values"]),
            step=bool(candidate_data["step"]),
            parameter_count=int(candidate_data["parameter_count"]),
        )
        confirmation_candidates[candidate.key] = candidate
    confirmation = parallel_evaluate(
        args,
        list(confirmation_candidates.values()),
        fit_last_year=CONFIRMATION_FIT_LAST_YEAR,
        score_first_year=CONFIRMATION_FIRST_YEAR,
        score_last_day=CONFIRMATION_LAST_DAY,
        label="2020-2026 confirmation",
    )
    confirmation_by_key = {row["key"]: row for row in confirmation}
    baseline_confirmation = confirmation_by_key[baseline.key]
    baseline_selection = next(row for row in screening if row["key"] == baseline.key)

    family_summary: dict[str, object] = {}
    for family, winner in sorted(winners.items()):
        confirmed = confirmation_by_key[winner["key"]]
        family_summary[family] = {
            "selected_candidate": winner["candidate"],
            "selection_2010_2019": winner["metrics"],
            "selection_log_loss_improvement_vs_deployed_constant": (
                float(baseline_selection["metrics"]["log_loss"])
                - float(winner["metrics"]["log_loss"])
            ),
            "confirmation_2020_2026": confirmed["metrics"],
            "confirmation_log_loss_improvement_vs_deployed_constant": (
                float(baseline_confirmation["metrics"]["log_loss"])
                - float(confirmed["metrics"]["log_loss"])
            ),
        }

    payload = {
        "study": "friendly information ratio by era",
        "date": "2026-07-27",
        "protocol": {
            "candidate_count": len(values),
            "families": sorted(groups),
            "ratio_search_interval": [LOWER_RATIO, UPPER_RATIO],
            "selection": (
                "Candidate curves were selected only by 2010-2019 log loss "
                "after probability temperatures were fitted through 2009."
            ),
            "confirmation": (
                "One winner per family was evaluated on untouched 2020-2026 "
                "matches after temperatures were refitted through 2019."
            ),
            "adoption_rule": (
                "Adopt only a parsimonious curve that beats the deployed "
                "constant in both selection and confirmation, remains useful "
                "in the complete Python replay with the country venue layer, "
                "and passes ranking guardrails."
            ),
            "main_network_and_venue_learning": (
                "This screen changes the main rating-network update. If a "
                "curve passes, the same curve is separately checked for the "
                "country-venue learning update before release."
            ),
        },
        "deployed_constant": {
            "ratio": BASELINE_RATIO,
            "selection_2010_2019": baseline_selection["metrics"],
            "confirmation_2020_2026": baseline_confirmation["metrics"],
        },
        "family_winners": family_summary,
        "screening_digest": hashlib.sha256(
            json.dumps(screening, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "screening_results": sorted(screening, key=lambda row: row["key"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_count": len(values),
                "deployed_constant": payload["deployed_constant"],
                "family_winners": family_summary,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
