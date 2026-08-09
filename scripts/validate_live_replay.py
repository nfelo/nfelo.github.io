#!/usr/bin/env python3
"""Validate a rebuilt site against the frozen retrospective audit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any


METHODOLOGY_VERSION = "2026-07-27-country-home-dependence"
FRIENDLY_INFORMATION_RATIO = "0.78621"
FORECAST_TEMPERATURES = {
    "friendly": "0.896294991479",
    "competitive": "1.061356232973",
}
LIVE_SOURCE_TOLERANCES = {
    "log_loss": 0.002,
    "network_only_log_loss": 0.002,
    "brier": 0.002,
    "rps": 0.001,
    "accuracy": 0.01,
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_live_replay(
    summary: dict[str, Any],
    research: dict[str, Any],
    *,
    source_status: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return diagnostics when the live replay remains within the audit contract."""

    _require(
        summary["meta"]["methodology_version"] == METHODOLOGY_VERSION,
        "The frozen methodology version changed",
    )
    _require(
        summary["parameters"]["network"]["friendly_information_ratio_exact"]
        == FRIENDLY_INFORMATION_RATIO,
        "The frozen friendly information ratio changed",
    )
    _require(
        summary["parameters"]["forecast_temperature_exact"]
        == FORECAST_TEMPERATURES,
        "The frozen forecast temperatures changed",
    )

    replay = summary["validation"]["retrospective"]
    selected = research["end_to_end"]["selected"]
    _require(
        replay["cutoff"] == research["audit_cutoff"],
        "The retrospective audit cutoff changed",
    )

    frozen_matches = int(research["scored_matches"])
    live_matches = int(replay["matches"])
    drift = live_matches - frozen_matches
    allowed_match_drift = max(25, frozen_matches // 100)
    _require(
        abs(drift) <= allowed_match_drift,
        (
            "Historical sample drift is too large: "
            f"{live_matches} vs {frozen_matches} "
            f"(allowed ±{allowed_match_drift})"
        ),
    )

    expected_keys = {
        "log_loss": "log_loss",
        "network_only_log_loss": "network_log_loss",
        "brier": "brier",
        "rps": "rps",
        "accuracy": "accuracy",
    }
    metric_deltas: dict[str, float] = {}
    for actual_key, expected_key in expected_keys.items():
        actual = float(replay[actual_key])
        expected = float(selected[expected_key])
        tolerance = LIVE_SOURCE_TOLERANCES[actual_key]
        _require(math.isfinite(actual), f"{actual_key} is not finite")
        _require(
            math.isclose(actual, expected, abs_tol=tolerance, rel_tol=0.0),
            (
                f"{actual_key} moved outside the live-source tolerance: "
                f"actual={actual:.12f} expected={expected:.12f} "
                f"tolerance={tolerance:.12f}"
            ),
        )
        metric_deltas[actual_key] = actual - expected

    _require(
        float(replay["log_loss"]) < float(replay["network_only_log_loss"]),
        "Forecast layer no longer improves on the network-only probabilities",
    )
    _require(
        float(replay["log_loss"])
        < float(research["end_to_end"]["baseline"]["log_loss"]),
        "Forecast layer no longer improves on the frozen public-rating baseline",
    )

    if source_status is not None:
        unresolved = list(source_status.get("unresolved_names", []))
        unresolved.extend(
            source_status.get("base_snapshot", {}).get(
                "unresolved_world_names", []
            )
        )
        _require(not unresolved, f"Unresolved source names: {unresolved}")

        checked_at = datetime.fromisoformat(source_status["source_checked_at"])
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        current_time = now or datetime.now(timezone.utc)
        _require(
            (current_time - checked_at).total_seconds() <= 3600,
            (
                "Refreshed source status is unexpectedly stale: "
                f"{checked_at.isoformat()}"
            ),
        )

    return {
        "frozen_matches": frozen_matches,
        "live_matches": live_matches,
        "historical_correction_drift": drift,
        "allowed_match_drift": allowed_match_drift,
        "metrics": {key: float(replay[key]) for key in expected_keys},
        "metric_deltas": metric_deltas,
        "metric_tolerances": LIVE_SOURCE_TOLERANCES,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--research", type=Path, required=True)
    parser.add_argument("--source-status", type=Path)
    arguments = parser.parse_args()

    diagnostics = validate_live_replay(
        _load_json(arguments.summary),
        _load_json(arguments.research),
        source_status=(
            _load_json(arguments.source_status)
            if arguments.source_status is not None
            else None
        ),
    )
    print(json.dumps(diagnostics, sort_keys=True))


if __name__ == "__main__":
    main()
