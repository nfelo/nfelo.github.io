#!/usr/bin/env python3
"""Causal forecast-layer comparisons using captured NFELO pre-match states."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize, minimize_scalar


EPS = 1e-15
BLOCKS = ((1960, 1979), (1980, 1999), (2000, 2009), (2010, 2019), (2020, 2026))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("components", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def log_loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    return float(-np.log(np.maximum(probabilities[np.arange(len(outcomes)), outcomes], EPS)).mean())


def metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float | int]:
    one_hot = np.eye(3, dtype=np.float64)[outcomes]
    cumulative_error = np.cumsum(probabilities, axis=1)[:, :2] - np.cumsum(one_hot, axis=1)[:, :2]
    return {
        "matches": int(len(outcomes)),
        "log_loss": log_loss(probabilities, outcomes),
        "brier": float(np.square(probabilities - one_hot).sum(axis=1).mean()),
        "rps": float(0.5 * np.square(cumulative_error).sum(axis=1).mean()),
        "accuracy": float((probabilities.argmax(axis=1) == outcomes).mean()),
    }


def score_calibration(
    raw: np.ndarray, friendly: np.ndarray, draw_tilt: float, friendly_power: float, competitive_power: float
) -> np.ndarray:
    values = np.maximum(np.asarray(raw, dtype=np.float64), EPS).copy()
    values[:, 1] *= math.exp(float(draw_tilt))
    values /= values.sum(axis=1, keepdims=True)
    powers = np.where(friendly, friendly_power, competitive_power)
    values = np.power(values, powers[:, None])
    return values / values.sum(axis=1, keepdims=True)


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def symmetric_coordinates(probabilities: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.maximum(probabilities, EPS)
    strength = 0.5 * np.log(values[:, 0] / values[:, 2])
    draw = np.log(values[:, 1] / np.sqrt(values[:, 0] * values[:, 2]))
    return strength, draw


def symmetric_stack(
    network: np.ndarray, score: np.ndarray, friendly: np.ndarray, parameters: np.ndarray
) -> np.ndarray:
    ns, nd = symmetric_coordinates(network)
    ss, sd = symmetric_coordinates(score)
    flag = friendly.astype(np.float64)
    # Swap invariance is exact: swapping teams negates only the strength coordinate.
    strength = (
        parameters[0] * ns
        + parameters[1] * ss
        + flag * (parameters[2] * ns + parameters[3] * ss)
    )
    draw = parameters[4] + parameters[5] * nd + parameters[6] * sd + parameters[7] * flag
    return softmax(np.column_stack((strength, draw, -strength)))


def release_index(year: int) -> int:
    if year <= 1979:
        return 0
    if year <= 1999:
        return 1
    if year <= 2009:
        return 2
    if year <= 2019:
        return 3
    return 4


def fit_predict_year(
    method: str,
    year: int,
    window: int,
    years: np.ndarray,
    network: np.ndarray,
    score_states: np.ndarray,
    friendly: np.ndarray,
    outcomes: np.ndarray,
) -> tuple[np.ndarray, dict[str, object]]:
    state = release_index(year)
    train = (years >= year - window) & (years <= year - 1)
    test = years == year
    n_train = network[train]
    s_train = score_states[train, state]
    f_train = friendly[train]
    y_train = outcomes[train]
    n_test = network[test]
    s_test = score_states[test, state]
    f_test = friendly[test]

    if len(y_train) < 500:
        raise RuntimeError(f"only {len(y_train)} training matches for {year}")

    if method == "sequential_linear":
        fitted = minimize(
            lambda x: log_loss(score_calibration(s_train, f_train, *x), y_train),
            np.asarray((0.10, 0.95, 1.05)),
            method="Powell",
            bounds=((-0.35, 0.35), (0.75, 1.30), (0.75, 1.30)),
            options={"maxiter": 64, "xtol": 1e-7, "ftol": 1e-12},
        )
        calibrated_train = score_calibration(s_train, f_train, *fitted.x)
        weight = minimize_scalar(
            lambda w: log_loss(w * n_train + (1.0 - w) * calibrated_train, y_train),
            bounds=(0.0, 1.0),
            method="bounded",
            options={"xatol": 1e-10},
        ).x
        prediction = weight * n_test + (1.0 - weight) * score_calibration(s_test, f_test, *fitted.x)
        detail: dict[str, object] = {"calibration": fitted.x.tolist(), "network_weight": float(weight)}

    elif method in {"joint_linear", "joint_linear_class"}:
        class_weight = method.endswith("_class")
        size = 5 if class_weight else 4
        initial = np.asarray((0.10, 0.95, 1.05, 0.65, 0.65)[:size], dtype=np.float64)
        bounds = ((-0.50, 0.50), (0.60, 1.50), (0.60, 1.50), (0.0, 1.0))
        if class_weight:
            bounds += ((0.0, 1.0),)

        def predict(values: np.ndarray, n: np.ndarray, s: np.ndarray, f: np.ndarray) -> np.ndarray:
            calibrated = score_calibration(s, f, *values[:3])
            weights = np.where(f, values[3], values[4]) if class_weight else np.full(len(f), values[3])
            return weights[:, None] * n + (1.0 - weights[:, None]) * calibrated

        fitted = minimize(
            lambda x: log_loss(predict(x, n_train, s_train, f_train), y_train),
            initial,
            method="Nelder-Mead",
            bounds=bounds,
            options={"maxiter": 1200, "xatol": 1e-8, "fatol": 1e-11},
        )
        prediction = predict(fitted.x, n_test, s_test, f_test)
        detail = {"parameters": fitted.x.tolist(), "training_loss": float(fitted.fun)}

    elif method == "log_pool_class":
        initial = np.asarray((0.10, 0.95, 1.05, 0.65, 0.65), dtype=np.float64)
        bounds = ((-0.50, 0.50), (0.60, 1.50), (0.60, 1.50), (0.0, 1.0), (0.0, 1.0))

        def predict(values: np.ndarray, n: np.ndarray, s: np.ndarray, f: np.ndarray) -> np.ndarray:
            calibrated = score_calibration(s, f, *values[:3])
            weights = np.where(f, values[3], values[4])
            pooled = np.power(np.maximum(n, EPS), weights[:, None]) * np.power(
                np.maximum(calibrated, EPS), 1.0 - weights[:, None]
            )
            return pooled / pooled.sum(axis=1, keepdims=True)

        fitted = minimize(
            lambda x: log_loss(predict(x, n_train, s_train, f_train), y_train),
            initial,
            method="Nelder-Mead",
            bounds=bounds,
            options={"maxiter": 1200, "xatol": 1e-8, "fatol": 1e-11},
        )
        prediction = predict(fitted.x, n_test, s_test, f_test)
        detail = {"parameters": fitted.x.tolist(), "training_loss": float(fitted.fun)}

    elif method == "symmetric_stack":
        initial = np.asarray((1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0), dtype=np.float64)
        centre = initial.copy()

        def objective(values: np.ndarray) -> float:
            penalty = 2e-5 * float(np.square(values - centre).sum())
            return log_loss(symmetric_stack(n_train, s_train, f_train, values), y_train) + penalty

        fitted = minimize(
            objective,
            initial,
            method="L-BFGS-B",
            bounds=((0.0, 2.0), (-1.0, 2.0), (-1.0, 1.0), (-1.0, 1.0), (-1.5, 1.5),
                    (-1.0, 2.0), (-1.0, 2.0), (-1.0, 1.0)),
            options={"maxiter": 500, "ftol": 1e-14, "gtol": 1e-8},
        )
        prediction = symmetric_stack(n_test, s_test, f_test, fitted.x)
        detail = {"parameters": fitted.x.tolist(), "training_loss_penalized": float(fitted.fun)}
    else:
        raise ValueError(method)

    return prediction / prediction.sum(axis=1, keepdims=True), detail


def annual_model(
    method: str,
    window: int,
    years: np.ndarray,
    network: np.ndarray,
    score_states: np.ndarray,
    friendly: np.ndarray,
    outcomes: np.ndarray,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    prediction = np.full_like(network, np.nan)
    details: list[dict[str, object]] = []
    for year in range(1960, 2027):
        values, detail = fit_predict_year(
            method, year, window, years, network, score_states, friendly, outcomes
        )
        prediction[years == year] = values
        details.append({"year": year, **detail})
    return prediction, details


def bootstrap_year_difference(
    first: np.ndarray,
    second: np.ndarray,
    outcomes: np.ndarray,
    years: np.ndarray,
    draws: int = 20_000,
) -> dict[str, float | int]:
    losses = -np.log(np.maximum(first[np.arange(len(outcomes)), outcomes], EPS)) + np.log(
        np.maximum(second[np.arange(len(outcomes)), outcomes], EPS)
    )
    unique = np.unique(years)
    sums = np.asarray([losses[years == year].sum() for year in unique])
    counts = np.asarray([(years == year).sum() for year in unique])
    rng = np.random.default_rng(20260719)
    sampled = rng.integers(0, len(unique), size=(draws, len(unique)))
    differences = sums[sampled].sum(axis=1) / counts[sampled].sum(axis=1)
    return {
        "candidate_minus_reference": float(losses.mean()),
        "ci95_lower": float(np.quantile(differences, 0.025)),
        "ci95_upper": float(np.quantile(differences, 0.975)),
        "bootstrap_probability_candidate_better": float((differences < 0).mean()),
        "draws": draws,
        "year_clusters": int(len(unique)),
    }


def main() -> None:
    args = parse_args()
    source = np.load(args.components)
    all_years = source["year"].astype(int)
    cutoff = (all_years >= 1960) & (source["date"] <= "2026-07-11")
    years = all_years
    outcomes = source["outcome"].astype(int)
    network = source["network"]
    score_states = source["all_score_raw"]
    friendly = source["friendly"].astype(bool)

    predictions: dict[str, np.ndarray] = {
        "network_deployed_replay": network,
        "score_layer_deployed_gated": source["final"],
        "score_layer_deployed_ungated": source["ungated"],
    }
    fit_details: dict[str, object] = {}
    for window in (4, 8, 12, 20):
        for method in ("sequential_linear", "joint_linear_class", "log_pool_class", "symmetric_stack"):
            name = f"{method}_w{window}"
            predictions[name], fit_details[name] = annual_model(
                method, window, years, network, score_states, friendly, outcomes
            )

    results: dict[str, object] = {
        "scope": {
            "matches": int(cutoff.sum()),
            "first_year": 1960,
            "last_date": "2026-07-11",
            "note": "All annual transforms use prior complete calendar years only. Core deployed network constants remain a retrospective replay.",
        },
        "models": {},
        "gate": {},
        "score_state_grid": {},
        "comparisons": {},
        "fit_details": fit_details,
    }
    for name, values in predictions.items():
        selected = values[cutoff]
        if not np.all(np.isfinite(selected)):
            raise RuntimeError(f"non-finite probabilities for {name}")
        model_result: dict[str, object] = {"aggregate": metrics(selected, outcomes[cutoff]), "blocks": {}}
        for first, last in BLOCKS:
            block = cutoff & (years >= first) & (years <= last)
            model_result["blocks"][f"{first}-{last}"] = metrics(values[block], outcomes[block])
        results["models"][name] = model_result

    reverted = cutoff & source["reverted"].astype(bool)
    results["gate"] = {
        "reversions": int(reverted.sum()),
        "share": float(reverted.sum() / cutoff.sum()),
        "gated_on_reverted": metrics(source["final"][reverted], outcomes[reverted]),
        "ungated_on_reverted": metrics(source["ungated"][reverted], outcomes[reverted]),
    }

    for state, state_name in enumerate(source["score_state_names"].tolist()):
        state_predictions = np.full_like(network, np.nan)
        for year in range(1960, 2027):
            train = (years >= year - 8) & (years <= year - 1)
            test = years == year
            raw_train = score_states[train, state]
            raw_test = score_states[test, state]
            f_train = friendly[train]
            y_train = outcomes[train]
            fitted = minimize(
                lambda x: log_loss(score_calibration(raw_train, f_train, *x), y_train),
                np.asarray((0.10, 0.95, 1.05)), method="Powell",
                bounds=((-0.35, 0.35), (0.75, 1.30), (0.75, 1.30)),
                options={"maxiter": 64, "xtol": 1e-7, "ftol": 1e-12},
            )
            calibrated_train = score_calibration(raw_train, f_train, *fitted.x)
            weight = minimize_scalar(
                lambda w: log_loss(w * network[train] + (1.0 - w) * calibrated_train, y_train),
                bounds=(0.0, 1.0), method="bounded",
            ).x
            state_predictions[test] = weight * network[test] + (1.0 - weight) * score_calibration(
                raw_test, friendly[test], *fitted.x
            )
        state_result: dict[str, object] = {"aggregate": metrics(state_predictions[cutoff], outcomes[cutoff]), "blocks": {}}
        for first, last in BLOCKS:
            block = cutoff & (years >= first) & (years <= last)
            state_result["blocks"][f"{first}-{last}"] = metrics(state_predictions[block], outcomes[block])
        results["score_state_grid"][state_name] = state_result

    candidates = {
        name: values for name, values in predictions.items()
        if name not in {"network_deployed_replay", "score_layer_deployed_gated"}
    }
    best_name = min(candidates, key=lambda name: log_loss(candidates[name][cutoff], outcomes[cutoff]))
    results["best_diagnostic_model"] = best_name
    results["comparisons"][f"{best_name}_vs_deployed_gated"] = bootstrap_year_difference(
        predictions[best_name][cutoff], source["final"][cutoff], outcomes[cutoff], years[cutoff]
    )
    results["comparisons"]["deployed_ungated_vs_gated"] = bootstrap_year_difference(
        source["ungated"][cutoff], source["final"][cutoff], outcomes[cutoff], years[cutoff]
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "best": best_name,
        "best_metrics": results["models"][best_name]["aggregate"],
        "deployed": results["models"]["score_layer_deployed_gated"]["aggregate"],
        "network": results["models"]["network_deployed_replay"]["aggregate"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
