#!/usr/bin/env python3
"""Evaluate NFELO's public conservative ranking formula against future results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize


EPS = 1e-15
Z_VALUES = (0.0, 0.5, 1.0, 1.2815515655, 1.6448536270, 1.9599639845, 2.3263478740)


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def forecast(gap: np.ndarray, home: np.ndarray, friendly: np.ndarray, parameters: np.ndarray) -> np.ndarray:
    scaled = gap / 400.0
    flag = friendly.astype(float)
    strength = (parameters[0] + parameters[1] * flag) * scaled + parameters[2] * home
    draw = parameters[3] + parameters[4] * np.abs(strength) + parameters[5] * flag
    return softmax(np.column_stack((strength, draw, -strength)))


def loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    return float(-np.log(np.maximum(probabilities[np.arange(len(outcomes)), outcomes], EPS)).mean())


def annual_forecasts(
    gap: np.ndarray,
    years: np.ndarray,
    eligible: np.ndarray,
    home: np.ndarray,
    friendly: np.ndarray,
    outcomes: np.ndarray,
    window: int,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    predictions = np.full((len(gap), 3), np.nan, dtype=float)
    fits: list[dict[str, object]] = []
    initial = np.asarray((2.0, -0.1, 0.45, 0.0, -0.5, 0.0), dtype=float)
    bounds = ((0.2, 5.0), (-2.0, 2.0), (-1.5, 1.5), (-2.5, 2.5), (-2.0, 0.5), (-1.0, 1.0))
    for year in range(1960, 2027):
        train = eligible & (years >= year - window) & (years <= year - 1)
        test = eligible & (years == year)
        if train.sum() < 500:
            continue
        fitted = minimize(
            lambda x: loss(forecast(gap[train], home[train], friendly[train], x), outcomes[train]),
            initial,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 400, "ftol": 1e-14, "gtol": 1e-8},
        )
        predictions[test] = forecast(gap[test], home[test], friendly[test], fitted.x)
        fits.append({"year": year, "training_matches": int(train.sum()), "parameters": fitted.x.tolist()})
        initial = fitted.x
    return predictions, fits


def metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float | int]:
    one = np.eye(3)[outcomes]
    cumulative = np.cumsum(probabilities, axis=1)[:, :2] - np.cumsum(one, axis=1)[:, :2]
    return {
        "matches": int(len(outcomes)),
        "log_loss": loss(probabilities, outcomes),
        "brier": float(np.square(probabilities - one).sum(axis=1).mean()),
        "rps": float(0.5 * np.square(cumulative).sum(axis=1).mean()),
        "accuracy": float((probabilities.argmax(axis=1) == outcomes).mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--components", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    network = pd.read_csv(args.network, sep="\t")
    matches = pd.read_csv(
        args.matches,
        sep="\t",
        comment="#",
        header=None,
        names=("id", "day", "year", "month", "dom", "a", "b", "ga", "gb", "home", "friendly", "level", "official_a", "official_b"),
    )
    components = np.load(args.components)
    if len(network) != len(matches):
        raise RuntimeError("row count mismatch")
    years = matches.year.to_numpy(int)
    cutoff = (years >= 1960) & (matches.day.to_numpy(int) <= 2026 * 400 + 7 * 32 + 11)
    outcomes = np.where(matches.ga > matches.gb, 0, np.where(matches.ga == matches.gb, 1, 2)).astype(int)
    home = matches.home.to_numpy(float)
    friendly = matches.friendly.to_numpy(bool)
    eligible = cutoff & (network.games_a.to_numpy() >= 30) & (network.games_b.to_numpy() >= 30)
    se_a = network.se_a.to_numpy(float)
    se_b = network.se_b.to_numpy(float)
    breadth_a = network.adjusted_mean_a.to_numpy(float)
    breadth_b = network.adjusted_mean_b.to_numpy(float)
    latent_a = network.latent_a.to_numpy(float)
    latent_b = network.latent_b.to_numpy(float)

    candidates: dict[str, np.ndarray] = {
        "latent_mean": latent_a - latent_b,
        "latent_lcb_1_645": (latent_a - 1.6448536270 * se_a) - (latent_b - 1.6448536270 * se_b),
        "world_football_elo_pre_match": matches.official_a.to_numpy(float) - matches.official_b.to_numpy(float),
    }
    for z in Z_VALUES:
        candidates[f"breadth_lcb_z{z:.6f}"] = (breadth_a - z * se_a) - (breadth_b - z * se_b)

    payload: dict[str, object] = {
        "scope": {"eligible_matches": int(eligible.sum()), "minimum_prior_matches": 30},
        "candidates": {},
    }
    neutral_decisive = eligible & (home == 0) & (outcomes != 1)
    for name, gap in candidates.items():
        for window in (4, 8, 12, 20):
            prediction, fits = annual_forecasts(gap, years, eligible, home, friendly, outcomes, window)
            valid = eligible & np.isfinite(prediction).all(axis=1)
            key = f"{name}_w{window}"
            higher_won = ((gap[neutral_decisive] > 0) & (outcomes[neutral_decisive] == 0)) | (
                (gap[neutral_decisive] < 0) & (outcomes[neutral_decisive] == 2)
            )
            payload["candidates"][key] = {
                "metrics": metrics(prediction[valid], outcomes[valid]),
                "neutral_decisive_matches": int(neutral_decisive.sum()),
                "neutral_decisive_higher_rank_won": float(higher_won.mean()),
                "fits": fits,
            }

    # The exact deployed public rating is retained as an independent cross-check.
    deployed_gap = components["pre_rating1"] - components["pre_rating2"]
    check = eligible & np.isfinite(deployed_gap)
    reconstructed = candidates["breadth_lcb_z1.644854"]
    payload["deployed_reconstruction"] = {
        "matches": int(check.sum()),
        "mean_absolute_gap_error": float(np.abs(deployed_gap[check] - reconstructed[check]).mean()),
        "max_absolute_gap_error": float(np.abs(deployed_gap[check] - reconstructed[check]).max()),
    }
    best = min(payload["candidates"], key=lambda key: payload["candidates"][key]["metrics"]["log_loss"])
    payload["best_predictive_ranking"] = best
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "best": best,
        "best_metrics": payload["candidates"][best]["metrics"],
        "deployed_z1_645_w8": payload["candidates"]["breadth_lcb_z1.644854_w8"]["metrics"],
        "breadth_mean_w8": payload["candidates"]["breadth_lcb_z0.000000_w8"]["metrics"],
        "latent_mean_w8": payload["candidates"]["latent_mean_w8"]["metrics"],
        "world_football_elo_w8": payload["candidates"]["world_football_elo_pre_match_w8"]["metrics"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
