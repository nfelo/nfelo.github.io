#!/usr/bin/env python3
"""Causal, time-varying country home-dependence estimates.

The ledger overwhelmingly records a host as team one, so independent host
and visitor effects are not cleanly identifiable.  The audited model instead
learns one country value: half applies when that country hosts and half when
it visits.  Neutral matches receive neither an effect nor a learning update.
"""

from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


LN10_OVER_400 = math.log(10.0) / 400.0
MODEL_DAYS_PER_YEAR = 400.0


class VenueEffects:
    """Independent hierarchical venue states with causal same-day updates."""

    def __init__(self, count: int, configuration: dict[str, Any]) -> None:
        self.count = count
        self.version = str(configuration["version"])
        self.prior_sd = float(configuration["prior_sd"])
        self.prior_variance = self.prior_sd**2
        self.half_life_years = float(configuration["half_life_years"])
        self.home_share = float(configuration["home_share"])
        self.away_share = float(configuration["away_share"])
        self.friendly_learning_ratio = float(
            configuration["friendly_learning_ratio"]
        )
        self.competitive_learning_ratio = float(
            configuration["competitive_learning_ratio"]
        )
        self.neutral_effect = float(configuration["neutral_effect"])
        self.predictive_variance_scale = float(
            configuration.get("predictive_variance_scale", 0.0)
        )
        self.selection_rule = str(configuration["selection_rule"])
        self.validation = dict(configuration.get("validation", {}))
        if self.prior_sd <= 0.0 or self.half_life_years <= 0.0:
            raise ValueError("Venue prior and half-life must be positive")
        if not math.isclose(
            self.home_share + self.away_share,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("Venue home and away shares must sum to one")
        if self.neutral_effect != 0.0:
            raise ValueError("The audited neutral-site effect must remain zero")
        if self.predictive_variance_scale < 0.0:
            raise ValueError("Venue predictive-variance scale cannot be negative")

        self.mean = np.zeros(count, dtype=np.float64)
        self.variance = np.full(
            count,
            self.prior_variance,
            dtype=np.float64,
        )
        self.last_day = np.full(count, -1, dtype=np.int32)
        self.matches = np.zeros(count, dtype=np.int32)

    @classmethod
    def from_path(cls, count: int, path: Path) -> VenueEffects:
        return cls(count, json.loads(path.read_text(encoding="utf-8")))

    def _project_values(self, index: int, day: int) -> tuple[float, float]:
        previous = int(self.last_day[index])
        if previous < 0 or day <= previous:
            return float(self.mean[index]), float(self.variance[index])
        elapsed = (day - previous) / MODEL_DAYS_PER_YEAR
        retention = math.exp(
            -math.log(2.0) * elapsed / self.half_life_years
        )
        mean = float(self.mean[index]) * retention
        variance = self.prior_variance - (
            self.prior_variance - float(self.variance[index])
        ) * retention**2
        return mean, variance

    def advance(self, index: int, day: int) -> None:
        mean, variance = self._project_values(index, day)
        self.mean[index] = mean
        self.variance[index] = variance
        self.last_day[index] = day

    def advance_many(self, indices: Iterable[int], day: int) -> None:
        for index in sorted(set(indices)):
            self.advance(index, day)

    def correction(
        self,
        first: int,
        second: int,
        home_sign: int,
        *,
        day: int | None = None,
    ) -> float:
        if home_sign == 0:
            return self.neutral_effect
        if home_sign not in (-1, 1):
            raise ValueError(f"Invalid home sign: {home_sign}")
        if day is None:
            first_mean = float(self.mean[first])
            second_mean = float(self.mean[second])
        else:
            first_mean = self._project_values(first, day)[0]
            second_mean = self._project_values(second, day)[0]
        # Both participants contribute to dependence on home conditions.  The
        # sign changes when the source's team order is reversed.
        return float(home_sign) * (
            self.home_share * first_mean
            + self.away_share * second_mean
        )

    def predictive_variance(
        self,
        first: int,
        second: int,
        home_sign: int,
        *,
        day: int | None = None,
    ) -> float:
        if home_sign == 0 or self.predictive_variance_scale == 0.0:
            return 0.0
        if day is None:
            first_variance = float(self.variance[first])
            second_variance = float(self.variance[second])
        else:
            first_variance = self._project_values(first, day)[1]
            second_variance = self._project_values(second, day)[1]
        return self.predictive_variance_scale * (
            self.home_share**2 * first_variance
            + self.away_share**2 * second_variance
        )

    def update_day(self, observations: Iterable[dict[str, Any]]) -> None:
        """Update after all forecasts on a date have been frozen."""
        gradient: defaultdict[int, float] = defaultdict(float)
        curvature: defaultdict[int, float] = defaultdict(float)
        appearances: defaultdict[int, int] = defaultdict(int)
        for row in observations:
            home_sign = int(row["home_sign"])
            if home_sign == 0:
                continue
            weight = (
                self.friendly_learning_ratio
                if bool(row["friendly"])
                else self.competitive_learning_ratio
            )
            residual = float(row["result"]) - float(row["expected"])
            information = max(
                1e-8,
                float(row["expected"]) * (1.0 - float(row["expected"])),
            )
            for index, share in (
                (int(row["first"]), self.home_share),
                (int(row["second"]), self.away_share),
            ):
                coefficient = float(home_sign) * share
                gradient[index] += (
                    weight * LN10_OVER_400 * residual * coefficient
                )
                curvature[index] += (
                    weight
                    * LN10_OVER_400**2
                    * information
                    * coefficient**2
                )
                appearances[index] += 1
        for index, score in gradient.items():
            precision = 1.0 / max(float(self.variance[index]), 1e-12)
            updated_precision = precision + curvature[index]
            self.mean[index] += score / updated_precision
            self.variance[index] = 1.0 / updated_precision
            self.matches[index] += appearances[index]

    def record(self, index: int, day: int) -> dict[str, float | int | str]:
        mean, variance = self._project_values(index, day)
        standard_error = math.sqrt(max(0.0, variance))
        reliability = max(
            0.0,
            min(1.0, 1.0 - variance / self.prior_variance),
        )
        return {
            "dependence": mean,
            "se": standard_error,
            "hosting_adjustment": self.home_share * mean,
            "away_adjustment": -self.away_share * mean,
            "away_disadvantage": self.away_share * mean,
            "neutral": self.neutral_effect,
            "reliability": reliability,
            "matches": int(self.matches[index]),
            "as_of_day": day,
        }

    def export(self, day: int) -> dict[str, Any]:
        return {
            "version": self.version,
            "prior_sd": self.prior_sd,
            "half_life_years": self.half_life_years,
            "home_share": self.home_share,
            "away_share": self.away_share,
            "friendly_learning_ratio": self.friendly_learning_ratio,
            "competitive_learning_ratio": self.competitive_learning_ratio,
            "neutral_effect": self.neutral_effect,
            "predictive_variance_scale": self.predictive_variance_scale,
            "selection_rule": self.selection_rule,
            "validation": self.validation,
            # Raw posterior states are retained so future fixtures can apply
            # exactly one interval of mean reversion from each team's own
            # latest venue-state date.
            "means": self.mean.tolist(),
            "variances": self.variance.tolist(),
            "last_day": self.last_day.tolist(),
            "matches": self.matches.tolist(),
            "as_of_day": day,
        }
