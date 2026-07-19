#!/usr/bin/env python3
"""Compare the deployed all-or-nothing pick gate with a boundary-preserving pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


EPS = 1e-15


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


def boundary_pool(network: np.ndarray, ungated: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Move toward the pooled forecast until just before the network pick changes."""
    result = ungated.copy()
    fraction = np.ones(len(network), dtype=float)
    for row in range(len(network)):
        winner = int(np.argmax(network[row]))
        delta = ungated[row] - network[row]
        limit = 1.0
        for competitor in range(3):
            if competitor == winner:
                continue
            closing = delta[competitor] - delta[winner]
            if closing > 0.0:
                limit = min(limit, (network[row, winner] - network[row, competitor]) / closing)
        if limit < 1.0:
            # Stay infinitesimally inside the original argmax region, avoiding
            # dependence on library-specific tie-breaking.
            fraction[row] = max(0.0, limit * (1.0 - 1e-10))
            result[row] = network[row] + fraction[row] * delta
            result[row] /= result[row].sum()
    return result, fraction


def bootstrap_difference(
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
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("components", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = np.load(args.components)
    cutoff = (source["year"].astype(int) >= 1960) & (source["date"] <= "2026-07-11")
    network = source["network"][cutoff]
    ungated = source["ungated"][cutoff]
    gated = source["final"][cutoff]
    outcomes = source["outcome"][cutoff].astype(int)
    years = source["year"][cutoff].astype(int)
    boundary, fraction = boundary_pool(network, ungated)
    changed = ungated.argmax(axis=1) != network.argmax(axis=1)
    payload = {
        "models": {
            "network": metrics(network, outcomes),
            "ungated": metrics(ungated, outcomes),
            "full_reversion_gate": metrics(gated, outcomes),
            "boundary_gate": metrics(boundary, outcomes),
        },
        "changed_pick_rows": int(changed.sum()),
        "boundary_fraction_on_changed": {
            "mean": float(fraction[changed].mean()),
            "median": float(np.median(fraction[changed])),
            "minimum": float(fraction[changed].min()),
            "maximum": float(fraction[changed].max()),
        },
        "comparisons": {
            "boundary_vs_full_reversion": bootstrap_difference(boundary, gated, outcomes, years),
            "ungated_vs_full_reversion": bootstrap_difference(ungated, gated, outcomes, years),
        },
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
