#!/usr/bin/env python3
"""Deterministic full-covariance Monte Carlo tournament simulations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
from scipy.stats import skellam


EPSILON = 1e-15


class SimulationError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def model_day(value: str) -> int:
    year, month, day = (int(item) for item in value.split("-"))
    return year * 400 + month * 32 + day


def logistic10(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.power(10.0, -value / 400.0))


def stable_covariance_root(covariance: np.ndarray) -> np.ndarray:
    covariance = 0.5 * (covariance + covariance.T)
    values, vectors = np.linalg.eigh(covariance)
    tolerance = max(1.0, float(np.max(np.abs(values)))) * 1e-10
    if float(np.min(values)) < -tolerance:
        raise SimulationError(f"Tournament covariance is not positive semidefinite: {np.min(values)}")
    return vectors @ np.diag(np.sqrt(np.maximum(values, 0.0)))


def pooled_probabilities(
    network: np.ndarray,
    score: np.ndarray,
    nfelo_weight: float,
) -> np.ndarray:
    candidate = nfelo_weight * network + (1.0 - nfelo_weight) * score
    candidate /= candidate.sum(axis=1, keepdims=True)
    winners = np.argmax(network, axis=1)
    changed = np.argmax(candidate, axis=1) != winners
    if not np.any(changed):
        return candidate
    delta = candidate - network
    fraction = np.ones(len(network), dtype=np.float64)
    rows = np.arange(len(network))
    for competitor in range(3):
        mask = changed & (winners != competitor)
        if not np.any(mask):
            continue
        closing = delta[rows, competitor] - delta[rows, winners]
        eligible = mask & (closing > 0.0)
        if np.any(eligible):
            limit = (
                network[rows, winners] - network[:, competitor]
            ) / np.maximum(closing, EPSILON)
            fraction[eligible] = np.minimum(fraction[eligible], limit[eligible])
    fraction = np.clip(fraction * (1.0 - 1e-10), 0.0, 1.0)
    result = network + fraction[:, None] * delta
    result = np.maximum(result, EPSILON)
    return result / result.sum(axis=1, keepdims=True)


def rounded_tenths(wins: np.ndarray, codes: list[str]) -> dict[str, float]:
    if int(wins.sum()) <= 0:
        raise SimulationError("Tournament simulation produced no champions")
    exact = wins.astype(np.float64) * 1000.0 / float(wins.sum())
    units = np.floor(exact).astype(np.int64)
    remaining = 1000 - int(units.sum())
    order = sorted(
        range(len(codes)),
        key=lambda index: (-(exact[index] - units[index]), codes[index]),
    )
    for index in order[:remaining]:
        units[index] += 1
    if int(units.sum()) != 1000:
        raise SimulationError("Rounded title chances do not sum to 100.0%")
    return {code: float(units[index]) / 10.0 for index, code in enumerate(codes)}


@dataclass(slots=True)
class MatchDraw:
    probabilities: np.ndarray
    lambda1: np.ndarray
    lambda2: np.ndarray


class TournamentSimulator:
    def __init__(
        self,
        entry: dict[str, Any],
        state: dict[str, Any],
        trials: int,
        seed: int,
    ) -> None:
        self.entry = entry
        self.rules = entry["rules"]
        self.codes = list(state["codes"])
        if set(self.codes) != set(entry["participants"]):
            raise SimulationError("Captured state and format participants differ")
        self.index = {code: index for index, code in enumerate(self.codes)}
        self.trials = int(trials)
        self.rng = np.random.default_rng(seed)
        count = len(self.codes)
        means = np.asarray(state["means"], dtype=np.float64)
        covariance = np.asarray(state["covariance"], dtype=np.float64).reshape(count, count)
        root = stable_covariance_root(covariance)
        self.strength = means[None, :] + self.rng.standard_normal((trials, count)) @ root.T

        venue = state["venue_effects"]
        venue_means = np.asarray(venue["means"], dtype=np.float64)
        venue_scale = float(venue.get("predictive_variance_scale", 0.0))
        venue_sd = np.sqrt(
            np.maximum(0.0, venue_scale * np.asarray(venue["variances"], dtype=np.float64))
        )
        self.venue = venue_means[None, :] + self.rng.standard_normal((trials, count)) * venue_sd[None, :]
        self.home_share = float(venue["home_share"])
        self.away_share = float(venue["away_share"])

        self.scale = float(state["scale"])
        self.home = float(state["home"])
        self.draw = float(state["draw"])
        score = state["forecast_layer"]
        self.attack = np.asarray(score["attack"], dtype=np.float64)
        self.defence = np.asarray(score["defence"], dtype=np.float64)
        self.score_last_day = np.asarray(score["last_day"], dtype=np.int64)
        self.gap_scale = float(score["parameters"]["gap_scale"])
        self.annual_decay = float(score["parameters"]["annual_decay"])
        self.base_goal = float(score["base_goal"])
        self.calibration = score["calibration"]
        self.start = str(entry["start"])

        self.points = np.zeros((trials, count), dtype=np.int16)
        self.goals_for = np.zeros((trials, count), dtype=np.int16)
        self.goals_against = np.zeros((trials, count), dtype=np.int16)
        self.wins = np.zeros((trials, count), dtype=np.int8)
        self.group_records: dict[str, list[tuple[int, int, np.ndarray, np.ndarray]]] = {
            str(group["name"]): [] for group in self.rules["groups"]
        }

    def score_state(self, index: int, day: int) -> tuple[float, float]:
        previous = int(self.score_last_day[index])
        elapsed = 0.0 if previous < 0 else max(0.0, (day - previous) / 400.0)
        retention = math.exp(-self.annual_decay * elapsed)
        return self.attack[index] * retention, self.defence[index] * retention

    def distribution(
        self,
        first: np.ndarray,
        second: np.ndarray,
        day_text: str,
        home_sign: int | np.ndarray,
        *,
        duration: float = 1.0,
    ) -> MatchDraw:
        rows = np.arange(self.trials)
        difference = self.scale * (
            self.strength[rows, first] - self.strength[rows, second]
        )
        home_values = np.asarray(home_sign, dtype=np.float64)
        if np.any(home_values):
            difference += self.home * home_values
            difference += home_values * (
                self.home_share * self.venue[rows, first]
                + self.away_share * self.venue[rows, second]
            )
        expected = logistic10(difference)
        draws = self.draw * 4.0 * expected * (1.0 - expected)
        network = np.column_stack((
            expected - 0.5 * draws,
            draws,
            1.0 - expected - 0.5 * draws,
        ))
        temperature = float(self.calibration["competitive_temperature"])
        network = np.power(np.maximum(network, EPSILON), temperature)
        network /= network.sum(axis=1, keepdims=True)

        day = model_day(day_text)
        first_previous = self.score_last_day[first]
        second_previous = self.score_last_day[second]
        first_elapsed = np.where(
            first_previous < 0,
            0.0,
            np.maximum(0.0, (day - first_previous) / 400.0),
        )
        second_elapsed = np.where(
            second_previous < 0,
            0.0,
            np.maximum(0.0, (day - second_previous) / 400.0),
        )
        first_retention = np.exp(-self.annual_decay * first_elapsed)
        second_retention = np.exp(-self.annual_decay * second_elapsed)
        attack1 = self.attack[first] * first_retention
        attack2 = self.attack[second] * second_retention
        defence1 = self.defence[first] * first_retention
        defence2 = self.defence[second] * second_retention
        expected = np.clip(expected, 1e-8, 1.0 - 1e-8)
        gap = 0.5 * self.gap_scale * np.log(expected / (1.0 - expected))
        lambda1 = np.clip(
            np.exp(math.log(self.base_goal * duration) + gap + attack1 - defence2),
            0.05 * duration,
            8.0 * duration,
        )
        lambda2 = np.clip(
            np.exp(math.log(self.base_goal * duration) - gap + attack2 - defence1),
            0.05 * duration,
            8.0 * duration,
        )
        score_draw = skellam.pmf(0, lambda1, lambda2)
        score_loss = skellam.cdf(-1, lambda1, lambda2)
        score_win = np.maximum(EPSILON, 1.0 - score_draw - score_loss)
        score = np.column_stack((score_win, score_draw, score_loss))
        score[:, 1] *= math.exp(float(np.clip(self.calibration["draw_log_tilt"], -3.0, 3.0)))
        score /= score.sum(axis=1, keepdims=True)
        score = np.power(np.maximum(score, EPSILON), temperature)
        score /= score.sum(axis=1, keepdims=True)
        final = pooled_probabilities(network, score, float(self.calibration["nfelo_weight"]))
        return MatchDraw(final, lambda1, lambda2)

    def outcomes(self, probabilities: np.ndarray) -> np.ndarray:
        values = self.rng.random(self.trials)
        first = probabilities[:, 0]
        return np.where(values < first, 0, np.where(values < first + probabilities[:, 1], 1, 2))

    def conditional_scores(self, draw: MatchDraw) -> tuple[np.ndarray, np.ndarray]:
        wanted = self.outcomes(draw.probabilities)
        first = np.zeros(self.trials, dtype=np.int16)
        second = np.zeros(self.trials, dtype=np.int16)
        pending = np.ones(self.trials, dtype=bool)
        for _ in range(80):
            indices = np.flatnonzero(pending)
            if not len(indices):
                break
            sample1 = self.rng.poisson(draw.lambda1[indices])
            sample2 = self.rng.poisson(draw.lambda2[indices])
            observed = np.where(sample1 > sample2, 0, np.where(sample1 == sample2, 1, 2))
            accepted = observed == wanted[indices]
            chosen = indices[accepted]
            first[chosen] = sample1[accepted]
            second[chosen] = sample2[accepted]
            pending[chosen] = False
        if np.any(pending):
            # Only an astronomically thin rejection tail reaches this guard.
            first[pending & (wanted == 0)] = 1
            second[pending & (wanted == 2)] = 1
        return first, second

    def play_groups(self) -> None:
        rows = np.arange(self.trials)
        for fixture in self.rules["group_fixtures"]:
            first_index = self.index[str(fixture["team1"])]
            second_index = self.index[str(fixture["team2"])]
            first = np.full(self.trials, first_index, dtype=np.int16)
            second = np.full(self.trials, second_index, dtype=np.int16)
            match = self.distribution(first, second, str(fixture["date"]), int(fixture["home"]))
            goals1, goals2 = self.conditional_scores(match)
            first_won = goals1 > goals2
            second_won = goals2 > goals1
            tied = goals1 == goals2
            self.points[rows, first] += first_won * 3 + tied
            self.points[rows, second] += second_won * 3 + tied
            self.goals_for[rows, first] += goals1
            self.goals_against[rows, first] += goals2
            self.goals_for[rows, second] += goals2
            self.goals_against[rows, second] += goals1
            self.wins[rows, first] += first_won
            self.wins[rows, second] += second_won
            self.group_records[str(fixture["group"])].append(
                (first_index, second_index, goals1, goals2)
            )

    def head_to_head(self, group: str, trial: int, tied: set[int]) -> dict[int, tuple[int, int, int]]:
        points = {team: 0 for team in tied}
        goal_difference = {team: 0 for team in tied}
        goals = {team: 0 for team in tied}
        for first, second, goals1, goals2 in self.group_records[group]:
            if first not in tied or second not in tied:
                continue
            first_goals = int(goals1[trial])
            second_goals = int(goals2[trial])
            if first_goals > second_goals:
                points[first] += 3
            elif first_goals < second_goals:
                points[second] += 3
            else:
                points[first] += 1
                points[second] += 1
            goal_difference[first] += first_goals - second_goals
            goal_difference[second] += second_goals - first_goals
            goals[first] += first_goals
            goals[second] += second_goals
        return {team: (points[team], goal_difference[team], goals[team]) for team in tied}

    def rank_group(self, group: dict[str, Any]) -> np.ndarray:
        members = [self.index[str(code)] for code in group["teams"]]
        result = np.empty((self.trials, len(members)), dtype=np.int16)
        policy = str(self.rules["tie_break"])
        random_keys = self.rng.random((self.trials, len(members)))
        for trial in range(self.trials):
            overall = {
                team: (
                    int(self.points[trial, team]),
                    int(self.goals_for[trial, team] - self.goals_against[trial, team]),
                    int(self.goals_for[trial, team]),
                    int(self.wins[trial, team]),
                )
                for team in members
            }
            h2h: dict[int, tuple[int, int, int]] = {}
            if policy == "head_to_head_then_overall":
                by_points: dict[int, set[int]] = defaultdict(set)
                for team in members:
                    by_points[overall[team][0]].add(team)
                for tied in by_points.values():
                    if len(tied) > 1:
                        h2h.update(self.head_to_head(str(group["name"]), trial, tied))
                key = lambda team: (
                    overall[team][0],
                    *h2h.get(team, (0, 0, 0)),
                    overall[team][1], overall[team][2], overall[team][3],
                    random_keys[trial, members.index(team)],
                )
            else:
                by_primary: dict[tuple[int, int, int], set[int]] = defaultdict(set)
                for team in members:
                    by_primary[overall[team][:3]].add(team)
                for tied in by_primary.values():
                    if len(tied) > 1:
                        h2h.update(self.head_to_head(str(group["name"]), trial, tied))
                key = lambda team: (
                    overall[team][0], overall[team][1], overall[team][2],
                    *h2h.get(team, (0, 0, 0)),
                    overall[team][3],
                    random_keys[trial, members.index(team)],
                )
            result[trial] = sorted(members, key=key, reverse=True)
        return result

    def group_seeds(self) -> tuple[dict[tuple[str, int], np.ndarray], dict[str, np.ndarray]]:
        rankings = {
            str(group["name"]): self.rank_group(group)
            for group in self.rules["groups"]
        }
        seeds: dict[tuple[str, int], np.ndarray] = {}
        for name, table in rankings.items():
            for position in range(table.shape[1]):
                seeds[(name, position + 1)] = table[:, position]
        best_count = int(self.rules["best_third"])
        if not best_count:
            return seeds, {}
        names = sorted(rankings)
        third_teams = np.column_stack([seeds[(name, 3)] for name in names])
        rows = np.arange(self.trials)[:, None]
        points = self.points[rows, third_teams]
        gd = self.goals_for[rows, third_teams] - self.goals_against[rows, third_teams]
        gf = self.goals_for[rows, third_teams]
        wins = self.wins[rows, third_teams]
        random_keys = self.rng.random(third_teams.shape)
        order = np.lexsort((-random_keys, -wins, -gf, -gd, -points), axis=1)
        qualified_columns = order[:, :best_count]
        masks = np.zeros(self.trials, dtype=np.int64)
        for column in range(len(names)):
            masks |= np.any(qualified_columns == column, axis=1).astype(np.int64) << column
        allocations = self.rules["third_place_allocation"]
        third_for_winner: dict[str, np.ndarray] = {}
        for winner in sorted({key for mapping in allocations.values() for key in mapping}):
            selected = np.empty(self.trials, dtype=np.int16)
            for mask in np.unique(masks):
                key = "".join(name for column, name in enumerate(names) if int(mask) & (1 << column))
                mapping = allocations.get(key)
                if mapping is None or winner not in mapping:
                    raise SimulationError(f"No third-place allocation for {key} / winner {winner}")
                selected[masks == mask] = seeds[(str(mapping[winner]), 3)][masks == mask]
            third_for_winner[winner] = selected
        return seeds, third_for_winner

    def knockout_winner(
        self,
        first: np.ndarray,
        second: np.ndarray,
        day_text: str,
        home_sign: int | np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        regulation = self.distribution(first, second, day_text, home_sign)
        outcome = self.outcomes(regulation.probabilities)
        winner = np.where(outcome == 0, first, second).astype(np.int16)
        loser = np.where(outcome == 0, second, first).astype(np.int16)
        tied = outcome == 1
        if np.any(tied):
            extra = self.distribution(first, second, day_text, home_sign, duration=1.0 / 3.0)
            extra1 = self.rng.poisson(extra.lambda1)
            extra2 = self.rng.poisson(extra.lambda2)
            extra_outcome = np.where(extra1 > extra2, 0, np.where(extra1 == extra2, 1, 2))
            first_extra = tied & (extra_outcome == 0)
            second_extra = tied & (extra_outcome == 2)
            winner[first_extra], loser[first_extra] = first[first_extra], second[first_extra]
            winner[second_extra], loser[second_extra] = second[second_extra], first[second_extra]
            penalties = tied & (extra_outcome == 1)
            coin = self.rng.random(self.trials) < 0.5
            first_penalty = penalties & coin
            second_penalty = penalties & ~coin
            winner[first_penalty], loser[first_penalty] = first[first_penalty], second[first_penalty]
            winner[second_penalty], loser[second_penalty] = second[second_penalty], first[second_penalty]
        return winner, loser

    def two_leg_tie(
        self,
        leg1_home: np.ndarray,
        leg1_away: np.ndarray,
        first_day: str,
        leg2_home: np.ndarray,
        leg2_away: np.ndarray,
        second_day: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        if not (
            np.array_equal(leg2_home, leg1_away)
            and np.array_equal(leg2_away, leg1_home)
        ):
            raise SimulationError("Two-leg tie does not reverse the same entrants")
        first, second = leg1_home, leg1_away
        leg1 = self.distribution(leg1_home, leg1_away, first_day, 1)
        home1, away1 = self.conditional_scores(leg1)
        leg2 = self.distribution(leg2_home, leg2_away, second_day, 1)
        home2, away2 = self.conditional_scores(leg2)
        first_total = home1 + away2
        second_total = away1 + home2
        first_won = first_total > second_total
        second_won = second_total > first_total
        if bool(self.rules.get("away_goals")):
            aggregate_draw = first_total == second_total
            first_won |= aggregate_draw & (away2 > away1)
            second_won |= aggregate_draw & (away1 > away2)
        winner = np.where(first_won, first, second).astype(np.int16)
        loser = np.where(first_won, second, first).astype(np.int16)
        unresolved = ~(first_won | second_won)
        if np.any(unresolved):
            extra = self.distribution(
                leg2_home,
                leg2_away,
                second_day,
                1,
                duration=1.0 / 3.0,
            )
            extra1 = self.rng.poisson(extra.lambda1)
            extra2 = self.rng.poisson(extra.lambda2)
            outcome = np.where(extra1 > extra2, 0, np.where(extra1 == extra2, 1, 2))
            home_extra = unresolved & (outcome == 0)
            away_extra = unresolved & (outcome == 2)
            winner[home_extra], loser[home_extra] = leg2_home[home_extra], leg2_away[home_extra]
            winner[away_extra], loser[away_extra] = leg2_away[away_extra], leg2_home[away_extra]
            penalties = unresolved & (outcome == 1)
            coin = self.rng.random(self.trials) < 0.5
            home_penalty = penalties & coin
            away_penalty = penalties & ~coin
            winner[home_penalty], loser[home_penalty] = leg2_home[home_penalty], leg2_away[home_penalty]
            winner[away_penalty], loser[away_penalty] = leg2_away[away_penalty], leg2_home[away_penalty]
        return winner, loser

    def two_leg_winner(
        self,
        first: np.ndarray,
        second: np.ndarray,
        first_day: str,
        second_day: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        # The lower seed hosts leg one; the higher seed hosts the return.
        return self.two_leg_tie(
            second,
            first,
            first_day,
            first,
            second,
            second_day,
        )

    def resolve_seed(
        self,
        expression: list[str],
        seeds: dict[tuple[str, int], np.ndarray],
        third: dict[str, np.ndarray],
        winners: dict[str, np.ndarray],
        losers: dict[str, np.ndarray],
        opponent: list[str],
    ) -> np.ndarray:
        kind, value = str(expression[0]), str(expression[1])
        if kind.startswith("group"):
            return seeds[(value, int(kind[-1]))]
        if kind == "winner":
            return winners[value]
        if kind == "loser":
            return losers[value]
        if kind == "third-options":
            if opponent[0] != "group1":
                raise SimulationError("Third-place entrant is not paired with a group winner")
            return third[str(opponent[1])]
        raise SimulationError(f"Unknown knockout entrant: {expression}")

    def revision_graph_champion(
        self,
        seeds: dict[tuple[str, int], np.ndarray],
        third: dict[str, np.ndarray],
    ) -> np.ndarray:
        winners: dict[str, np.ndarray] = {}
        losers: dict[str, np.ndarray] = {}
        champion: np.ndarray | None = None
        for node in self.rules["knockout_matches"]:
            first = self.resolve_seed(node["team1"], seeds, third, winners, losers, node["team2"])
            second = self.resolve_seed(node["team2"], seeds, third, winners, losers, node["team1"])
            node_day = str(node.get("date") or self.entry.get("source_end") or self.start)
            venue_host = node.get("venue_host")
            if venue_host is None:
                home_sign: int | np.ndarray = 0
            else:
                host = self.index[str(venue_host)]
                home_sign = np.where(first == host, 1, np.where(second == host, -1, 0))
            winner, loser = self.knockout_winner(first, second, node_day, home_sign)
            winners[str(node["id"])] = winner
            losers[str(node["id"])] = loser
            if node.get("championship"):
                champion = winner
        if champion is None:
            raise SimulationError("Revision graph has no championship node")
        return champion

    def two_leg_graph_champion(
        self,
        seeds: dict[tuple[str, int], np.ndarray],
        third: dict[str, np.ndarray],
    ) -> np.ndarray:
        winners: dict[str, np.ndarray] = {}
        losers: dict[str, np.ndarray] = {}
        champion: np.ndarray | None = None
        for tie in self.rules["knockout_ties"]:
            resolved_legs: list[tuple[np.ndarray, np.ndarray, str]] = []
            for leg in tie["legs"]:
                home = self.resolve_seed(
                    leg["home"], seeds, third, winners, losers, leg["away"]
                )
                away = self.resolve_seed(
                    leg["away"], seeds, third, winners, losers, leg["home"]
                )
                resolved_legs.append((home, away, str(leg["date"])))
            winner, loser = self.two_leg_tie(
                resolved_legs[0][0],
                resolved_legs[0][1],
                resolved_legs[0][2],
                resolved_legs[1][0],
                resolved_legs[1][1],
                resolved_legs[1][2],
            )
            winners[str(tie["id"])] = winner
            losers[str(tie["id"])] = loser
            if tie.get("championship"):
                champion = winner
        if champion is None:
            raise SimulationError("Two-leg graph has no championship tie")
        return champion

    def standard_champion(
        self,
        seeds: dict[tuple[str, int], np.ndarray],
        *,
        two_leg: bool,
    ) -> np.ndarray:
        names = sorted(str(group["name"]) for group in self.rules["groups"])
        if len(names) == 2:
            pairs = [
                (seeds[(names[0], 1)], seeds[(names[1], 2)]),
                (seeds[(names[1], 1)], seeds[(names[0], 2)]),
            ]
        elif len(names) == 4:
            pairs = [
                (seeds[(names[0], 1)], seeds[(names[1], 2)]),
                (seeds[(names[1], 1)], seeds[(names[0], 2)]),
                (seeds[(names[2], 1)], seeds[(names[3], 2)]),
                (seeds[(names[3], 1)], seeds[(names[2], 2)]),
            ]
        else:
            raise SimulationError("Standard bracket supports two or four groups")
        latest = max(str(item["date"]) for item in self.rules["group_fixtures"])
        first_day = (date.fromisoformat(latest) + timedelta(days=4)).isoformat()
        second_day = (date.fromisoformat(latest) + timedelta(days=8)).isoformat()
        round_winners = []
        for first, second in pairs:
            if two_leg:
                winner, _ = self.two_leg_winner(first, second, first_day, second_day)
            else:
                winner, _ = self.knockout_winner(first, second, first_day, 0)
            round_winners.append(winner)
        while len(round_winners) > 1:
            next_round = []
            first_day = (date.fromisoformat(second_day) + timedelta(days=4)).isoformat()
            second_day = (date.fromisoformat(second_day) + timedelta(days=8)).isoformat()
            for offset in range(0, len(round_winners), 2):
                first, second = round_winners[offset:offset + 2]
                if two_leg:
                    winner, _ = self.two_leg_winner(first, second, first_day, second_day)
                else:
                    winner, _ = self.knockout_winner(first, second, first_day, 0)
                next_round.append(winner)
            round_winners = next_round
        return round_winners[0]

    def simulate(self) -> np.ndarray:
        self.play_groups()
        seeds, third = self.group_seeds()
        kind = str(self.rules["knockout_kind"])
        if kind == "revision_graph":
            champion = self.revision_graph_champion(seeds, third)
        elif kind == "two_leg_graph":
            champion = self.two_leg_graph_champion(seeds, third)
        elif kind == "standard-neutral":
            champion = self.standard_champion(seeds, two_leg=False)
        elif kind == "two-leg-standard":
            champion = self.standard_champion(seeds, two_leg=True)
        else:
            raise SimulationError(f"Unsupported knockout kind: {kind}")
        return np.bincount(champion, minlength=len(self.codes)).astype(np.int64)


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": 1, "editions": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if int(value.get("schema", -1)) != 1:
        raise ValueError("Unsupported tournament-probability cache schema")
    return value


def write_cache_if_changed(path: Path, value: dict[str, Any]) -> bool:
    text = canonical_json(value) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def cached_row_is_valid(
    row: dict[str, Any],
    signature: dict[str, Any],
    trials: int,
) -> bool:
    """Reject a stale or damaged simulation instead of publishing it."""
    try:
        if any(row.get(field) != value for field, value in signature.items()):
            return False
        payload = dict(row)
        recorded = str(payload.pop("simulation_sha256"))
        if digest(payload) != recorded:
            return False
        codes = [str(code) for code in row["codes"]]
        wins = np.asarray(row["wins"], dtype=np.int64)
        if len(codes) != len(set(codes)) or len(wins) != len(codes):
            return False
        if np.any(wins < 0) or int(wins.sum()) != trials:
            return False
        expected = rounded_tenths(wins, codes)
        actual = {str(code): float(value) for code, value in row["title_chances"].items()}
        return actual == expected
    except (KeyError, TypeError, ValueError):
        return False


def compute_title_chances(
    manifest: dict[str, Any],
    states: dict[str, dict[str, Any]],
    cache_path: Path,
) -> dict[str, dict[str, float]]:
    cache = load_cache(cache_path)
    old = dict(cache.get("editions", {}))
    editions: dict[str, Any] = {}
    public: dict[str, dict[str, float]] = {}
    trials = int(manifest["trials"])
    algorithm = str(manifest["algorithm"])
    for key, entry in sorted(manifest["editions"].items()):
        if entry.get("status") != "ready":
            continue
        state = states.get(key)
        if state is None:
            raise SimulationError(f"Replay did not capture pre-tournament state for {key}")
        signature = {
            "algorithm": algorithm,
            "facts_sha256": entry["facts_sha256"],
            "state_sha256": state["state_sha256"],
            "trials": trials,
        }
        previous = old.get(key)
        if previous and cached_row_is_valid(previous, signature, trials):
            print(f"Reusing tournament simulation {key}…", file=sys.stderr, flush=True)
            editions[key] = previous
            public[key] = {str(code): float(value) for code, value in previous["title_chances"].items()}
            continue
        seed_digest = hashlib.sha256(canonical_json({"edition": key, **signature}).encode("utf-8")).digest()
        seed = int.from_bytes(seed_digest[:8], "big", signed=False)
        print(
            f"Simulating {key} ({trials:,} trials)…",
            file=sys.stderr,
            flush=True,
        )
        simulator = TournamentSimulator(entry, state, trials, seed)
        wins = simulator.simulate()
        chances = rounded_tenths(wins, simulator.codes)
        row = {
            **signature,
            "seed": seed,
            "codes": simulator.codes,
            "wins": wins.tolist(),
            "title_chances": chances,
        }
        row["simulation_sha256"] = digest(row)
        editions[key] = row
        public[key] = chances
    output = {
        "schema": 1,
        "algorithm": algorithm,
        "trials": trials,
        "editions": editions,
    }
    output["cache_sha256"] = digest(output)
    write_cache_if_changed(cache_path, output)
    return public
