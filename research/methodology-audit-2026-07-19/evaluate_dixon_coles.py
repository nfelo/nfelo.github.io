#!/usr/bin/env python3
"""Test a Dixon-Coles low-score correction inside the NFELO score layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize


EPS = 1e-15
BLOCKS = ((1960, 1979), (1980, 1999), (2000, 2009), (2010, 2019), (2020, 2026))


def release_index(year: int) -> int:
    return 0 if year <= 1979 else 1 if year <= 1999 else 2 if year <= 2009 else 3 if year <= 2019 else 4


def score_calibration(
    raw: np.ndarray,
    friendly: np.ndarray,
    tilt: float,
    friendly_power: float,
    competitive_power: float,
) -> np.ndarray:
    values = np.maximum(raw, EPS).copy()
    values[:, 1] *= np.exp(tilt)
    values /= values.sum(axis=1, keepdims=True)
    powers = np.where(friendly, friendly_power, competitive_power)
    values = np.power(values, powers[:, None])
    return values / values.sum(axis=1, keepdims=True)


def correction(raw: np.ndarray, lambdas: np.ndarray, rho: float) -> np.ndarray:
    """Aggregate the four Dixon-Coles low-score cell adjustments to W/D/L."""
    lambda1 = lambdas[:, 0]
    lambda2 = lambdas[:, 1]
    common = np.exp(-(lambda1 + lambda2)) * lambda1 * lambda2 * rho
    result = raw.copy()
    result[:, 0] += common
    result[:, 1] -= 2.0 * common
    result[:, 2] += common
    return result


def predict(
    values: np.ndarray,
    network: np.ndarray,
    raw: np.ndarray,
    lambdas: np.ndarray,
    friendly: np.ndarray,
    use_correction: bool,
) -> np.ndarray:
    offset = 1 if use_correction else 0
    rho = float(values[0]) if use_correction else 0.0
    adjusted = correction(raw, lambdas, rho) if use_correction else raw
    score = score_calibration(adjusted, friendly, *values[offset:offset + 3])
    weights = np.where(friendly, values[offset + 3], values[offset + 4])
    return weights[:, None] * network + (1.0 - weights[:, None]) * score


def log_loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    if not np.all(np.isfinite(probabilities)) or np.any(probabilities <= 0.0):
        return 1e6
    return float(-np.log(probabilities[np.arange(len(outcomes)), outcomes]).mean())


def annual(
    source: np.lib.npyio.NpzFile,
    use_correction: bool,
    window: int = 8,
    reference_fits: list[dict[str, object]] | None = None,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    years = source["year"].astype(int)
    network = source["network"]
    friendly = source["friendly"].astype(bool)
    outcomes = source["outcome"].astype(int)
    raw_states = source["all_score_raw"]
    lambda_states = source["all_score_lambda"]
    result = np.full_like(network, np.nan)
    fits: list[dict[str, object]] = []
    if use_correction:
        bounds = ((-0.12, 0.01), (-0.5, 0.5), (0.6, 1.5), (0.6, 1.5), (0.0, 1.0), (0.0, 1.0))
    else:
        bounds = ((-0.5, 0.5), (0.6, 1.5), (0.6, 1.5), (0.0, 1.0), (0.0, 1.0))
    for year in range(1960, 2027):
        state = release_index(year)
        train = (years >= year - window) & (years <= year - 1)
        test = years == year
        arguments = (
            network[train], raw_states[train, state], lambda_states[train, state],
            friendly[train], use_correction,
        )
        if use_correction:
            if reference_fits is None:
                raise ValueError("corrected fit requires the nested uncorrected fit")
            base = np.asarray(reference_fits[year - 1960]["parameters"], dtype=float)
            starts = (np.r_[-0.03, base], np.r_[0.0, base])
        else:
            starts = (np.asarray((0.10, 0.95, 1.05, 0.65, 0.65), dtype=float),)
        attempts = [
            minimize(
                lambda x: log_loss(predict(x, *arguments), outcomes[train]),
                start,
                method="Nelder-Mead",
                bounds=bounds,
                options={"maxiter": 1800, "xatol": 1e-8, "fatol": 1e-11},
            )
            for start in starts
        ]
        fitted = min(attempts, key=lambda item: float(item.fun))
        result[test] = predict(
            fitted.x,
            network[test], raw_states[test, state], lambda_states[test, state],
            friendly[test], use_correction,
        )
        fits.append({"year": year, "parameters": fitted.x.tolist(), "training_loss": float(fitted.fun)})
    return result, fits


def metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float | int]:
    one = np.eye(3)[outcomes]
    cumulative = np.cumsum(probabilities, axis=1)[:, :2] - np.cumsum(one, axis=1)[:, :2]
    return {
        "matches": int(len(outcomes)),
        "log_loss": log_loss(probabilities, outcomes),
        "brier": float(np.square(probabilities - one).sum(axis=1).mean()),
        "rps": float(0.5 * np.square(cumulative).sum(axis=1).mean()),
        "accuracy": float((probabilities.argmax(axis=1) == outcomes).mean()),
    }


def bootstrap(
    candidate: np.ndarray,
    reference: np.ndarray,
    outcomes: np.ndarray,
    years: np.ndarray,
    draws: int = 20_000,
) -> dict[str, float | int]:
    difference = -np.log(candidate[np.arange(len(outcomes)), outcomes]) + np.log(
        reference[np.arange(len(outcomes)), outcomes]
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
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("components", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = np.load(args.components)
    baseline, baseline_fits = annual(source, False)
    corrected, corrected_fits = annual(source, True, reference_fits=baseline_fits)
    years = source["year"].astype(int)
    cutoff = (years >= 1960) & (source["date"] <= "2026-07-11")
    outcomes = source["outcome"].astype(int)
    payload: dict[str, object] = {
        "scope_note": "Annual fits use the previous eight complete years; the captured core network remains a retrospective final-parameter replay.",
        "uncorrected": {"aggregate": metrics(baseline[cutoff], outcomes[cutoff]), "fits": baseline_fits},
        "dixon_coles": {"aggregate": metrics(corrected[cutoff], outcomes[cutoff]), "fits": corrected_fits},
        "comparison": bootstrap(corrected[cutoff], baseline[cutoff], outcomes[cutoff], years[cutoff]),
        "blocks": {},
    }
    for first, last in BLOCKS:
        block = cutoff & (years >= first) & (years <= last)
        payload["blocks"][f"{first}-{last}"] = {
            "uncorrected": metrics(baseline[block], outcomes[block]),
            "dixon_coles": metrics(corrected[block], outcomes[block]),
        }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "uncorrected": payload["uncorrected"]["aggregate"],
        "dixon_coles": payload["dixon_coles"]["aggregate"],
        "comparison": payload["comparison"],
        "latest_corrected_parameters": corrected_fits[-1]["parameters"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
