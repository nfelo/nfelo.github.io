#!/usr/bin/env python3
"""Check era-varying friendly learning in the country venue layer."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


BASELINE_RATIO = 0.78621
GRID = (0.20, 0.40, 0.60, 0.80, 1.00, 1.20, 1.40)


@dataclass(frozen=True, slots=True)
class Profile:
    family: str
    years: tuple[int, ...]
    values: tuple[float, ...]
    step: bool

    @property
    def key(self) -> str:
        mode = "step" if self.step else "smooth"
        years = ",".join(str(value) for value in self.years)
        values = ",".join(f"{value:.6f}" for value in self.values)
        return f"{self.family}|{mode}|{years}|{values}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay-script", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--components", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_overlay(path: Path):
    spec = importlib.util.spec_from_file_location("venue_overlay", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def profiles() -> list[Profile]:
    result = [
        Profile("constant", (1872, 2020), (BASELINE_RATIO,) * 2, False)
    ]
    for value in GRID:
        result.append(
            Profile("constant", (1872, 2020), (value, value), False)
        )
    for first in GRID:
        for second in GRID:
            result.append(
                Profile(
                    "two_era_step_2010",
                    (1872, 2010),
                    (first, second),
                    True,
                )
            )
            result.append(
                Profile(
                    "smooth_trend",
                    (1900, 2020),
                    (first, second),
                    False,
                )
            )
    rng = np.random.default_rng(20260727)
    for _ in range(64):
        values = np.exp(
            rng.uniform(math.log(0.20), math.log(1.40), size=3)
        )
        result.append(
            Profile(
                "three_era_step_1980_2010",
                (1872, 1980, 2010),
                tuple(round(float(value), 8) for value in values),
                True,
            )
        )
    return list({profile.key: profile for profile in result}.values())


def ratio_values(profile: Profile, years: np.ndarray) -> np.ndarray:
    if profile.step:
        boundaries = np.asarray(profile.years, dtype=np.int32)
        indices = np.searchsorted(boundaries, years, side="right") - 1
        indices = np.clip(indices, 0, len(profile.values) - 1)
        return np.asarray(profile.values, dtype=np.float64)[indices]
    return np.exp(
        np.interp(
            years.astype(np.float64),
            np.asarray(profile.years, dtype=np.float64),
            np.log(np.asarray(profile.values, dtype=np.float64)),
        )
    )


def probability_for_profile(overlay, data, candidate, profile: Profile) -> np.ndarray:
    friendly_ratio = ratio_values(profile, data.year)
    weights = np.where(data.friendly, friendly_ratio, 1.0)
    correction, correction_variance, _ = overlay.simulate(
        data,
        candidate,
        {"profile": weights},
    )
    return overlay.probabilities(
        data.difference + correction,
        data.variance + correction_variance,
        data.year,
        data.friendly,
    )


def profile_from_row(row: dict[str, object]) -> Profile:
    values = row["profile"]
    assert isinstance(values, dict)
    return Profile(
        family=str(values["family"]),
        years=tuple(int(value) for value in values["years"]),
        values=tuple(float(value) for value in values["values"]),
        step=bool(values["step"]),
    )


def main() -> None:
    args = parse_args()
    overlay = load_overlay(args.overlay_script)
    data = overlay.load_data(args.matches, args.components)
    score_mask = (
        (data.year >= 1960)
        & (data.day <= 2026 * 400 + 7 * 32 + 11)
    )
    selection_mask = score_mask & (data.year >= 2010) & (data.year <= 2019)
    confirmation_mask = score_mask & (data.year >= 2020)
    candidate = overlay.Candidate(
        structure="dependence",
        prior_sd=60.0,
        half_life=40.0,
        learning="profile",
        uncertainty_scale=0.0,
    )
    rows: list[dict[str, object]] = []
    values = profiles()
    for index, profile in enumerate(values, start=1):
        probability = probability_for_profile(
            overlay,
            data,
            candidate,
            profile,
        )
        rows.append(
            {
                "profile": asdict(profile),
                "key": profile.key,
                "selection_2010_2019": overlay.metrics(
                    probability,
                    data.outcome,
                    selection_mask,
                ),
                "confirmation_2020_2026": overlay.metrics(
                    probability,
                    data.outcome,
                    confirmation_mask,
                ),
            }
        )
        if index % 25 == 0 or index == len(values):
            print(f"venue friendly-era check: {index}/{len(values)}", flush=True)

    baseline_key = Profile(
        "constant",
        (1872, 2020),
        (BASELINE_RATIO,) * 2,
        False,
    ).key
    baseline = next(row for row in rows if row["key"] == baseline_key)
    families: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        profile = row["profile"]
        assert isinstance(profile, dict)
        family = str(profile["family"])
        families.setdefault(family, []).append(row)
    winners = {
        family: min(
            family_rows,
            key=lambda row: row["selection_2010_2019"]["log_loss"],
        )
        for family, family_rows in families.items()
    }
    for winner in winners.values():
        winner["selection_improvement_vs_constant"] = (
            baseline["selection_2010_2019"]["log_loss"]
            - winner["selection_2010_2019"]["log_loss"]
        )
        winner["confirmation_improvement_vs_constant"] = (
            baseline["confirmation_2020_2026"]["log_loss"]
            - winner["confirmation_2020_2026"]["log_loss"]
        )

    baseline_probability = probability_for_profile(
        overlay,
        data,
        candidate,
        profile_from_row(baseline),
    )
    baseline_loss = overlay.per_match_loss(
        baseline_probability,
        data.outcome,
    )
    best_constant = winners["constant"]
    best_constant_probability = probability_for_profile(
        overlay,
        data,
        candidate,
        profile_from_row(best_constant),
    )
    best_constant_loss = overlay.per_match_loss(
        best_constant_probability,
        data.outcome,
    )
    for family, winner in winners.items():
        winner_probability = probability_for_profile(
            overlay,
            data,
            candidate,
            profile_from_row(winner),
        )
        winner_loss = overlay.per_match_loss(
            winner_probability,
            data.outcome,
        )
        winner["bootstrap_vs_deployed_constant"] = {
            "selection_2010_2019": overlay.paired_year_bootstrap(
                data,
                baseline_loss,
                winner_loss,
                selection_mask,
            ),
            "confirmation_2020_2026": overlay.paired_year_bootstrap(
                data,
                baseline_loss,
                winner_loss,
                confirmation_mask,
            ),
        }
        if family != "constant":
            winner["bootstrap_vs_best_constant"] = {
                "selection_2010_2019": overlay.paired_year_bootstrap(
                    data,
                    best_constant_loss,
                    winner_loss,
                    selection_mask,
                ),
                "confirmation_2020_2026": overlay.paired_year_bootstrap(
                    data,
                    best_constant_loss,
                    winner_loss,
                    confirmation_mask,
                ),
            }

    payload = {
        "study": "era-varying friendly learning in country venue effects",
        "date": "2026-07-27",
        "candidate_count": len(values),
        "selection_period": "2010-2019",
        "untouched_confirmation_period": "2020-2026-07-11",
        "deployed_constant": baseline,
        "family_winners": winners,
        "results": sorted(rows, key=lambda row: row["key"]),
    }
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "deployed_constant": baseline,
                "family_winners": winners,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
