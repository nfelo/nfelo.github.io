#!/usr/bin/env python3
"""Causal country-specific home, away and neutral venue-effect search.

This first-stage evaluator keeps the deployed opponent-network states fixed and
learns only an additional venue residual from matches that occurred strictly
earlier.  It is deliberately fast enough to screen a broad hierarchical model
family before the strongest candidates are replayed through the complete
rating and score model.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np


EPSILON = 1e-15
LN10_OVER_400 = math.log(10.0) / 400.0
QUALITY_SCALE = 1.7440260583320362
FRIENDLY_INFORMATION_RATIO = 0.78621
FRIENDLY_TEMPERATURE = 0.896294991479
COMPETITIVE_TEMPERATURE = 1.061356232973
G_DRAW = 3.486642593835564
G_TWO = 1.755270459152449
G_THREE = 2.20104735688078
G_TAIL = 1.467767822525712
MARGIN_ENVIRONMENT_POWER = 1.880272889370813
KNOT_YEARS = np.asarray((1900, 1930, 1960, 1990, 2020), dtype=np.float64)
SCALE = np.asarray(
    (
        1.9329803161851784,
        1.5602143637570678,
        1.3044459799655215,
        1.1218570234757215,
        1.0,
    ),
    dtype=np.float64,
)
HOME = np.asarray(
    (
        73.123115543503,
        96.74246793815797,
        112.89558566270792,
        112.66052421548639,
        83.53363897913016,
    ),
    dtype=np.float64,
)
DRAW = np.asarray(
    (
        0.18451738305372078,
        0.2174334339602218,
        0.25965582882029153,
        0.30867595078868215,
        0.32513463832148676,
    ),
    dtype=np.float64,
)
NODES = np.asarray(
    (
        -3.6684708465595826,
        -2.7832900997816514,
        -2.0259480158257555,
        -1.3265570844949328,
        -0.6568095668820998,
        0.0,
        0.6568095668820998,
        1.3265570844949328,
        2.0259480158257555,
        2.7832900997816514,
        3.6684708465595826,
    ),
    dtype=np.float64,
)
WEIGHTS = np.asarray(
    (
        0.0000008121849790214923,
        0.00019567193027122338,
        0.0067202852355372645,
        0.06613874607105782,
        0.24224029987396992,
        0.36940836940836935,
        0.24224029987396992,
        0.06613874607105782,
        0.0067202852355372645,
        0.00019567193027122338,
        0.0000008121849790214923,
    ),
    dtype=np.float64,
)
FOLDS = (
    (1960, 1979),
    (1980, 1999),
    (2000, 2009),
    (2010, 2019),
    (2020, 2026),
)
STRUCTURES = (
    "global",
    "host",
    "away",
    "dependence",
    "dependence_nonhome",
    "dependence_neutral",
    "global_dependence",
    "global_dependence_neutral",
    "neutral",
    "host_neutral",
    "away_neutral",
    "host_away",
    "host_nonhome",
    "host_away_neutral",
    "global_host_away",
    "global_host_away_neutral",
)


@dataclass(frozen=True, slots=True)
class Candidate:
    structure: str
    prior_sd: float
    half_life: float
    learning: str
    uncertainty_scale: float = 0.0

    @property
    def key(self) -> str:
        half = "static" if self.half_life >= 1e8 else f"{self.half_life:g}y"
        return (
            f"{self.structure}|sd={self.prior_sd:g}|half={half}|"
            f"learn={self.learning}|uncertainty={self.uncertainty_scale:g}"
        )


@dataclass(slots=True)
class MatchData:
    identifier: np.ndarray
    day: np.ndarray
    year: np.ndarray
    team1: np.ndarray
    team2: np.ndarray
    goals1: np.ndarray
    goals2: np.ndarray
    home: np.ndarray
    friendly: np.ndarray
    outcome: np.ndarray
    fractional: np.ndarray
    margin: np.ndarray
    baseline_probability: np.ndarray
    difference: np.ndarray
    variance: np.ndarray
    team_count: int


def interpolate(years: np.ndarray, values: np.ndarray) -> np.ndarray:
    return np.interp(years.astype(np.float64), KNOT_YEARS, values)


def era_scale(years: np.ndarray) -> np.ndarray:
    return np.exp(interpolate(years, np.log(SCALE)))


def era_home(years: np.ndarray) -> np.ndarray:
    return interpolate(years, HOME)


def draw_probability(years: np.ndarray) -> np.ndarray:
    unit = (DRAW - 0.05) / 0.40
    transformed = np.log(unit / (1.0 - unit))
    logit = interpolate(years, transformed)
    return 0.05 + 0.40 / (1.0 + np.exp(-logit))


def logistic10(values: np.ndarray | float) -> np.ndarray | float:
    result = 1.0 / (1.0 + np.power(10.0, -np.asarray(values) / 400.0))
    return float(result) if result.ndim == 0 else result


def probabilities(
    difference: np.ndarray,
    variance: np.ndarray,
    years: np.ndarray,
    friendly: np.ndarray,
) -> np.ndarray:
    scale = era_scale(years)
    sampled = (
        difference[:, None]
        + math.sqrt(2.0)
        * scale[:, None]
        * np.sqrt(np.maximum(variance, 0.0))[:, None]
        * NODES[None, :]
    )
    expected = np.asarray(logistic10(sampled), dtype=np.float64)
    draws = (
        draw_probability(years)[:, None]
        * 4.0
        * expected
        * (1.0 - expected)
    )
    base = np.column_stack(
        (
            (expected - 0.5 * draws) @ WEIGHTS,
            draws @ WEIGHTS,
            (1.0 - expected - 0.5 * draws) @ WEIGHTS,
        )
    )
    temperature = np.where(
        friendly,
        FRIENDLY_TEMPERATURE,
        COMPETITIVE_TEMPERATURE,
    )
    adjusted = np.power(np.maximum(base, EPSILON), temperature[:, None])
    return adjusted / adjusted.sum(axis=1, keepdims=True)


def goal_weight(margin: int, environment: float) -> float:
    if margin == 0:
        return G_DRAW
    raw = min(margin, 7)
    effective = 1.0 + (raw - 1.0) * (
        1.10 / max(0.10, environment)
    ) ** MARGIN_ENVIRONMENT_POWER
    effective = min(7.0, effective)
    if effective <= 1.0:
        return 1.0
    if effective <= 2.0:
        return 1.0 + (effective - 1.0) * (G_TWO - 1.0)
    if effective <= 3.0:
        return G_TWO + (effective - 2.0) * (G_THREE - G_TWO)
    return G_THREE + G_TAIL * (effective - 3.0)


def model_learning_weights(data: MatchData) -> np.ndarray:
    result = np.ones(len(data.day), dtype=np.float64)
    window: list[tuple[int, float]] = []
    start = 0
    excess_sum = 0.0
    for index, year in enumerate(data.year):
        while start < len(window) and window[start][0] < int(year) - 20:
            excess_sum -= window[start][1]
            start += 1
        environment = (20.0 * 1.10 + excess_sum) / (
            20.0 + len(window) - start
        )
        weight = QUALITY_SCALE * goal_weight(int(data.margin[index]), environment)
        if data.friendly[index]:
            weight *= FRIENDLY_INFORMATION_RATIO
        result[index] = weight
        if data.margin[index] > 0:
            excess = float(min(int(data.margin[index]), 7) - 1)
            window.append((int(year), excess))
            excess_sum += excess
    return result


def load_data(matches_path: Path, components_path: Path) -> MatchData:
    matches = np.loadtxt(matches_path, comments="#", dtype=np.float64)
    components = np.loadtxt(
        components_path,
        skiprows=1,
        usecols=range(9),
        dtype=np.float64,
    )
    if len(matches) != len(components):
        raise ValueError("Match and component row counts differ")
    identifier = matches[:, 0].astype(np.int32)
    if not np.array_equal(identifier, components[:, 0].astype(np.int32)):
        raise ValueError("Match and component identities differ")
    goals1 = matches[:, 7].astype(np.int16)
    goals2 = matches[:, 8].astype(np.int16)
    outcome = np.where(goals1 > goals2, 0, np.where(goals1 == goals2, 1, 2))
    fractional = np.where(goals1 > goals2, 1.0, np.where(goals1 == goals2, 0.5, 0.0))
    team1 = matches[:, 5].astype(np.int16)
    team2 = matches[:, 6].astype(np.int16)
    data = MatchData(
        identifier=identifier,
        day=matches[:, 1].astype(np.int32),
        year=matches[:, 2].astype(np.int16),
        team1=team1,
        team2=team2,
        goals1=goals1,
        goals2=goals2,
        home=matches[:, 9].astype(np.int8),
        friendly=matches[:, 10].astype(bool),
        outcome=outcome.astype(np.int8),
        fractional=fractional,
        margin=np.abs(goals1 - goals2).astype(np.int8),
        baseline_probability=components[:, 3:6],
        difference=components[:, 7],
        variance=components[:, 8],
        team_count=int(max(team1.max(), team2.max()) + 1),
    )
    reconstructed = probabilities(
        data.difference,
        data.variance,
        data.year,
        data.friendly,
    )
    maximum_error = float(np.max(np.abs(reconstructed - data.baseline_probability)))
    if maximum_error > 2e-12:
        raise ValueError(
            f"Baseline probability reconstruction differs by {maximum_error}"
        )
    return data


def feature_channels(structure: str) -> tuple[str, ...]:
    mapping = {
        "global": ("global",),
        "host": ("host",),
        "away": ("away",),
        "dependence": ("dependence",),
        "dependence_nonhome": ("dependence",),
        "dependence_neutral": ("dependence", "neutral"),
        "global_dependence": ("global", "dependence"),
        "global_dependence_neutral": (
            "global",
            "dependence",
            "neutral",
        ),
        "neutral": ("neutral",),
        "host_neutral": ("host", "neutral"),
        "away_neutral": ("away", "neutral"),
        "host_away": ("host", "away"),
        "host_nonhome": ("host", "nonhome"),
        "host_away_neutral": ("host", "away", "neutral"),
        "global_host_away": ("global", "host", "away"),
        "global_host_away_neutral": (
            "global",
            "host",
            "away",
            "neutral",
        ),
    }
    return mapping[structure]


def features(
    structure: str,
    first: int,
    second: int,
    home: int,
) -> tuple[tuple[str, int, float], ...]:
    values: list[tuple[str, int, float]] = []
    channels = feature_channels(structure)
    if home:
        host = first if home == 1 else second
        visitor = second if home == 1 else first
        sign = float(home)
        if "global" in channels:
            values.append(("global", 0, sign))
        if "host" in channels:
            values.append(("host", host, sign))
        if "away" in channels:
            values.append(("away", visitor, sign))
        if "nonhome" in channels:
            values.append(("nonhome", visitor, sign))
        if "dependence" in channels:
            values.append(("dependence", host, 0.5 * sign))
            values.append(("dependence", visitor, 0.5 * sign))
    else:
        if "neutral" in channels:
            values.append(("neutral", first, 1.0))
            values.append(("neutral", second, -1.0))
        if "nonhome" in channels:
            values.append(("nonhome", first, -1.0))
            values.append(("nonhome", second, 1.0))
        if structure == "dependence_nonhome":
            values.append(("dependence", first, -0.5))
            values.append(("dependence", second, 0.5))
    return tuple(values)


def simulate(
    data: MatchData,
    candidate: Candidate,
    learning_weights: dict[str, np.ndarray],
) -> tuple[
    np.ndarray,
    np.ndarray,
    dict[str, dict[str, list[float] | list[int]]],
]:
    channels = feature_channels(candidate.structure)
    size = {
        channel: 1 if channel == "global" else data.team_count
        for channel in channels
    }
    prior_variance = candidate.prior_sd**2
    means = {
        channel: np.zeros(count, dtype=np.float64)
        for channel, count in size.items()
    }
    variances = {
        channel: np.full(count, prior_variance, dtype=np.float64)
        for channel, count in size.items()
    }
    last_day = {
        channel: np.full(count, -1, dtype=np.int32)
        for channel, count in size.items()
    }
    counts = {
        channel: np.zeros(count, dtype=np.int32)
        for channel, count in size.items()
    }
    correction = np.zeros(len(data.day), dtype=np.float64)
    correction_variance = np.zeros(len(data.day), dtype=np.float64)
    weights = learning_weights[candidate.learning]

    def advance(channel: str, team: int, day: int) -> None:
        previous = int(last_day[channel][team])
        if previous >= 0 and day > previous and candidate.half_life < 1e8:
            elapsed = (day - previous) / 400.0
            retention = math.exp(-math.log(2.0) * elapsed / candidate.half_life)
            means[channel][team] *= retention
            variances[channel][team] = prior_variance - (
                prior_variance - variances[channel][team]
            ) * retention**2
        last_day[channel][team] = day

    start = 0
    while start < len(data.day):
        day = int(data.day[start])
        end = start + 1
        while end < len(data.day) and int(data.day[end]) == day:
            end += 1
        match_features: list[tuple[tuple[str, int, float], ...]] = []
        touched: set[tuple[str, int]] = set()
        for index in range(start, end):
            row_features = features(
                candidate.structure,
                int(data.team1[index]),
                int(data.team2[index]),
                int(data.home[index]),
            )
            match_features.append(row_features)
            for channel, team, _ in row_features:
                key = (channel, team)
                if key not in touched:
                    advance(channel, team, day)
                    touched.add(key)
            correction[index] = sum(
                coefficient * means[channel][team]
                for channel, team, coefficient in row_features
            )
            correction_variance[index] = candidate.uncertainty_scale * sum(
                coefficient**2 * variances[channel][team]
                for channel, team, coefficient in row_features
            )

        gradient: defaultdict[tuple[str, int], float] = defaultdict(float)
        curvature: defaultdict[tuple[str, int], float] = defaultdict(float)
        for offset, index in enumerate(range(start, end)):
            expected = float(
                logistic10(data.difference[index] + correction[index])
            )
            weight = float(weights[index])
            residual = float(data.fractional[index]) - expected
            information = max(1e-8, expected * (1.0 - expected))
            for channel, team, coefficient in match_features[offset]:
                key = (channel, team)
                gradient[key] += (
                    weight * LN10_OVER_400 * residual * coefficient
                )
                curvature[key] += (
                    weight
                    * LN10_OVER_400**2
                    * information
                    * coefficient**2
                )
                counts[channel][team] += 1
        for (channel, team), score in gradient.items():
            precision = 1.0 / max(variances[channel][team], 1e-12)
            updated_precision = precision + curvature[(channel, team)]
            means[channel][team] += score / updated_precision
            variances[channel][team] = 1.0 / updated_precision
        start = end

    final_day = int(data.day[-1])
    for channel in channels:
        for team in range(size[channel]):
            if last_day[channel][team] >= 0:
                advance(channel, team, final_day)
    state = {
        channel: {
            "mean": means[channel].tolist(),
            "sd": np.sqrt(np.maximum(variances[channel], 0.0)).tolist(),
            "last_day": last_day[channel].tolist(),
            "matches": counts[channel].tolist(),
        }
        for channel in channels
    }
    return correction, correction_variance, state


def per_match_loss(probability: np.ndarray, outcome: np.ndarray) -> np.ndarray:
    return -np.log(
        np.maximum(
            probability[np.arange(len(outcome)), outcome],
            EPSILON,
        )
    )


def metrics(
    probability: np.ndarray,
    outcome: np.ndarray,
    mask: np.ndarray,
) -> dict[str, float | int]:
    selected = probability[mask]
    actual = outcome[mask]
    one_hot = np.zeros_like(selected)
    one_hot[np.arange(len(actual)), actual] = 1.0
    difference = selected - one_hot
    cumulative = np.cumsum(difference, axis=1)[:, :2]
    return {
        "matches": int(mask.sum()),
        "log_loss": float(per_match_loss(selected, actual).mean()),
        "brier": float(np.square(difference).sum(axis=1).mean()),
        "rps": float(0.5 * np.square(cumulative).sum(axis=1).mean()),
        "accuracy": float(
            (np.argmax(selected, axis=1) == actual).mean()
        ),
    }


def candidate_row(
    data: MatchData,
    candidate: Candidate,
    learning_weights: dict[str, np.ndarray],
    score_mask: np.ndarray,
    include_state: bool = False,
) -> tuple[dict[str, object], np.ndarray, dict[str, object] | None]:
    correction, correction_variance, state = simulate(
        data,
        candidate,
        learning_weights,
    )
    probability = probabilities(
        data.difference + correction,
        data.variance + correction_variance,
        data.year,
        data.friendly,
    )
    result: dict[str, object] = {
        "key": candidate.key,
        "candidate": asdict(candidate),
        "overall": metrics(probability, data.outcome, score_mask),
        "folds": {},
        "venue": {},
        "correction": {
            "mean": float(correction[score_mask].mean()),
            "mean_absolute": float(np.abs(correction[score_mask]).mean()),
            "p95_absolute": float(
                np.quantile(np.abs(correction[score_mask]), 0.95)
            ),
            "maximum_absolute": float(np.abs(correction[score_mask]).max()),
        },
    }
    for first_year, last_year in FOLDS:
        mask = (
            score_mask
            & (data.year >= first_year)
            & (data.year <= last_year)
        )
        result["folds"][f"{first_year}-{last_year}"] = metrics(
            probability,
            data.outcome,
            mask,
        )
    for label, venue_mask in (
        ("home", data.home != 0),
        ("neutral", data.home == 0),
        ("friendly", data.friendly),
        ("competitive", ~data.friendly),
    ):
        result["venue"][label] = metrics(
            probability,
            data.outcome,
            score_mask & venue_mask,
        )
    return result, per_match_loss(probability, data.outcome), state if include_state else None


def paired_year_bootstrap(
    data: MatchData,
    baseline_loss: np.ndarray,
    candidate_loss: np.ndarray,
    mask: np.ndarray,
    samples: int = 100_000,
) -> dict[str, float | int]:
    years = np.unique(data.year[mask])
    differences = candidate_loss - baseline_loss
    sums = np.asarray(
        [differences[mask & (data.year == year)].sum() for year in years]
    )
    counts = np.asarray(
        [(mask & (data.year == year)).sum() for year in years],
        dtype=np.int64,
    )
    rng = np.random.default_rng(20260727)
    sampled = np.empty(samples, dtype=np.float64)
    batch = 2_000
    for start in range(0, samples, batch):
        end = min(samples, start + batch)
        choices = rng.integers(0, len(years), size=(end - start, len(years)))
        sampled[start:end] = (
            sums[choices].sum(axis=1) / counts[choices].sum(axis=1)
        )
    return {
        "year_blocks": int(len(years)),
        "samples": samples,
        "mean_candidate_minus_baseline": float(differences[mask].mean()),
        "ci95_low": float(np.quantile(sampled, 0.025)),
        "ci95_high": float(np.quantile(sampled, 0.975)),
        "probability_candidate_better": float((sampled < 0.0).mean()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--components", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--structures",
        help="Comma-separated subset of the declared structures",
    )
    parser.add_argument(
        "--prior-sds",
        default="15,30,45,60,90",
        help="Comma-separated prior standard deviations in Elo points",
    )
    parser.add_argument(
        "--half-lives",
        default="5,10,20,40,static",
        help="Comma-separated temporal half-lives in years",
    )
    parser.add_argument(
        "--learning",
        default="unit,model",
        help="Comma-separated learning-weight rules",
    )
    parser.add_argument(
        "--uncertainty-scales",
        default="0",
        help="Comma-separated fractions of venue-state variance used in forecasts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = load_data(args.matches, args.components)
    teams = json.loads(args.teams.read_text(encoding="utf-8"))
    if len(teams) != data.team_count:
        raise ValueError("Team-code list does not match numeric match data")
    score_mask = (
        (data.year >= 1960)
        & (data.day <= 2026 * 400 + 7 * 32 + 11)
    )
    baseline_loss = per_match_loss(
        data.baseline_probability,
        data.outcome,
    )
    baseline: dict[str, object] = {
        "overall": metrics(
            data.baseline_probability,
            data.outcome,
            score_mask,
        ),
        "folds": {},
        "venue": {},
    }
    for first_year, last_year in FOLDS:
        mask = (
            score_mask
            & (data.year >= first_year)
            & (data.year <= last_year)
        )
        baseline["folds"][f"{first_year}-{last_year}"] = metrics(
            data.baseline_probability,
            data.outcome,
            mask,
        )
    for label, venue_mask in (
        ("home", data.home != 0),
        ("neutral", data.home == 0),
        ("friendly", data.friendly),
        ("competitive", ~data.friendly),
    ):
        baseline["venue"][label] = metrics(
            data.baseline_probability,
            data.outcome,
            score_mask & venue_mask,
        )

    unit = np.where(
        data.friendly,
        FRIENDLY_INFORMATION_RATIO,
        1.0,
    )
    learning_weights = {
        "unit": unit,
        "unit_all": np.ones(len(data.day), dtype=np.float64),
        "model": model_learning_weights(data),
    }
    selected_structures: Iterable[str] = STRUCTURES
    if args.structures:
        requested = tuple(
            value.strip()
            for value in args.structures.split(",")
            if value.strip()
        )
        unknown = sorted(set(requested) - set(STRUCTURES))
        if unknown:
            raise ValueError(f"Unknown structures: {unknown}")
        selected_structures = requested
    prior_sds = tuple(
        float(value.strip())
        for value in args.prior_sds.split(",")
        if value.strip()
    )
    half_lives = tuple(
        1e9 if value.strip().lower() == "static" else float(value.strip())
        for value in args.half_lives.split(",")
        if value.strip()
    )
    learning_rules = tuple(
        value.strip()
        for value in args.learning.split(",")
        if value.strip()
    )
    uncertainty_scales = tuple(
        float(value.strip())
        for value in args.uncertainty_scales.split(",")
        if value.strip()
    )
    unknown_learning = sorted(set(learning_rules) - set(learning_weights))
    if unknown_learning:
        raise ValueError(f"Unknown learning rules: {unknown_learning}")
    candidates = [
        Candidate(
            structure,
            prior_sd,
            half_life,
            learning,
            uncertainty_scale,
        )
        for structure in selected_structures
        for prior_sd in prior_sds
        for half_life in half_lives
        for learning in learning_rules
        for uncertainty_scale in uncertainty_scales
    ]
    if args.limit:
        candidates = candidates[: args.limit]

    rows: list[dict[str, object]] = []
    losses: dict[str, np.ndarray] = {}
    for index, candidate in enumerate(candidates, start=1):
        row, loss, _ = candidate_row(
            data,
            candidate,
            learning_weights,
            score_mask,
        )
        row["overall"]["candidate_minus_baseline"] = (
            float(row["overall"]["log_loss"])
            - float(baseline["overall"]["log_loss"])
        )
        for fold, values in row["folds"].items():
            values["candidate_minus_baseline"] = (
                float(values["log_loss"])
                - float(baseline["folds"][fold]["log_loss"])
            )
        rows.append(row)
        losses[candidate.key] = loss
        if index % 25 == 0 or index == len(candidates):
            best = min(
                rows,
                key=lambda item: float(item["overall"]["log_loss"]),
            )
            print(
                f"{index}/{len(candidates)}; best={best['key']} "
                f"loss={best['overall']['log_loss']:.9f}",
                flush=True,
            )

    tuning_mask = score_mask & (data.year <= 2019)
    holdout_mask = score_mask & (data.year >= 2020)
    selected = min(
        rows,
        key=lambda row: float(
            (losses[str(row["key"])][tuning_mask]).mean()
        ),
    )
    selected_candidate = Candidate(**selected["candidate"])
    selected_row, selected_loss, selected_state = candidate_row(
        data,
        selected_candidate,
        learning_weights,
        score_mask,
        include_state=True,
    )
    selected_row["overall"]["candidate_minus_baseline"] = (
        float(selected_row["overall"]["log_loss"])
        - float(baseline["overall"]["log_loss"])
    )
    selected_row["selection_log_loss_through_2019"] = float(
        selected_loss[tuning_mask].mean()
    )
    selected_row["selection_baseline_through_2019"] = float(
        baseline_loss[tuning_mask].mean()
    )
    selected_correction, selected_variance, _ = simulate(
        data,
        selected_candidate,
        learning_weights,
    )
    selected_row["untouched_2020_2026"] = {
        **metrics(
            probabilities(
                data.difference + selected_correction,
                data.variance + selected_variance,
                data.year,
                data.friendly,
            ),
            data.outcome,
            holdout_mask,
        ),
        "candidate_minus_baseline": float(
            selected_loss[holdout_mask].mean()
            - baseline_loss[holdout_mask].mean()
        ),
    }
    selected_row["bootstrap_all"] = paired_year_bootstrap(
        data,
        baseline_loss,
        selected_loss,
        score_mask,
    )
    selected_row["bootstrap_2020_2026"] = paired_year_bootstrap(
        data,
        baseline_loss,
        selected_loss,
        holdout_mask,
    )
    selected_row["state"] = selected_state

    payload = {
        "study": {
            "date": "2026-07-27",
            "matches_total": int(len(data.day)),
            "matches_scored": int(score_mask.sum()),
            "results_through": "2026-07-25",
            "fixed_audit_cutoff": "2026-07-11",
            "candidate_count": len(candidates),
            "selection_rule": (
                "lowest causal overlay log loss through 2019; 2020-2026 "
                "untouched until final evaluation"
            ),
            "team_codes": teams,
        },
        "baseline": baseline,
        "selected": selected_row,
        "candidates": sorted(
            rows,
            key=lambda row: float(row["overall"]["log_loss"]),
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
