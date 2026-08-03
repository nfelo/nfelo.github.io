from __future__ import annotations

from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
LIVE_SOURCE_LOG_LOSS_DELTA = 0.000025
sys.path.insert(0, str(ROOT / "scripts"))

from ledger import read_matches, read_successors, read_supplemental_matches  # noqa: E402
from forecast_layer import (  # noqa: E402
    CALIBRATION_DECIMALS,
    canonical_calibration_value,
    outcome_preserving_pool,
    poisson_wdl,
    raked_score_matrix,
)
from fetch_sources import fetch_world_table  # noqa: E402
from model import (  # noqa: E402
    CONFIDENCE_Z,
    joint_gaussian_update,
    projected_public_record,
    projected_variance,
    three_way_probabilities,
)
from open_results import merge_record, venue_country  # noqa: E402
from venue_effects import VenueEffects  # noqa: E402


class _HTMLCheck(HTMLParser):
    pass


class StaticBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = ROOT / "public" / "data"
        cls.summary = json.loads((cls.data / "summary.json").read_text(encoding="utf-8"))
        cls.state = json.loads((cls.data / "state.json").read_text(encoding="utf-8"))
        cls.fixtures = json.loads((cls.data / "fixtures.json").read_text(encoding="utf-8"))

    def test_world_table_retries_incomplete_success_responses(self) -> None:
        row = "\t".join(["row", "1", "AA", "100"] + ["value"] * 27)
        incomplete = "\n".join([row] * 149)
        complete = "\n".join([row] * 200)

        class Client:
            def __init__(self) -> None:
                self.responses = [incomplete, complete]
                self.urls: list[str] = []

            def get(self, url: str) -> str:
                self.urls.append(url)
                return self.responses.pop(0)

        client = Client()
        with patch("fetch_sources.time.sleep"):
            text, rows = fetch_world_table(client, "https://example.test/World.tsv")
        self.assertEqual(text, complete)
        self.assertEqual(len(rows), 200)
        self.assertEqual(len(client.urls), 2)
        self.assertIn("nfelo_retry=", client.urls[1])

    def test_source_ledger_is_complete_and_ordered(self) -> None:
        successors = read_successors(ROOT / "source" / "teams.tsv")
        matches = read_matches(ROOT / "source" / "elo_pages", successors)
        self.assertGreaterEqual(len(matches), 52_302)
        self.assertGreaterEqual(matches[-1].date_text, "2026-07-11")
        self.assertEqual(matches, sorted(matches, key=lambda item: item.day))

    def test_summary_and_state_dimensions(self) -> None:
        meta = self.summary["meta"]
        self.assertGreaterEqual(meta["matches"], 52_302)
        self.assertGreaterEqual(meta["teams"], 248)
        count = len(self.state["codes"])
        self.assertEqual(count, meta["teams"])
        self.assertEqual(len(self.state["means"]), count)
        self.assertEqual(len(self.state["covariance"]), count * count)
        self.assertEqual(len(self.state["last_day"]), count)
        self.assertEqual(
            self.state["as_of_date"],
            meta["results_through"],
        )
        self.assertTrue(all(math.isfinite(value) for value in self.state["means"]))
        covariance = np.asarray(self.state["covariance"], dtype=np.float64).reshape(count, count)
        self.assertTrue(np.allclose(covariance, covariance.T, atol=1e-8))
        self.assertGreaterEqual(float(np.linalg.eigvalsh(covariance).min()), -1e-5)
        self.assertEqual(
            meta["methodology_version"],
            "2026-07-27-country-home-dependence",
        )
        self.assertGreaterEqual(
            meta["rankings_as_of"],
            meta["results_through"],
        )
        self.assertTrue(
            math.isfinite(self.state["margin_environment"])
        )
        self.assertAlmostEqual(
            self.summary["parameters"]["network"]["friendly_information_ratio"],
            0.78621,
            places=10,
        )
        venue = self.state["venue_effects"]
        for field in ("means", "variances", "last_day", "matches"):
            self.assertEqual(len(venue[field]), count)
        self.assertTrue(all(math.isfinite(value) for value in venue["means"]))
        self.assertTrue(all(value >= 0 for value in venue["variances"]))

    def test_rankings_and_records_are_sorted(self) -> None:
        ratings = [team["rating"] for team in self.summary["current"]]
        peaks = [item["rating"] for item in self.summary["peaks"]]
        matches = [item["combined"] for item in self.summary["top_matches"]]
        upsets = [item["points"] for item in self.summary["upsets"]]
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        self.assertEqual(peaks, sorted(peaks, reverse=True))
        self.assertEqual(matches, sorted(matches, reverse=True))
        self.assertEqual(upsets, sorted(upsets, reverse=True))
        self.assertTrue(all(item["winner_gain"] > 0 and item["loser_loss"] > 0 for item in self.summary["upsets"]))
        self.assertEqual(len({item["code"] for item in self.summary["peaks"]}), len(self.summary["peaks"]))
        self.assertNotIn("record_peaks", self.summary)
        self.assertTrue(all("record_rating" not in team for team in self.summary["teams"]))

    def test_all_matches_are_chunked_once(self) -> None:
        index = json.loads((self.data / "matches" / "index.json").read_text(encoding="utf-8"))
        total = 0
        ids = set()
        for item in index["decades"]:
            payload = json.loads((self.data / "matches" / item["file"]).read_text(encoding="utf-8"))
            self.assertEqual(len(payload["matches"]), item["count"])
            total += item["count"]
            for match in payload["matches"]:
                self.assertIn(match["home"], (-1, 0, 1))
                self.assertAlmostEqual(sum(match["p"]), 1.0, places=6)
                self.assertNotIn(match["id"], ids)
                ids.add(match["id"])
        self.assertEqual(total, self.summary["meta"]["matches"])
        search = json.loads((self.data / "matches" / "search.json").read_text(encoding="utf-8"))["matches"]
        self.assertEqual(len(search), total)
        self.assertEqual(len({match["id"] for match in search}), total)

    def test_team_match_venue_codes(self) -> None:
        for code in ("AR", "EN", "JP"):
            page = json.loads((self.data / "teams" / f"{code}.json").read_text(encoding="utf-8"))
            self.assertTrue(page["matches"])
            self.assertTrue(all(match["site"] in {"H", "A", "N"} for match in page["matches"]))
            self.assertTrue(all("opponent_pre" in match and "opponent_post" in match for match in page["matches"]))

    def test_match_views_include_both_teams_ratings(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        for field in ("pre_a", "post_a", "pre_b", "post_b", "opponent_pre", "opponent_post"):
            self.assertIn(f"match.{field}", javascript)
        stylesheet = (ROOT / "public" / "assets" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("#content:focus { outline: none; }", stylesheet)

    def test_history_defaults_to_today_and_match_venue_uses_team_perspective(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('const requested = isoDate(route.query.get("date")) || today;', javascript)
        self.assertIn('function matchSite(match, perspective = "")', javascript)
        self.assertIn('if (perspective === match.b)', javascript)
        self.assertIn('matchTable(hydrated, document.getElementById("match-team").value)', javascript)
        self.assertIn('aria-label="Ranking date calendar"', javascript)
        self.assertIn(
            "chosen >= (index.last_matchday || index.last)",
            javascript,
        )

    def test_global_as_of_release_closes_all_audited_consistency_gaps(self) -> None:
        history_index = json.loads(
            (
                self.data
                / "rankings-history"
                / "index.json"
            ).read_text(encoding="utf-8")
        )
        latest = json.loads(
            (
                self.data
                / "rankings-history"
                / f'{history_index["last"][:4]}.json'
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            history_index["last"],
            self.summary["meta"]["rankings_as_of"],
        )
        self.assertEqual(
            history_index["last_matchday"],
            self.summary["meta"]["results_through"],
        )
        self.assertEqual(
            len(history_index["codes"]),
            self.summary["meta"]["teams"],
        )
        self.assertTrue(latest["global_snapshots"])
        self.assertEqual(
            latest["global_snapshots"][-1][0],
            history_index["last"],
        )

        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        builder = (
            ROOT / "scripts" / "build_site.py"
        ).read_text(encoding="utf-8")
        methodology = javascript
        for phrase in (
            "historicalRankingFromPayload",
            "global_snapshots",
            "currentState.margin_environment",
            "The selected-date ratings and latent means are exact global snapshots.",
            "Historical rows also omit archived pairwise covariance.",
            "summary.meta.rankings_as_of",
            "No direct match: network effects, inactivity decay or "
            "eligibility changed the order.",
            "&date=${encodeURIComponent(cutoff)}",
            "Why does NFELO include territories and some teams outside FIFA?",
            "Nᵢ = (Σⱼwᵢⱼ)² / Σⱼwᵢⱼ²",
            "G(0) = ${number(p.goal_margin.draw, 10)}",
        ):
            self.assertIn(phrase, methodology)
        self.assertNotIn(
            "const environment = useCurrent ? 1.1",
            javascript,
        )
        for phrase in (
            "combined_mean =",
            "combined_se =",
            "2.0 * float(covariance[i * count + j])",
            "def build_number_one_chronology",
        ):
            self.assertIn(phrase, builder)
        reunion = next(
            team
            for team in self.summary["teams"]
            if team["code"] == "RE"
        )
        self.assertEqual(reunion["nation"], "Réunion")

        fixtures = json.loads(
            (self.data / "fixtures.json").read_text(
                encoding="utf-8"
            )
        )["fixtures"]
        self.assertTrue(fixtures)
        self.assertTrue(all(
            "combined_mean" in fixture
            and "combined_se" in fixture
            for fixture in fixtures
        ))
        self.assertTrue(any(
            abs(
                float(fixture["combined_rating"])
                - float(fixture["rating1"])
                - float(fixture["rating2"])
            ) > 0.01
            for fixture in fixtures
        ))

    def test_public_readme_avoids_internal_setup_language(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        normalised_readme = " ".join(readme.split())
        self.assertNotIn("codex", readme)
        self.assertNotIn("bake-off", readme)
        self.assertIn("current formula accuracy", normalised_readme)
        self.assertIn("59.2%", readme)
        self.assertIn("across 46,801 stored pre-match forecasts", readme)
        self.assertNotIn("| formula | forecasts |", readme)
        self.assertNotIn("0.878333", readme)
        self.assertNotIn("59.170%", readme)
        self.assertIn(
            "methodology validation section",
            normalised_readme,
        )
        self.assertNotIn("0.884219", readme)
        self.assertIn(
            "older comparisons and component studies remain",
            normalised_readme,
        )
        self.assertIn("prospective_forecasts.jsonl", readme)
        validation = (ROOT / "docs" / "model-validation.md").read_text(encoding="utf-8").lower()
        for phrase in (
            "nested historical holdout",
            "retrospective full-history replay",
            "prospective",
            "joint order-invariant date update",
            "one public rating",
        ):
            self.assertIn(phrase, validation)

    def test_team_matches_use_names_from_the_match_date(self) -> None:
        germany = json.loads((self.data / "teams" / "DE.json").read_text(encoding="utf-8"))
        self.assertIn("West Germany", {match["team_name"] for match in germany["matches"]})
        historical_opponents = {
            match["opponent"]
            for code in ("DE", "EN", "FR")
            for match in json.loads(
                (self.data / "teams" / f"{code}.json").read_text(encoding="utf-8")
            )["matches"]
        }
        self.assertTrue(
            historical_opponents.intersection({"Soviet Union", "Czechoslovakia", "Yugoslavia"})
        )

    def test_probability_swap_invariance(self) -> None:
        first = three_way_probabilities(137.5, 12_345.0, 2026, friendly=False)
        second = three_way_probabilities(-137.5, 12_345.0, 2026, friendly=False)
        self.assertAlmostEqual(float(first[0]), float(second[2]), places=12)
        self.assertAlmostEqual(float(first[1]), float(second[1]), places=12)
        self.assertAlmostEqual(float(first[2]), float(second[0]), places=12)
        self.assertAlmostEqual(float(first.sum()), 1.0, places=12)

    def test_country_venue_state_is_causal_swap_invariant_and_neutral_safe(self) -> None:
        configuration = json.loads(
            (ROOT / "config" / "venue_effects.json").read_text(
                encoding="utf-8"
            )
        )
        first = VenueEffects(3, configuration)
        first.mean[:] = (40.0, -20.0, 10.0)
        first.variance[:] = (900.0, 1_225.0, 1_600.0)
        first.last_day[:] = 10_000

        correction = first.correction(0, 1, 1)
        swapped = first.correction(1, 0, -1)
        self.assertAlmostEqual(correction, 10.0, places=12)
        self.assertAlmostEqual(correction, -swapped, places=12)
        self.assertEqual(first.correction(0, 1, 0), 0.0)
        self.assertEqual(first.predictive_variance(0, 1, 1), 0.0)

        neutral_before = (
            first.mean.copy(),
            first.variance.copy(),
            first.matches.copy(),
        )
        first.update_day([{
            "first": 0,
            "second": 1,
            "home_sign": 0,
            "result": 1.0,
            "expected": 0.25,
            "friendly": False,
        }])
        self.assertTrue(np.array_equal(first.mean, neutral_before[0]))
        self.assertTrue(np.array_equal(first.variance, neutral_before[1]))
        self.assertTrue(np.array_equal(first.matches, neutral_before[2]))

        observations = [
            {
                "first": 0,
                "second": 1,
                "home_sign": 1,
                "result": 1.0,
                "expected": 0.55,
                "friendly": False,
            },
            {
                "first": 2,
                "second": 0,
                "home_sign": 1,
                "result": 0.0,
                "expected": 0.61,
                "friendly": True,
            },
        ]
        ordered = VenueEffects(3, configuration)
        reversed_order = VenueEffects(3, configuration)
        ordered.advance_many((0, 1, 2), 12_000)
        reversed_order.advance_many((0, 1, 2), 12_000)
        ordered.update_day(observations)
        reversed_order.update_day(list(reversed(observations)))
        self.assertTrue(
            np.allclose(ordered.mean, reversed_order.mean, atol=1e-14)
        )
        self.assertTrue(
            np.allclose(
                ordered.variance,
                reversed_order.variance,
                atol=1e-14,
            )
        )
        self.assertTrue(
            np.array_equal(ordered.matches, reversed_order.matches)
        )

        decay = VenueEffects(1, configuration)
        decay.mean[0] = 40.0
        decay.variance[0] = 900.0
        decay.last_day[0] = 8_000
        projected = decay.record(0, 8_000 + 40 * 400)
        self.assertAlmostEqual(projected["dependence"], 20.0, places=10)
        self.assertGreater(projected["se"], 30.0)
        self.assertLess(projected["se"], 60.0)

    def test_country_venue_release_data_ui_and_guardrails(self) -> None:
        parameters = self.summary["parameters"]["venue_effects"]
        study = self.summary["validation"]["home_advantage_study"]
        self.assertEqual(parameters["prior_sd"], 60.0)
        self.assertEqual(parameters["half_life_years"], 40.0)
        self.assertEqual(parameters["home_share"], 0.5)
        self.assertEqual(parameters["away_share"], 0.5)
        self.assertEqual(parameters["neutral_effect"], 0.0)
        self.assertEqual(parameters["predictive_variance_scale"], 0.0)
        self.assertEqual(study["matches"], 46_801)
        self.assertEqual(study["untouched_matches"], 6_320)
        self.assertGreater(study["final_log_loss_improvement"], 0.001)
        self.assertGreater(
            study["untouched_log_loss_improvement"],
            0.001,
        )
        self.assertTrue(study["all_five_time_blocks_improved"])

        for code in ("BO", "DE", "ES"):
            page = json.loads(
                (
                    self.data
                    / "teams"
                    / f"{code}.json"
                ).read_text(encoding="utf-8")
            )
            profile = page["team"]["venue_effect"]
            for field in (
                "dependence",
                "se",
                "hosting_adjustment",
                "away_adjustment",
                "away_disadvantage",
                "neutral",
                "reliability",
                "matches",
                "as_of_day",
            ):
                self.assertIn(field, profile)
            self.assertAlmostEqual(
                profile["hosting_adjustment"],
                -profile["away_adjustment"],
                places=7,
            )
            self.assertEqual(profile["neutral"], 0.0)
            self.assertTrue(
                any("venue_effect" in point for point in page["history"])
            )
            score_states = [
                point["score_state"]
                for point in page["history"]
                if point.get("score_state")
            ]
            self.assertTrue(score_states)
            for field in (
                "attack",
                "defence",
                "last_day",
                "annual_decay",
                "learning_rate",
            ):
                self.assertIn(field, score_states[-1])

        latest_matches = json.loads(
            (
                self.data
                / "matches"
                / "2020.json"
            ).read_text(encoding="utf-8")
        )["matches"]
        self.assertTrue(all(
            "global_home" in match
            and "country_home" in match
            for match in latest_matches
        ))
        self.assertTrue(all(
            match["country_home"] == 0.0
            for match in latest_matches
            if match["home"] == 0
        ))
        for fixture in self.fixtures["fixtures"]:
            self.assertAlmostEqual(
                fixture["total_home_adjustment"],
                fixture["global_home_adjustment"]
                + fixture["country_home_adjustment"],
                places=7,
            )

        early_british = {
            "England",
            "Scotland",
            "Wales",
            "Northern Ireland",
        }
        top_ten_early_british = [
            peak
            for peak in self.summary["peaks"][:10]
            if peak["nation"] in early_british
            and peak["date"] < "1914-01-01"
        ]
        self.assertLessEqual(len(top_ten_early_british), 1)
        self.assertEqual(self.summary["current"][0]["nation"], "Spain")

        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in (
            "Home and away",
            "Extra at home",
            "Extra when away",
            "See uncertainty and technical details",
            "Why are a team’s home and away adjustments linked?",
            "What happens at a neutral venue?",
            "projectVenueProfile",
            "compactVenueProfileHTML",
            "projectScoreProfile",
            'class="venue-profile score-profile"',
            "score-profile-details",
            '<h2 id="score-profile-title">Attack and defence</h2>',
            "Own expected goals",
            "Opponent expected goals",
            "Attack residual",
            "Defence residual",
            "after every non-neutral matchday",
            "after each completed matchday",
        ):
            self.assertIn(phrase, javascript)
        score_panel = javascript.split(
            'const scorePanel = scoreProfile ? `',
            1,
        )[1].split('` : "";', 1)[0]
        self.assertNotIn("Last matchday update", score_panel)
        self.assertNotIn("Reversion half-life", score_panel)
        self.assertNotIn("validDate(venueAsOfDate)", score_panel)
        self.assertNotIn("<small>", score_panel)
        self.assertIn(
            'Match adjustment${cutoff ? '
            '` · ${validDate(venueAsOfDate)}` : ""}',
            javascript,
        )
        self.assertNotIn(
            "Match adjustment · ${validDate(venueAsOfDate)}",
            javascript,
        )
        for phrase in (
            ".venue-profile",
            ".venue-profile-highlights",
            ".venue-highlight",
            ".venue-profile-details",
            ".team-model-details",
            ".score-profile",
            ".score-profile-highlights",
            ".score-profile-details .venue-detail-grid",
        ):
            self.assertIn(phrase, stylesheet)
        self.assertNotIn(".venue-profile-metrics", stylesheet)
        self.assertNotIn(".venue-metric-primary", stylesheet)
        self.assertIn("Country-specific home and away profiles", readme)
        self.assertIn(
            "research/home-advantage-2026-07-27/",
            readme,
        )

    def test_score_layer_is_swap_invariant_and_preserves_the_network_pick(self) -> None:
        first = poisson_wdl(1.91, 0.83)
        second = poisson_wdl(0.83, 1.91)
        self.assertTrue(np.allclose(first, second[::-1], atol=1e-14))
        network = np.asarray((0.41, 0.30, 0.29))
        score = np.asarray((0.10, 0.20, 0.70))
        candidate = 0.55 * network + 0.45 * score
        final, clipped = outcome_preserving_pool(network, score, 0.55)
        self.assertTrue(clipped)
        self.assertNotEqual(int(np.argmax(candidate)), int(np.argmax(network)))
        self.assertEqual(int(np.argmax(final)), int(np.argmax(network)))
        self.assertFalse(np.array_equal(final, network))
        self.assertAlmostEqual(float(final.sum()), 1.0, places=12)

        swapped, swapped_clipped = outcome_preserving_pool(
            network[::-1], score[::-1], 0.55
        )
        self.assertEqual(swapped_clipped, clipped)
        self.assertTrue(np.allclose(final, swapped[::-1], atol=1e-12))

    def test_joint_date_update_is_order_invariant(self) -> None:
        mean = np.asarray((12.0, -4.0, 7.5, -15.5), dtype=np.float64)
        covariance = np.asarray(
            (
                (900.0, 75.0, 20.0, -15.0),
                (75.0, 800.0, 40.0, 10.0),
                (20.0, 40.0, 700.0, 55.0),
                (-15.0, 10.0, 55.0, 850.0),
            ),
            dtype=np.float64,
        )
        observations = [
            (0, 1, 0.0007, 0.020),
            (2, 3, 0.0011, -0.018),
            (0, 2, 0.0004, 0.009),
        ]
        first_mean, first_covariance, contributions = joint_gaussian_update(
            mean, covariance, observations
        )
        second_mean, second_covariance, _ = joint_gaussian_update(
            mean, covariance, list(reversed(observations))
        )
        self.assertTrue(np.allclose(first_mean, second_mean, atol=1e-10))
        self.assertTrue(np.allclose(first_covariance, second_covariance, atol=1e-10))
        self.assertTrue(np.allclose(
            first_mean - mean,
            np.sum(np.asarray(contributions), axis=0),
            atol=1e-10,
        ))
        self.assertGreaterEqual(float(np.linalg.eigvalsh(first_covariance).min()), -1e-8)

    def test_raked_score_matrix_matches_final_wdl(self) -> None:
        final = np.asarray((0.47, 0.28, 0.25), dtype=np.float64)
        matrix = raked_score_matrix(1.73, 1.06, final)
        rows, columns = np.indices(matrix.shape)
        actual = np.asarray((
            matrix[rows > columns].sum(),
            matrix[rows == columns].sum(),
            matrix[rows < columns].sum(),
        ))
        self.assertTrue(np.allclose(actual, final, atol=1e-12))
        swapped = raked_score_matrix(1.06, 1.73, final[::-1])
        self.assertTrue(np.allclose(matrix, swapped.T, atol=1e-12))

    def test_deployed_forecast_layer_matches_the_audited_release(self) -> None:
        summary = json.loads(
            (ROOT / "public" / "data" / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        research = json.loads(
            (
                ROOT
                / "research"
                / "home-advantage-2026-07-27"
                / "results.json"
            ).read_text(encoding="utf-8")
        )

        # Frozen methodology choices remain exact. Live source corrections
        # must never silently change the published rating model.
        self.assertEqual(
            summary["meta"]["methodology_version"],
            "2026-07-27-country-home-dependence",
        )
        self.assertEqual(
            summary["parameters"]["network"]
            ["friendly_information_ratio_exact"],
            "0.78621",
        )
        self.assertEqual(
            summary["parameters"]["forecast_temperature_exact"],
            {
                "friendly": "0.896294991479",
                "competitive": "1.061356232973",
            },
        )

        replay = summary["validation"]["retrospective"]
        expected = research["end_to_end"]["selected"]
        self.assertEqual(replay["matches"], research["scored_matches"])

        # These are aggregate diagnostics derived from a live historical
        # source. Tiny upstream corrections and platform floating-point
        # differences are acceptable; a material model change is not.
        metric_tolerances = {
            "log_loss": LIVE_SOURCE_LOG_LOSS_DELTA,
            "network_only_log_loss": 0.000005,
            "brier": 0.000005,
            "rps": 0.000005,
            # Accuracy moves in whole-match increments. Permit at most
            # two changed classifications in the 46,801-match audit.
            "accuracy": 2.5 / replay["matches"],
        }
        for actual_key, expected_key in (
            ("log_loss", "log_loss"),
            ("network_only_log_loss", "network_log_loss"),
            ("brier", "brier"),
            ("rps", "rps"),
            ("accuracy", "accuracy"),
        ):
            self.assertAlmostEqual(
                replay[actual_key],
                expected[expected_key],
                delta=metric_tolerances[actual_key],
            )

        # The fitted score layer must continue to improve log loss over
        # the public-rating-only probabilities on the audit replay.
        self.assertLess(
            replay["log_loss"],
            replay["network_only_log_loss"],
        )
        self.assertLess(
            replay["log_loss"],
            research["end_to_end"]["baseline"]["log_loss"],
        )

        forecast_layer = summary["parameters"]["forecast_layer"]
        calibration = forecast_layer["calibration"]
        calibration_year = int(calibration["year"])
        window_years = int(
            forecast_layer["calibration_window_years"]
        )

        # This is the causal rolling-recalibration contract. A calibration
        # for year Y may use completed results through Y-1, never year Y.
        # When the calendar advances, the newest completed year therefore
        # enters the fit automatically and the oldest year drops out.
        self.assertEqual(
            calibration["training_last_year"],
            calibration_year - 1,
        )
        self.assertEqual(
            calibration["training_first_year"],
            calibration_year - window_years,
        )
        self.assertGreaterEqual(
            calibration["training_matches"],
            500,
        )
        self.assertGreaterEqual(
            calibration_year,
            int(summary["meta"]["results_through"][:4]),
        )

        parameter_bounds = {
            "draw_log_tilt": (-0.35, 0.35),
            "friendly_temperature": (0.75, 1.30),
            "competitive_temperature": (0.75, 1.30),
            "nfelo_weight": (0.0, 1.0),
        }
        for key, (lower, upper) in parameter_bounds.items():
            value = float(calibration[key])
            self.assertTrue(math.isfinite(value))
            self.assertGreaterEqual(value, lower)
            self.assertLessEqual(value, upper)
            self.assertEqual(value, canonical_calibration_value(value))
        self.assertEqual(
            forecast_layer["calibration_precision_decimals"],
            CALIBRATION_DECIMALS,
        )

        # While 2026 remains the active calibration, keep a tight guard
        # around its audited coefficients. From 2027 onward the rolling
        # fit is intentionally allowed to move as newer results enter.
        if calibration_year == 2026:
            expected_calibration = expected["calibration_2026"]
            for key in (
                "draw_log_tilt",
                "friendly_temperature",
                "competitive_temperature",
                "nfelo_weight",
            ):
                self.assertAlmostEqual(
                    calibration[key],
                    expected_calibration[key],
                    delta=0.00005,
                )

    def test_calibration_grid_absorbs_observed_platform_jitter(self) -> None:
        self.assertEqual(CALIBRATION_DECIMALS, 6)
        self.assertEqual(
            canonical_calibration_value(0.54751830),
            canonical_calibration_value(0.54751843),
        )
        self.assertEqual(
            canonical_calibration_value(0.54751843),
            0.547518,
        )
        with self.assertRaises(ValueError):
            canonical_calibration_value(float("nan"))

    def test_standalone_404_uses_the_current_light_and_dark_theme(self) -> None:
        source = (ROOT / "config" / "404.html").read_text(encoding="utf-8")
        built = (ROOT / "public" / "404.html").read_text(encoding="utf-8")
        self.assertEqual(built, source)
        for phrase in (
            'media="(prefers-color-scheme: light)"',
            'media="(prefers-color-scheme: dark)"',
            "@media (prefers-color-scheme: dark)",
            "color-scheme: dark",
            "background: #fff6fb",
            "background: #1b0d17",
            "a:focus-visible",
            "@media (max-width: 480px)",
        ):
            self.assertIn(phrase, source)
        for legacy_colour in ("#10252b", "#f4f1e8", "#fffdf7", "#0b1f26"):
            self.assertNotIn(legacy_colour, source)

        def luminance(colour: str) -> float:
            channels = [
                int(colour[index:index + 2], 16) / 255.0
                for index in (1, 3, 5)
            ]
            linear = [
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return (
                0.2126 * linear[0]
                + 0.7152 * linear[1]
                + 0.0722 * linear[2]
            )

        def contrast(first: str, second: str) -> float:
            lighter, darker = sorted(
                (luminance(first), luminance(second)),
                reverse=True,
            )
            return (lighter + 0.05) / (darker + 0.05)

        for foreground, background in (
            ("#44203d", "#fff9fc"),
            ("#75566c", "#fff9fc"),
            ("#7b286b", "#fff9fc"),
            ("#fff4fb", "#4a183f"),
            ("#f3dce9", "#4a183f"),
            ("#3b1532", "#ff9bd5"),
            ("#fff2fa", "#2c1425"),
            ("#e8cede", "#2c1425"),
            ("#f3a8dc", "#2c1425"),
            ("#fff2fa", "#6f3466"),
        ):
            self.assertGreaterEqual(contrast(foreground, background), 4.5)

    def test_faq_page_is_complete_and_discoverable(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        sitemap = (ROOT / "public" / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn('href="#/faq">FAQ</a>', html)
        self.assertIn('case "faq": renderFAQ(); break;', javascript)
        self.assertEqual(javascript.count('question: "'), 33)
        self.assertNotIn(
            "What do the Tournaments and Best tournaments pages show?",
            javascript,
        )
        self.assertIn(
            "How is the methodology tested?",
            javascript,
        )
        self.assertIn("Search questions", javascript)
        self.assertIn(
            "Why is a friendly’s rating change not always "
            "78.6% of a competitive match?",
            javascript,
        )
        self.assertIn(
            "Testing different friendly weights by era did not "
            "improve later forecasts",
            javascript,
        )
        self.assertIn("Expand all", javascript)
        self.assertIn("Collapse all", javascript)
        self.assertIn("https://nfelo.github.io/faq/", sitemap)
        self.assertTrue((ROOT / "public" / "faq" / "index.html").exists())

    def test_faq_search_home_link_github_and_current_team_name(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function faqSearchTokens", javascript)
        self.assertIn('token.endsWith("ies")', javascript)
        self.assertIn("terms.every", javascript)
        self.assertIn('href="#/faq">Questions? Read the FAQ', javascript)
        self.assertIn("https://github.com/nfelo/nfelo.github.io", javascript)
        teams = {team["code"]: team["nation"] for team in self.summary["teams"]}
        self.assertEqual(teams["AS"], "American Samoa")

    def test_world_number_one_spells_are_complete_and_visible(self) -> None:
        spells = self.summary["number_ones"]
        self.assertGreater(len(spells), 20)
        self.assertEqual(spells, sorted(spells, key=lambda row: row["from"], reverse=True))
        self.assertIsNone(spells[0]["to"])
        self.assertTrue(all(spell["days"] > 0 for spell in spells))
        for older, newer in zip(reversed(spells), list(reversed(spells))[1:]):
            self.assertLessEqual(older["from"], newer["from"])
            self.assertTrue(
                older["code"] != newer["code"] or older["nation"] != newer["nation"]
            )
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-record="numberones"', javascript)
        self.assertIn("function numberOneTable", javascript)
        self.assertIn("function numberOneSummaryTable", javascript)
        self.assertIn('data-record="numberonesummary"', javascript)
        self.assertIn("Entry result or explanation", javascript)
        self.assertIn("Swipe horizontally to see all columns", javascript)
        self.assertTrue(all("match" in spell for spell in spells))
        self.assertTrue(all("cause" in spell for spell in spells))
        indirect_spells = []
        for spell in spells:
            involved = {
                spell["code"],
                spell.get("displaced_code"),
            }
            for match in spell.get("matches", []):
                self.assertTrue(
                    match["team1_code"] in involved
                    or match["team2_code"] in involved,
                    (
                        spell["from"],
                        spell["nation"],
                        match["team1"],
                        match["team2"],
                    ),
                )
            if spell["cause"] in {"network", "drift"}:
                indirect_spells.append(spell)
                self.assertFalse(spell.get("matches"))
                self.assertIn("No direct match:", spell["reason"])
        self.assertTrue(indirect_spells)
        self.assertIn(
            "A result is shown only when it involved the incoming "
            "or displaced leader",
            javascript,
        )
        summaries = self.summary["number_one_summary"]
        self.assertTrue(summaries)
        self.assertEqual(summaries, sorted(
            summaries, key=lambda row: (-row["days"], row["first"], row["nation"])
        ))
        self.assertEqual(sum(row["spells"] for row in summaries), len(spells))
        self.assertIn("Leadership is determined jointly after all results on each date", javascript)
        change_matches = [spell["match"] for spell in spells if spell.get("match")]
        self.assertTrue(change_matches)
        self.assertTrue(all(
            match["team1_code"] and match["team2_code"]
            and isinstance(match["score1"], int)
            and isinstance(match["score2"], int)
            for match in change_matches
        ))

    def test_internal_navigation_opens_at_top_and_supports_back(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        smoke = (
            ROOT / "scripts" / "smoke_browser_boot.js"
        ).read_text(encoding="utf-8")
        for marker in (
            "function routeFromInternalHref",
            "function navigateToInternalRoute",
            "history.pushState(",
            'scrollMode: "top"',
            'window.addEventListener("popstate"',
            'scrollMode: "restore"',
            'history.scrollRestoration = "manual";',
            "nfeloScrollY",
        ):
            self.assertIn(marker, javascript)
        self.assertIn(
            "new pages open at the top and Back restores the prior route",
            smoke,
        )

    def test_ranking_movement_comparison_and_number_one_filters(self) -> None:
        current = self.summary["current"]
        self.assertTrue(current)
        self.assertTrue(all("movement_date_12m" in team for team in current))
        self.assertTrue(any(team["rating_change_12m"] is not None for team in current))
        self.assertTrue(any(team["rank_change_12m"] is not None for team in current))
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        stylesheet = (ROOT / "public" / "assets" / "styles.css").read_text(encoding="utf-8")
        for phrase in (
            "function movementHTML",
            "12-month change",
            "async function renderCompare",
            "function comparisonChart",
            'id="number-one-team"',
            'id="number-one-from"',
            'id="number-one-to"',
        ):
            self.assertIn(phrase, javascript)
        self.assertIn('href="#/compare">Compare</a>', html)
        self.assertTrue((ROOT / "public" / "compare" / "index.html").exists())
        self.assertIn("https://nfelo.github.io/compare/", (ROOT / "public" / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertIn(".comparison-cards", stylesheet)
        self.assertIn("@media (max-width: 720px)", stylesheet)
        self.assertIn(".record-filters", stylesheet)
        self.assertIn(".record-filters[hidden]", stylesheet)
        self.assertIn('id="number-one-from" type="text"', javascript)
        self.assertIn('id="number-one-to" type="text"', javascript)
        self.assertIn('id="number-one-from-calendar"', javascript)
        self.assertIn('id="number-one-to-calendar"', javascript)
        self.assertIn('numberOneFilters.hidden = view !== "numberones";', javascript)
        self.assertNotIn('view === "numberones" || view === "numberonesummary"', javascript)
        self.assertIn("From date cannot be after To date.", javascript)
        self.assertIn("To date cannot be before From date.", javascript)
        self.assertIn("from > to", javascript)
        self.assertIn(
            "summary.meta.rankings_as_of",
            javascript,
        )
        self.assertIn('.min = from || "1872-01-01";', javascript)

    def test_team_and_comparison_rating_charts_are_interactive(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")
        for phrase in (
            "function interactiveRatingChart",
            "function initialiseRatingHistoryChart",
            "function comparisonChart",
            "function ratingChart",
            "chartPointAtOrBefore",
            "data-chart-from",
            "data-chart-to",
            "data-chart-earlier",
            "data-chart-later",
            "data-chart-zoom-in",
            "data-chart-zoom-out",
            "data-chart-all",
            "data-chart-inspector-values",
            'svg.addEventListener("pointermove"',
            'svg.addEventListener("click"',
            '"ArrowLeft", "ArrowRight", "Home", "End", "Escape"',
            "new ResizeObserver",
            'preserveAspectRatio="xMidYMid meet"',
            "initialiseRatingHistoryCharts(output)",
            "initialiseRatingHistoryCharts(content)",
        ):
            self.assertIn(phrase, javascript)
        self.assertNotIn('preserveAspectRatio="none"', javascript)
        for phrase in (
            "--chart-a:",
            "--chart-b:",
            "--chart-c:",
            "--chart-d:",
            "--chart-e:",
            "--chart-f:",
            "--chart-g:",
            "--chart-h:",
            "--chart-i:",
            "--chart-j:",
            "--chart-cursor:",
            "--chart-marker-fill:",
            ".chart-controls",
            ".chart-navigation",
            ".chart-inspector",
            ".chart-series-a",
            ".chart-series-j",
            ".rating-history-line",
            ".chart-marker",
            "stroke-dasharray: var(--series-dash)",
            ".rating-history-line.is-focused",
            ".rating-history-line.is-dimmed",
            "touch-action: pan-y",
            "@media (prefers-color-scheme: dark)",
            "@media (max-width: 720px)",
        ):
            self.assertIn(phrase, stylesheet)
        light_css, dark_css = stylesheet.split(
            "@media (prefers-color-scheme: dark)",
            maxsplit=1,
        )
        dark_css = dark_css.split("\n}\n\n* {", maxsplit=1)[0]

        def variables(block: str) -> dict[str, str]:
            values = {}
            for line in block.splitlines():
                stripped = line.strip()
                if stripped.startswith("--") and ":" in stripped:
                    name, value = stripped.rstrip(";").split(":", maxsplit=1)
                    values[name] = value.strip()
            return values

        def luminance(colour: str) -> float:
            channels = [
                int(colour[index:index + 2], 16) / 255
                for index in (1, 3, 5)
            ]
            linear = [
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return (
                0.2126 * linear[0]
                + 0.7152 * linear[1]
                + 0.0722 * linear[2]
            )

        def contrast(first: str, second: str) -> float:
            brighter, darker = sorted(
                (luminance(first), luminance(second)),
                reverse=True,
            )
            return (brighter + 0.05) / (darker + 0.05)

        for palette in (variables(light_css), variables(dark_css)):
            for line_colour in (
                "--chart-a",
                "--chart-b",
                "--chart-c",
                "--chart-d",
                "--chart-e",
                "--chart-f",
                "--chart-g",
                "--chart-h",
                "--chart-i",
                "--chart-j",
            ):
                self.assertGreaterEqual(
                    contrast(
                        palette[line_colour],
                        palette["--surface-subtle"],
                    ),
                    4.5,
                )

    def test_multi_team_comparison_includes_historical_teams(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")
        comparison_data = self.data / "comparison"
        expected_codes = {team["code"] for team in self.summary["teams"]}
        actual_codes = {path.stem for path in comparison_data.glob("*.json")}
        self.assertEqual(actual_codes, expected_codes)

        east_germany = json.loads(
            (comparison_data / "DD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(east_germany), {"code", "history"})
        self.assertEqual(east_germany["code"], "DD")
        self.assertTrue(east_germany["history"])
        self.assertLess(east_germany["history"][-1]["date"], "1991-01-01")
        self.assertTrue(
            all(
                set(point) == {"date", "rating", "historical_name"}
                for point in east_germany["history"]
            )
        )

        germany = json.loads(
            (comparison_data / "DE.json").read_text(encoding="utf-8")
        )
        self.assertTrue(
            any(
                point["date"].startswith("1985")
                and point["historical_name"] == "West Germany"
                for point in germany["history"]
            )
        )
        historical_names_1985 = {
            point["historical_name"]
            for path in comparison_data.glob("*.json")
            for point in json.loads(path.read_text(encoding="utf-8"))["history"]
            if point["date"].startswith("1985")
        }
        self.assertIn("Czechoslovakia", historical_names_1985)
        inactive_without_rating_lines = {
            team["code"]
            for team in self.summary["teams"]
            if not team.get("rank")
            and not json.loads(
                (
                    comparison_data
                    / f'{team["code"]}.json'
                ).read_text(encoding="utf-8")
            )["history"]
        }
        self.assertTrue(inactive_without_rating_lines)
        self.assertNotIn("DD", inactive_without_rating_lines)
        self.assertLess(
            (comparison_data / "ES.json").stat().st_size,
            (self.data / "teams" / "ES.json").stat().st_size,
        )

        for phrase in (
            "const MAX_COMPARISON_TEAMS = 10",
            "const allTeams = summary.teams",
            'route.query.get("teams")',
            'route.query.get("pair")',
            "data/comparison/",
            'id="comparison-add-toggle"',
            'id="comparison-new-team"',
            'id="comparison-pair-picker"',
            "Historical or currently unranked",
            "No longer active",
            "point.historical_name || item.label",
            "const chartSeriesClass",
            'if (!item.history.length) return [];',
            'if (!item.history.length) return "";',
            "No rating line (fewer than 30 matches)",
            "if (!config.series[index]?.history.length) return;",
        ):
            self.assertIn(phrase, javascript)
        for phrase in (
            ".comparison-team-list",
            ".comparison-add-panel",
            ".comparison-summary-table",
            ".comparison-pair-picker",
            ".chart-legend-item",
            ".chart-series-j",
        ):
            self.assertIn(phrase, stylesheet)

    def test_historical_predictor_score_grid_and_rating_effects(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "public" / "assets" / "styles.css").read_text(encoding="utf-8")
        for phrase in (
            'id="predict-date" type="text"',
            'id="predict-calendar"',
            "opening_prediction_context",
            "prediction_contexts",
            "Reconciled score probabilities",
            "Effect of each winning margin",
            "for (let margin = -5; margin <= 5; margin += 1)",
            "poissonMasses(lambdaA, 40)",
            "rakedCell",
            "teams[0].code",
            "teams.find((team) => team.code !== codeA).code",
        ):
            self.assertIn(phrase, javascript)
        self.assertIn(".score-grid table", stylesheet)
        self.assertIn(".margin-grid table", stylesheet)
        latest_history = json.loads(
            (self.data / "rankings-history" / f'{self.summary["meta"]["results_through"][:4]}.json').read_text(encoding="utf-8")
        )
        self.assertIn("opening_prediction_context", latest_history)
        self.assertIn("prediction_contexts", latest_history)
        self.assertTrue(latest_history["prediction_contexts"])
        self.assertTrue(all("context" in item and "margin_environment" in item for item in latest_history["prediction_contexts"]))
        rows = latest_history["opening"] + latest_history["events"]
        self.assertTrue(any("latent" in row and "reliability" in row and "score_state" in row for row in rows))

    def test_fixture_search_placeholder_uses_a_listed_match(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn("const exampleFixture = fixtures.length", javascript)
        self.assertIn("Math.floor(Math.random() * fixtures.length)", javascript)
        self.assertIn("exampleFixture.team1_name", javascript)
        self.assertIn("exampleFixture.team2_name", javascript)
        self.assertIn("exampleFixture.tournament_name", javascript)
        self.assertIn('placeholder="${escapeHTML(fixtureSearchPlaceholder)}"', javascript)
        self.assertIn('fixtureSearchPlaceholder = exampleFixture', javascript)
        self.assertIn(': "Team or competition…";', javascript)
        self.assertNotIn('placeholder="Vietnam, friendly, AFCON…"', javascript)

    def test_methodology_explains_probability_only_layer_in_plain_english(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        methodology = javascript.split(
            "function renderMethodology(query",
            1,
        )[1].split("function renderAbout", 1)[0]
        for phrase in (
            "In plain English",
            "Connect the opposition",
            "changes probabilities only",
            "Attack, defence and annual calibration",
            "preceding ${number(f.calibration_window_years)} complete years",
            "Joint matchday update",
            "Current deployed NFELO formula",
            "summary.validation.retrospective",
            "number(replay.log_loss, 6)",
            "precisePercent(replay.accuracy)",
            "Earlier NFELO network benchmark",
            "Best tested scalar Elo",
            "G-Elo comparison",
            "Published World Football Elo forecast",
            "number(benchmark.published_wfe_log_loss, 6)",
            "Five-block historical holdout",
            "The published rating",
            "Constant, stepped and smoothly changing friendly weights",
            "calibration_precision_decimals",
            "method-contents",
            "method-details",
            "updated after every non-neutral matchday",
            "available in an expandable section on each team page",
        ):
            self.assertIn(phrase, methodology)
        for patch_note_phrase in (
            "1,650",
            "incremental era gain",
            "Previous full replay",
            "Country venue study:",
            "release improved",
            "0.884219",
        ):
            self.assertNotIn(patch_note_phrase, methodology)
        self.assertIn("applyForecastLayer", javascript)
        self.assertIn(
            "Why is a friendly’s rating change not always "
            "78.6% of a competitive match?",
            javascript,
        )
        self.assertNotIn("63.901%", javascript)
        self.assertNotIn("0.63901", javascript)
        self.assertIn(
            '${p.network.friendly_information_ratio_exact}',
            methodology,
        )
        self.assertIn(
            "<code>qₖ</code> is "
            "${p.network.friendly_information_ratio_exact}",
            methodology,
        )

    def test_faq_is_plain_language_and_methodology_links_are_section_aware(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        faq = javascript.split(
            "function buildFAQItems()",
            1,
        )[1].split("function faqSearchTokens", 1)[0]
        self.assertEqual(faq.count('question: "'), 33)
        for jargon in (
            "posterior",
            "latent",
            "covariance",
            "Gauss",
            "bootstrap",
            "hyperparameter",
            "order-invariant",
        ):
            self.assertNotIn(jargon, faq)
        self.assertIn(
            "Team pages label its evidence as limited, "
            "moderate or strong.",
            faq,
        )
        for phrase in (
            "updated after every non-neutral matchday",
            "Team pages show these tendencies in an expandable section.",
            "summary.validation.retrospective.accuracy",
            "percent(summary.validation.retrospective.accuracy)",
            "in technical comparisons, by log loss",
        ):
            self.assertIn(phrase, faq)
        self.assertLess(
            faq.index("in technical comparisons, by log loss"),
            faq.index(
                'question: "What does better log loss mean in practice?"'
            ),
        )
        self.assertNotIn(
            "summary.validation.retrospective.log_loss",
            faq,
        )
        for stale_public_metric in (
            "summary.validation.nested",
            "0.8842",
            "two different historical log-loss figures",
        ):
            self.assertNotIn(stale_public_metric, faq)

        section_links = set(re.findall(
            r'href="#/methodology\?section=([a-z]+)"',
            javascript,
        ))
        section_ids = set(re.findall(
            r'id="method-([a-z]+)"',
            javascript.split(
                "function renderMethodology(query",
                1,
            )[1].split("function renderAbout", 1)[0],
        ))
        self.assertEqual(
            section_ids,
            {
                "overview",
                "strength",
                "venue",
                "forecast",
                "learning",
                "ratings",
                "validation",
                "limits",
            },
        )
        self.assertEqual(section_links, section_ids)
        self.assertIn(
            'case "methodology": '
            "renderMethodology(current.query);",
            javascript,
        )
        self.assertIn(
            'target?.scrollIntoView({ block: "start" });',
            javascript,
        )
        self.assertIn(
            "target?.focus({ preventScroll: true });",
            javascript,
        )

    def test_rating_forecast_explanation_and_current_accuracy(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        for phrase in (
            "Why can the lower-rated team be the forecast favourite?",
            "Why can a lower-rated team be the forecast favourite?",
            "ratingForecastExplanation()",
            "Top-choice W/D/L accuracy",
            "Current deployed NFELO formula",
            "percent(summary.validation.retrospective.accuracy)",
            "number(replay.log_loss, 6)",
            "yearNumber(f.calibration.year)",
            "yearNumber(f.calibration.training_first_year)",
            "yearNumber(f.calibration.training_last_year)",
        ):
            self.assertIn(phrase, javascript)
        home = javascript.split(
            "async function renderHome()",
            1,
        )[1].split("function renderRankings", 1)[0]
        faq = javascript.split(
            "function buildFAQItems()",
            1,
        )[1].split("function faqSearchTokens", 1)[0]
        about = javascript.split(
            "function renderAbout()",
            1,
        )[1].split("function renderNotFound", 1)[0]
        methodology = javascript.split(
            "function renderMethodology(query",
            1,
        )[1].split("function renderAbout", 1)[0]
        for public_summary in (home, faq, about):
            self.assertIn(
                "percent(summary.validation.retrospective.accuracy)",
                public_summary,
            )
            self.assertNotIn(
                "summary.validation.retrospective.log_loss",
                public_summary,
            )
            self.assertNotIn(
                "precisePercent(summary.validation.retrospective.accuracy)",
                public_summary,
            )
        self.assertNotIn("40-year venue half-life", about)
        self.assertIn("number(replay.log_loss, 6)", methodology)
        self.assertIn("precisePercent(replay.accuracy)", methodology)
        for comparison in (
            "Earlier NFELO network benchmark",
            "Best tested scalar Elo",
            "G-Elo comparison",
            "Published World Football Elo forecast",
            "number(benchmark.log_loss, 6)",
            "number(benchmark.best_scalar_elo_log_loss, 6)",
            "number(benchmark.g_elo_log_loss, 6)",
            "number(benchmark.published_wfe_log_loss, 6)",
        ):
            self.assertIn(comparison, methodology)
        self.assertNotIn(
            "precisePercent(nested.published_wfe_accuracy)",
            javascript,
        )
        self.assertNotIn("Historical holdout accuracy", javascript)
        self.assertNotIn("number(f.calibration.year)", javascript)
        self.assertNotIn("number(f.calibration.training_first_year)", javascript)
        self.assertNotIn("number(f.calibration.training_last_year)", javascript)
        self.assertNotIn("Does that mean a friendly is treated exactly like a World Cup match?", javascript)
        replay = self.summary["validation"]["retrospective"]
        self.assertEqual(replay["matches"], 46_801)
        self.assertEqual(
            javascript.count("number(replay.log_loss, 6)"),
            1,
        )
        self.assertIn(
            'getJSON("data/summary.json")',
            javascript,
        )
        self.assertIn('{ cache: "no-cache" }', javascript)
        self.assertNotRegex(
            javascript,
            r"\b0\.878(?:33346|31572)\b",
        )
        self.assertNotRegex(
            methodology,
            r"Current deployed NFELO formula[^\n]*<b>0\.\d{6}</b>",
        )
        self.assertAlmostEqual(
            replay["accuracy"],
            0.59169676,
            delta=2.5 / replay["matches"],
        )

    def test_same_date_and_publication_safeguards_are_present(self) -> None:
        model = (ROOT / "scripts" / "model.py").read_text(encoding="utf-8")
        forecast = (ROOT / "scripts" / "forecast_layer.py").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn("debut = self.debut_mean(year)", model)
        self.assertIn("self.initialise_with(index, first_match.day, debut)", model)
        self.assertIn("joint_gaussian_update(", model)
        self.assertIn("FRIENDLY_INFORMATION_RATIO = 0.78621", model)
        self.assertIn("runtime_is_friendly(", model)
        self.assertIn('item["friendly"]', model)
        self.assertIn("weight *= FRIENDLY_INFORMATION_RATIO", model)
        self.assertIn("def predict_day(", forecast)
        self.assertIn(
            "No result enters any score state until every forecast is stored.",
            forecast,
        )
        self.assertIn("def update_prospective_ledger(", builder)
        self.assertIn('source / "prospective_forecasts.jsonl"', builder)

        ledger = ROOT / "source" / "prospective_forecasts.jsonl"
        self.assertTrue(ledger.exists())
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
        self.assertTrue(rows)
        self.assertEqual(
            len({(row["fixture_key"], row["model_version"]) for row in rows}),
            len(rows),
        )
        self.assertTrue(all(len(row["state_sha256"]) == 64 for row in rows))
        self.assertTrue(all(len(row["source_sha256"]) == 64 for row in rows))

    def test_public_rating_and_historical_peak_guardrails(self) -> None:
        model = (
            ROOT / "scripts" / "model.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            (
                "variance = projected_variance("
            ),
            model,
        )
        self.assertIn(
            "as_of_day=current_day if recent else None",
            model,
        )
        self.assertIn(
            (
                "rating = adjusted_mean - CONFIDENCE_Z "
                "* marginal_se"
            ),
            model,
        )
        self.assertNotIn("strength_rating =", model)
        self.assertNotIn("record_rating", model)

        peaks = self.summary["peaks"]
        self.assertTrue(peaks)
        self.assertEqual(
            peaks,
            sorted(
                peaks,
                key=lambda peak: (
                    -peak["rating"],
                    peak["date"],
                    peak["code"],
                ),
            ),
        )
        self.assertEqual(
            len({peak["code"] for peak in peaks}),
            len(peaks),
        )
        early_british = [
            peak
            for peak in peaks
            if peak["code"] in {"EN", "SC", "WA", "EI"}
            and peak["date"] < "1914-07-28"
        ]
        self.assertTrue(early_british)
        self.assertLess(
            max(peak["rating"] for peak in early_british),
            2100.0,
        )
        self.assertNotIn(peaks[0], early_british)
        self.assertLessEqual(
            sum(
                peak in early_british
                for peak in peaks[:20]
            ),
            1,
        )
        top_ten = {
            peak["code"] for peak in peaks[:10]
        }
        top_twenty = {
            peak["code"] for peak in peaks[:20]
        }
        self.assertTrue({"ES", "BR"} <= top_ten)
        self.assertIn("EN", top_twenty)

    def test_inactivity_is_projected_without_rewriting_matchdays(self) -> None:
        base_variance = 2_500.0
        one_year = projected_variance(base_variance, 1000, 1400)
        two_years = projected_variance(base_variance, 1000, 1800)
        self.assertGreater(one_year, base_variance)
        self.assertGreater(two_years, one_year)
        self.assertEqual(
            projected_variance(base_variance, 1000, 900),
            base_variance,
        )

        original = {
            "date": "2020-01-01",
            "mean": 1900.0,
            "se": 50.0,
            "rating": 1900.0 - CONFIDENCE_Z * 50.0,
        }
        projected = projected_public_record(original, "2022-01-01")
        self.assertEqual(original["se"], 50.0)
        self.assertGreater(projected["se"], original["se"])
        self.assertLess(projected["rating"], original["rating"])
        self.assertEqual(projected["rating_date"], "2022-01-01")

        current = self.summary["current"]
        self.assertTrue(all(
            team["rating_date"] == self.summary["meta"]["rankings_as_of"]
            for team in current
        ))
        self.assertTrue(all(
            team["last_match_date"] <= team["rating_date"]
            for team in current
        ))

        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        builder = (
            ROOT / "scripts" / "build_site.py"
        ).read_text(encoding="utf-8")
        for phrase in (
            "const projectTeamRating = (team, asOfDate)",
            "historicalRankingFromPayload",
            "payload.global_snapshots",
            "currentRankingForDate(currentState, dateValue)",
        ):
            self.assertIn(phrase, javascript)
        self.assertIn("first_variance = projected_variance(", builder)
        self.assertIn('int(state["last_day"][i])', builder)

    def test_upcoming_fixtures_are_sorted_and_probabilistic(self) -> None:
        fixtures = self.fixtures["fixtures"]
        self.assertIsInstance(fixtures, list)
        self.assertEqual(
            fixtures,
            sorted(fixtures, key=lambda item: (item["date"], item["team1_name"])),
        )
        for fixture in fixtures:
            self.assertGreater(fixture["date"], self.summary["meta"]["results_through"])
            self.assertAlmostEqual(sum(fixture["probabilities"]), 1.0, places=7)
            self.assertIn(fixture["team1_code"], self.state["codes"])
            self.assertIn(fixture["team2_code"], self.state["codes"])
            self.assertIn(fixture.get("date_precision", "day"), {"day", "month"})

    def test_homepage_fixtures_are_dated_and_strength_sorted_within_day(self) -> None:
        from build_site import homepage_fixtures  # noqa: PLC0415

        crowded_day = [
            {
                "date": "2026-09-03",
                "date_precision": "day",
                "combined_rating": combined,
                "team1_name": f"Team {combined}",
                "team2_name": "Opponent",
                "tournament_name": "International",
            }
            for combined in (3100, 3700, 3300, 3900, 3500, 4100)
        ]
        rows = [
            {
                "date": "2026-08-01",
                "date_precision": "month",
                "combined_rating": 9999,
                "team1_name": "Undated",
                "team2_name": "Fixture",
                "tournament_name": "International",
            },
            *crowded_day,
            {
                "date": "2026-09-04",
                "date_precision": "day",
                "combined_rating": 9999,
                "team1_name": "Later",
                "team2_name": "Fixture",
                "tournament_name": "International",
            },
        ]
        selected = homepage_fixtures(rows)
        self.assertEqual(len(selected), 5)
        self.assertTrue(all(row["date_precision"] == "day" for row in selected))
        self.assertEqual(
            [row["combined_rating"] for row in selected],
            [4100, 3900, 3700, 3500, 3300],
        )

        homepage = json.loads(
            (self.data / "home.json").read_text(encoding="utf-8")
        )["fixtures"]
        self.assertEqual(homepage, homepage_fixtures(self.fixtures["fixtures"]))

    def test_historical_rankings_use_contemporary_names(self) -> None:
        history = json.loads((self.data / "rankings-history" / "1990.json").read_text(encoding="utf-8"))
        names = {row["nation"] for row in history["opening"]} | {
            row["nation"] for row in history["events"]
        }
        self.assertIn("West Germany", names)
        self.assertIn("Soviet Union", names)
        self.assertNotIn("USSR", names)
        self.assertIn("Czechoslovakia", names)
        self.assertIn("Yugoslavia", names)

    def test_secondary_source_merge_is_conflict_safe(self) -> None:
        first = {
            "date": "2026-07-14", "team1_code": "FR", "team2_code": "ES",
            "score1": 0, "score2": 2,
        }
        same_reversed = {
            "date": "2026-07-14", "team1_code": "ES", "team2_code": "FR",
            "score1": 2, "score2": 0,
        }
        records = {}
        merge_record(records, first)
        merge_record(records, same_reversed)
        self.assertEqual(len(records), 1)
        with self.assertRaises(ValueError):
            merge_record(records, {**first, "score1": 1})

    def test_world_cup_venue_countries(self) -> None:
        self.assertEqual(venue_country("Dallas (Arlington)"), ("United States", "US"))
        self.assertEqual(venue_country("Toronto"), ("Canada", "CA"))
        self.assertEqual(venue_country("Guadalajara (Zapopan)"), ("Mexico", "MX"))

    def test_supplemental_result_schema_reconstructs_match(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "supplement.csv"
            path.write_text(
                "date,team1_code,team2_code,team1_name,team2_name,score1,score2,"
                "tournament_code,tournament_name,city,country,neutral,home_sign\n"
                "2026-07-14,FR,ES,France,Spain,1,2,WC,FIFA World Cup,Arlington,"
                "United States,True,0\n",
                encoding="utf-8",
            )
            matches = read_supplemental_matches(
                path,
                read_successors(ROOT / "source" / "teams.tsv"),
            )
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].date_text, "2026-07-14")
            self.assertEqual((matches[0].team1, matches[0].team2), ("FR", "ES"))
            self.assertEqual((matches[0].score1, matches[0].score2), (1, 2))
            self.assertEqual(matches[0].home_sign, 0)

    def test_entry_html_and_manifest(self) -> None:
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        parser = _HTMLCheck()
        parser.feed(html)
        self.assertIn('id="content"', html)
        self.assertTrue((ROOT / "public" / "404.html").exists())
        manifest = json.loads((ROOT / "public" / "build-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("index.html", manifest["files"])
        self.assertIn("data/summary.json", manifest["files"])

    def test_clean_route_entries_have_distinct_metadata(self) -> None:
        public = ROOT / "public"
        rankings = (public / "rankings" / "index.html").read_text(encoding="utf-8")
        argentina = (public / "team" / "AR" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>Rankings &middot; Network Football Elo</title>", rankings)
        self.assertIn("https://nfelo.github.io/rankings/", rankings)
        self.assertIn("<title>Argentina &middot; Network Football Elo</title>", argentina)
        self.assertIn("https://nfelo.github.io/team/AR/", argentina)
        sitemap = (public / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://nfelo.github.io/team/AR/", sitemap)

    def test_site_is_configured_for_the_organization_root_domain(self) -> None:
        public = ROOT / "public"
        html = (public / "index.html").read_text(encoding="utf-8")
        self.assertIn('<base href="/">', html)
        self.assertIn('href="https://nfelo.github.io/"', html)
        self.assertNotIn("benyominnemoff-lab.github.io", html)
        self.assertNotIn("/network-football-elo/", html)
        self.assertIn(
            "Sitemap: https://nfelo.github.io/sitemap.xml",
            (public / "robots.txt").read_text(encoding="utf-8"),
        )

    def test_progressive_lists_offer_show_all(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        for prefix in ("record", "fixture", "team"):
            self.assertIn(f'id="{prefix}-more"', javascript)
            self.assertIn(f'id="{prefix}-all"', javascript)
        self.assertEqual(javascript.count(">Show more</button>"), javascript.count(">Show all</button>"))

    def test_historical_rankings_and_tournaments_are_built(self) -> None:
        history = json.loads(
            (self.data / "rankings-history" / "index.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            history["first"][:4],
            str(history["years"][0]["year"]),
        )
        self.assertEqual(
            history["last"][:4],
            str(history["years"][-1]["year"]),
        )
        self.assertNotIn("world_cups", history)
        latest = json.loads(
            (
                self.data
                / "rankings-history"
                / history["years"][-1]["file"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(latest["year"], int(history["last"][:4]))
        self.assertTrue(latest["opening"])
        self.assertEqual(
            latest["events"],
            sorted(
                latest["events"],
                key=lambda row: (
                    row["date"],
                    row["id"],
                    row["code"],
                ),
            ),
        )
        self.assertTrue(
            all(
                row["matches"] >= 30
                for row in latest["opening"] + latest["events"]
            )
        )

        catalog = json.loads(
            (self.data / "tournaments" / "index.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(catalog["categories"])
        self.assertTrue(catalog["families"])
        self.assertTrue(
            all(family["editions"] for family in catalog["families"])
        )
        world_cup = next(
            family
            for family in catalog["families"]
            if family["name"] == "FIFA World Cup"
        )
        self.assertGreaterEqual(len(world_cup["editions"]), 20)
        self.assertTrue(
            all(edition["teams"] for edition in world_cup["editions"])
        )
        copa = next(
            family
            for family in catalog["families"]
            if family["name"] == "Copa América"
        )
        copa_1959 = [
            edition["label"]
            for edition in copa["editions"]
            if edition["start"].startswith("1959-")
        ]
        self.assertGreaterEqual(len(copa_1959), 2)
        self.assertTrue(all("1959" in label for label in copa_1959))
        self.assertTrue(any("March" in label for label in copa_1959))
        self.assertTrue(any("December" in label for label in copa_1959))

    def test_history_and_tournament_interfaces(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        html = (ROOT / "public" / "index.html").read_text(
            encoding="utf-8"
        )
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")
        sitemap = (ROOT / "public" / "sitemap.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn("formatHistoryDateInput", javascript)
        self.assertIn('maxlength="10"', javascript)
        self.assertIn("Day must be between 01 and 31.", javascript)
        self.assertIn("Month must be between 01 and 12.", javascript)
        self.assertNotIn('id="history-world-cup"', javascript)
        self.assertIn(
            'href="#/tournaments">Tournaments</a>',
            html,
        )
        self.assertIn(
            'case "tournaments": await renderTournaments(current); break;',
            javascript,
        )
        self.assertIn('id="tournament-family"', javascript)
        self.assertIn('id="tournament-edition"', javascript)
        self.assertIn('id="tournament-view"', javascript)
        self.assertIn("tournament_rank_change", javascript)
        self.assertIn("tournament_rating_change", javascript)
        self.assertIn("function tournamentRankingsTable", javascript)
        self.assertIn("/* Tournament snapshots */", stylesheet)
        self.assertIn(
            "https://nfelo.github.io/tournaments/",
            sitemap,
        )
        self.assertTrue(
            (ROOT / "public" / "tournaments" / "index.html").exists()
        )




    def test_tournament_catalog_codes_participants_and_sorting(self) -> None:
        catalog = json.loads(
            (
                self.data
                / "tournaments"
                / "index.json"
            ).read_text(encoding="utf-8")
        )
        owners: dict[str, set[str]] = {}
        for family in catalog["families"]:
            for code in family.get("source_codes", []):
                owners.setdefault(code, set()).add(
                    family["name"]
                )
            for edition in family["editions"]:
                participants = edition.get(
                    "participants",
                    [],
                )
                self.assertEqual(
                    {
                        participant["code"]
                        for participant in participants
                    },
                    set(edition["teams"]),
                )
                self.assertEqual(
                    len(participants),
                    len(edition["teams"]),
                )
                self.assertTrue(
                    all(
                        participant["nation"]
                        for participant in participants
                    )
                )
                changes = edition.get(
                    "rating_changes",
                    [],
                )
                self.assertEqual(
                    {
                        change["code"]
                        for change in changes
                    },
                    set(edition["teams"]),
                )
                for change in changes:
                    self.assertGreater(
                        change["matches"],
                        0,
                    )
                    if change["change"] is None:
                        self.assertIsNone(
                            change["start_rating"]
                        )
                        self.assertIsNone(
                            change["end_rating"]
                        )
                    else:
                        self.assertAlmostEqual(
                            (
                                change["end_rating"]
                                - change["start_rating"]
                            ),
                            change["change"],
                            places=7,
                        )

        excluded_qualifier_codes = {
            "OQ", "GCQ", "CHQ", "CHT", "TGQ",
            "AEQ", "SEQ", "SET", "CLQ", "NLQ",
            "UNQ", "UNT", "EAQ", "EAT", "ARQ",
            "AQT", "FCQ", "FBQ", "NUQ",
        }
        self.assertFalse(
            excluded_qualifier_codes & owners.keys()
        )

        expected_other_codes = {
            "ATL", "BG", "CMS", "FPG", "FRN",
            "GNF", "GSG", "ILG", "JCM", "LIT",
            "NKR", "RCD", "TCC", "TRE", "VWC",
            "WIT",
        }
        actual_other_codes = {
            code
            for family in catalog["families"]
            if family["category"] == "Other tournaments"
            for code in family.get("source_codes", [])
        }
        self.assertEqual(
            actual_other_codes,
            expected_other_codes,
        )

        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            (
                '<option value="rating">Rating</option>'
                '<option value="rating_change">'
                'Rating change</option>'
                '<option value="rank_change">'
                'Rank change</option>'
                '<option value="name">Name</option>'
            ),
            javascript,
        )
        self.assertNotIn(
            (
                '<option value="rating_gain">'
                'Rating gain</option>'
            ),
            javascript,
        )
        for phrase in (
            "attributedChanges",
            "excluding recalibration and unrelated results",
            "editionParticipants",
            "including teams without a published rating",
        ):
            self.assertIn(phrase, javascript)

    def test_best_tournament_records_and_rating_sort_options(self) -> None:
        records = self.summary.get(
            "best_tournaments",
            [],
        )
        self.assertTrue(records)
        self.assertLessEqual(len(records), 500)
        self.assertEqual(
            records,
            sorted(
                records,
                key=lambda row: (
                    -row["rating_gain"],
                    row["after"],
                    row["tournament"],
                    row["nation"],
                ),
            )[:500],
        )
        self.assertTrue(
            all(
                row["rating_gain"] > 0
                for row in records
            )
        )

        catalog = json.loads(
            (
                self.data
                / "tournaments"
                / "index.json"
            ).read_text(encoding="utf-8")
        )
        attributed = {
            (
                family["id"],
                edition["id"],
                change["code"],
            ): change
            for family in catalog["families"]
            for edition in family["editions"]
            for change in edition.get(
                "rating_changes",
                [],
            )
        }
        for row in records:
            key = (
                row["tournament_id"],
                row["edition_id"],
                row["code"],
            )
            self.assertIn(key, attributed)
            change = attributed[key]
            self.assertGreater(
                row["tournament_matches"],
                0,
            )
            self.assertAlmostEqual(
                row["rating_gain"],
                change["change"],
                places=7,
            )
            self.assertAlmostEqual(
                row["before_rating"],
                change["start_rating"],
                places=7,
            )
            self.assertAlmostEqual(
                row["after_rating"],
                change["end_rating"],
                places=7,
            )

        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        for phrase in (
            'data-record="tournaments"',
            "function bestTournamentTable",
            "const bestTournamentRows = (",
            "summary.best_tournaments || []",
            ").slice(0, 500);",
            "edition's own matchdays",
            "Tournament rating before → after",
            "teamLink(row.code, row.nation, row.after)",
            "label: currentFirstRecordLabel(code, names)",
        ):
            self.assertIn(phrase, javascript)
        self.assertNotIn(
            "const tournamentLabels = new Map(",
            javascript,
        )
        self.assertNotIn(
            (
                "row.display_nation || "
                "row.nation, row.after"
            ),
            javascript,
        )

        builder = (
            ROOT / "scripts" / "build_site.py"
        ).read_text(encoding="utf-8")
        for phrase in (
            "return records[:500]",
            '"rating_changes": attributed_rating_changes',
            "published_rating_transitions",
            '"start_rating": start_rating',
            '"end_rating": end_rating',
        ):
            self.assertIn(phrase, builder)

    def test_records_lineage_labels_and_repository_version(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        readme = (
            ROOT / "README.md"
        ).read_text(encoding="utf-8")

        for phrase in (
            "Explore team peaks, No. 1 chronology and totals",
            'id="peak-team-search"',
            'id="record-list-team"',
            'id="record-list-competition"',
            "currentFirstRecordLabel",
            "peakRecordLabel",
            "How is the methodology tested?",
            "Current and historical rankings, tournament snapshots",
        ):
            self.assertIn(phrase, javascript)

        self.assertNotIn(
            "Methodology: "
            "${escapeHTML(summary.meta.methodology_version)}",
            javascript,
        )
        self.assertIn(
            "**Current methodology version:**",
            readme,
        )
        self.assertIn(
            self.summary["meta"]["methodology_version"],
            readme,
        )
        self.assertIn(
            "Tournament snapshots use the same published rating",
            readme,
        )

    def test_final_ui_and_consistency_contract(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")
        html = (
            ROOT / "public" / "index.html"
        ).read_text(encoding="utf-8")
        for marker in (
            'class="home-explore"',
            'role="tablist"',
            'role="tabpanel"',
            'aria-selected="true"',
            "No. 1 totals",
            "Highest-rated matches",
            'list="tournament-team-suggestions"',
            "search_names:",
            "Final snapshot:",
            "Pre-tournament snapshot:",
            "Current and historical teams",
            "const allTeams = summary.teams",
            'class="context-actions team-context-actions"',
            "summary.validation.retrospective.matches",
            "score-profile-details",
        ):
            self.assertIn(marker, javascript)

        self.assertNotIn(
            "The tournament ended on "
            "${validDate(selectedEdition.end)}. Rank change",
            javascript,
        )
        self.assertIn(
            "/* Final site-wide audit corrections */",
            stylesheet,
        )
        self.assertIn(
            "@media (max-width: 1180px)",
            stylesheet,
        )
        self.assertNotRegex(
            stylesheet,
            r"\.hide-mobile\s*\{[^}]*"
            r"display\s*:\s*none",
        )
        self.assertIn('class="footer-links"', html)
        audit = (
            ROOT
            / "scripts"
            / "audit_site_consistency.py"
        )
        self.assertTrue(audit.exists())
        subprocess.run(
            [
                sys.executable,
                str(audit),
                "--public",
                str(ROOT / "public"),
            ],
            cwd=ROOT,
            check=True,
        )

    def test_primary_names_have_responsive_type_hierarchy(self) -> None:
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")

        self.assertIn("/* Primary-name hierarchy */", stylesheet)
        for selector in (
            ".comparison-team-row select",
            ".comparison-add-panel select",
            ".team-picker select",
            ".comparison-pair-picker select",
            ".comparison-team-name",
            '.comparison-meetings td[data-label="Match"]',
            ".bar-row a",
            ".chart-inspector-value b",
            ".home-explore-links b",
            ".table-shell .team-link",
        ):
            self.assertIn(selector, stylesheet)

        primary_block = stylesheet.split(
            "/* Primary-name hierarchy */",
            1,
        )[1]
        self.assertIn("font-size: 17px;", primary_block)
        self.assertIn("font-size: 16px;", primary_block)
        self.assertIn("font-size: 15px;", primary_block)
        self.assertIn("text-transform: none;", primary_block)
        self.assertIn("@media (min-width: 721px)", primary_block)
        self.assertIn("@media (max-width: 720px)", primary_block)

    def test_progressive_responsive_interface_keeps_every_ranking_field(self) -> None:
        html = (
            ROOT / "public" / "index.html"
        ).read_text(encoding="utf-8")
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        main_navigation = html.split(
            '<nav id="site-nav"',
            1,
        )[1].split("</nav>", 1)[0]
        self.assertEqual(
            main_navigation.count('class="nav-group"'),
            2,
        )
        for label in ("Explore", "Forecasts"):
            self.assertIn(f"<summary>{label}</summary>", main_navigation)
        for route in (
            "rankings",
            "history",
            "tournaments",
            "matches",
            "fixtures",
            "records",
            "compare",
            "predict",
            "methodology",
            "faq",
            "about",
        ):
            self.assertIn(f'href="#/{route}"', main_navigation)

        for marker in (
            "function closeNavigation",
            'querySelectorAll(".nav-group[open]")',
            '"contains-current"',
            'class="ranking-cards"',
            'class="ranking-card-details"',
            "More ranking details",
            'class="section analysis-disclosure"',
            "Underlying strength estimate",
            "Top-choice W/D/L accuracy",
            "Tournament gains",
            "Home/away effect",
            "Start of selected year",
        ):
            self.assertIn(marker, javascript)
        self.assertEqual(
            javascript.count(
                'class="section analysis-disclosure"',
            ),
            2,
        )
        self.assertNotIn(
            'class="section analysis-disclosure" open',
            javascript,
        )
        self.assertEqual(javascript.count('id="faq-expand"'), 1)
        for obsolete in (
            "Current-model accuracy",
            "Estimate before uncertainty",
            "Best tournaments",
            "Home dependence",
            ">Start of year<",
        ):
            self.assertNotIn(obsolete, javascript)
        self.assertNotIn("Best tournaments", readme)

        history = javascript.split(
            "async function renderHistory",
            1,
        )[1].split(
            "function tournamentRankingsTable",
            1,
        )[0]
        self.assertNotIn("World Cup", history)
        self.assertNotIn("pre-tournament", history.lower())
        self.assertNotIn("post-tournament", history.lower())

        current_rankings = javascript.split(
            "function rankingsTable",
            1,
        )[1].split(
            "function renderRankings",
            1,
        )[0]
        for label in (
            "12-month change",
            "Underlying strength estimate",
            "Matches",
            "Recent form",
            "All-time peak",
        ):
            self.assertIn(label, current_rankings)

        historical_rankings = javascript.split(
            "function historicalRankingsTable",
            1,
        )[1].split(
            "async function renderHistory",
            1,
        )[0]
        tournament_rankings = javascript.split(
            "function tournamentRankingsTable",
            1,
        )[1].split(
            "const MAJOR_TOURNAMENT_PRECEDENCE",
            1,
        )[0]
        for block in (historical_rankings, tournament_rankings):
            for label in (
                "Underlying strength estimate",
                "Matches",
                "Recent form",
                "Last match",
            ):
                self.assertIn(label, block)

        for marker in (
            "--font-display:",
            "--font-numeric:",
            "--focus:",
            'font-feature-settings: "lnum" 1, "tnum" 1;',
            '"Fraunces Variable", Candara, Corbel',
            ".brand:hover .brand-mark",
            ".page-heading::after",
            ".chronology-cause",
            "Floral editorial presentation system",
            ".nav-submenu",
            ".ranking-desktop",
            ".ranking-cards",
            ".ranking-card-details",
            ".analysis-disclosure",
            "@media (max-width: 900px)",
            "@media (max-width: 720px)",
        ):
            self.assertIn(marker, stylesheet)
        definitions = set(
            re.findall(r"--([\w-]+)\s*:", stylesheet)
        )
        references = set(
            re.findall(r"var\(--([\w-]+)", stylesheet)
        )
        self.assertEqual(references - definitions, set())
        self.assertGreaterEqual(
            stylesheet.count("--result-win: #2f7657;"),
            2,
        )
        self.assertGreaterEqual(
            stylesheet.count("--result-loss: #a93b55;"),
            2,
        )

    def test_browser_application_replaces_initial_loading_shell(self) -> None:
        public = ROOT / "public"
        html = (public / "index.html").read_text(
            encoding="utf-8"
        )
        app_position = html.index('src="assets/app.js')
        analytics_position = html.index(
            'src="https://gc.zgo.at/count.js"'
        )
        self.assertLess(app_position, analytics_position)
        self.assertIn("__nfeloShowBootError", html)
        self.assertIn("fallback.src", html)

        subprocess.run(
            [
                "node",
                str(
                    ROOT
                    / "scripts"
                    / "smoke_browser_boot.js"
                ),
                str(public),
            ],
            cwd=ROOT,
            check=True,
        )

    def test_match_probability_bars_link_to_predict(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            ROOT / "public" / "assets" / "styles.css"
        ).read_text(encoding="utf-8")

        for phrase in (
            "const predictURL",
            "function probabilityHTML(values, prediction = null)",
            'class="probability-link"',
            "matchId = null",
            'query.set("match", String(matchId))',
            "matchId: match.id",
            "date: match.date",
            "date: fixture.date",
            "first: fixture.team1_code",
            'route.query.get("venue")',
            'route.query.get("class")',
            'route.query.get("match")',
            "maximumPredictionDate",
            "venue: String(home)",
        ):
            self.assertIn(phrase, javascript)

        self.assertNotIn(
            "date: previousISODate(match.date)",
            javascript,
        )
        normalized_javascript = " ".join(
            javascript.split()
        )
        self.assertNotIn(
            (
                "date: todayISO(), "
                "first: fixture.team1_code"
            ),
            normalized_javascript,
        )

        self.assertEqual(
            javascript.count(
                "Tap or click a probability bar "
                "for the full prediction and venue breakdown."
            ),
            2,
        )
        self.assertIn(
            "/* Match-table links to the full Predict view */",
            stylesheet,
        )
        self.assertIn(
            ".probability-link:focus-visible",
            stylesheet,
        )

    def test_alias_search_dynamic_suggestions_and_rank_sort(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        builder = (
            ROOT / "scripts" / "build_site.py"
        ).read_text(encoding="utf-8")

        for phrase in (
            "MANUAL_TEAM_ALIAS_GROUPS",
            '"USSR": "Soviet Union"',
            "attach_team_aliases(output, args.source)",
        ):
            self.assertIn(phrase, builder)

        for phrase in (
            "const foldSearch",
            "const shuffledExamples",
            "const initialiseTeamAliasSearch",
            "teamSearchText(team.code, team.nation)",
            'value="rank_change">Rank change',
            'if (sort === "rank_change")',
            "const populateMatchTeamOptions",
            "const updateMatchSearchPlaceholder",
            "publicTeamName(match.an)",
            "fixture.team1_code",
        ):
            self.assertIn(phrase, javascript)

        self.assertIn(
            "aliases",
            self.summary["teams"][0],
        )
        aliases = {
            alias
            for team in self.summary["teams"]
            for alias in team.get("aliases", [])
        }
        self.assertIn("USSR", aliases)
        self.assertIn("Soviet Union", aliases)
        self.assertIn("Swaziland", aliases)
        self.assertNotIn(
            '"nation":"USSR"',
            (
                ROOT
                / "public"
                / "data"
                / "summary.json"
            ).read_text(encoding="utf-8"),
        )

    def test_record_filters_labels_and_major_tournament_default(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        builder = (
            ROOT / "scripts" / "build_site.py"
        ).read_text(encoding="utf-8")

        for marker in (
            'id="peak-team-search"',
            'id="record-list-team"',
            'id="record-list-competition"',
            "recordTeamChoices",
            "recordCompetitions",
            "peakRecordLabel",
            "shuffledExamples(competitions)",
            "function defaultMajorTournamentFamily",
            "MAJOR_TOURNAMENT_PRECEDENCE",
            (
                "teamLink(peak.code, "
                "peak.display_nation || peak.nation)"
            ),
            (
                "teamLink(row.code, "
                "row.display_nation || row.nation)"
            ),
            (
                "teamLink(row.code, "
                "row.nation, "
                "row.after)"
            ),
        ):
            self.assertIn(marker, javascript)

        precedence = [
            "FIFA World Cup",
            "UEFA European Championship",
            "Copa América",
            "Africa Cup of Nations",
            "AFC Asian Cup",
            "CONCACAF Gold Cup",
            "OFC Nations Cup",
        ]
        precedence_start = javascript.index(
            "const MAJOR_TOURNAMENT_PRECEDENCE = ["
        )
        precedence_end = javascript.index(
            "];",
            precedence_start,
        )
        precedence_block = javascript[
            precedence_start:precedence_end
        ]
        positions = [
            precedence_block.index(f'"{name}"')
            for name in precedence
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(
            precedence_block.count('"'),
            len(precedence) * 2,
        )
        self.assertIn(
            "newestTime - candidate.time <= thirtyDays",
            javascript,
        )

        for marker in (
            "def model_verification_fingerprint",
            "def normalise_historical_public_names",
            "def attach_lineage_names",
            "def build_number_one_chronology",
            "Public label normalisation changed model verification data.",
        ):
            self.assertIn(marker, builder)

        for decade in (1950, 1960, 1970, 1980):
            payload = json.loads(
                (
                    self.data
                    / "matches"
                    / f"{decade}.json"
                ).read_text(encoding="utf-8")
            )
            soviet_rows = [
                row
                for row in payload["matches"]
                if row["a"] == "RU" or row["b"] == "RU"
            ]
            self.assertTrue(soviet_rows)
            for row in soviet_rows:
                if row["a"] == "RU":
                    self.assertEqual(
                        row["an"],
                        "Soviet Union",
                    )
                if row["b"] == "RU":
                    self.assertEqual(
                        row["bn"],
                        "Soviet Union",
                    )

            history = json.loads(
                (
                    self.data
                    / "rankings-history"
                    / f"{decade}.json"
                ).read_text(encoding="utf-8")
            )
            russian_lineage_names = {
                row["nation"]
                for row in (
                    history["opening"]
                    + history["events"]
                )
                if row["code"] == "RU"
            }
            self.assertNotIn(
                "Russia",
                russian_lineage_names,
            )
            if russian_lineage_names:
                self.assertEqual(
                    russian_lineage_names,
                    {"Soviet Union"},
                )

        number_one = {
            row["code"]: row
            for row in self.summary[
                "number_one_summary"
            ]
        }
        self.assertEqual(
            number_one["RU"]["nation"],
            "Soviet Union",
        )
        self.assertEqual(
            number_one["RU"]["included_names"],
            [],
        )
        self.assertEqual(
            number_one["DE"]["nation"],
            "Germany",
        )
        self.assertIn(
            "West Germany",
            number_one["DE"]["included_names"],
        )

        for team in self.summary["teams"]:
            self.assertTrue(team["lineage_names"])

    def test_public_metadata_and_discovery_files(self) -> None:
        public = ROOT / "public"
        html = (public / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="canonical"', html)
        self.assertIn('property="og:image"', html)
        self.assertIn(
            'rel="icon" href="favicon-2026.svg?v=20260729l1"',
            html,
        )
        self.assertIn(
            'rel="apple-touch-icon" sizes="180x180" '
            'href="apple-touch-icon-2026.png?v=20260729l1"',
            html,
        )
        self.assertIn(
            'rel="manifest" href="site.webmanifest?v=20260729l1"',
            html,
        )
        self.assertRegex(html, r'assets/styles\.css\?v=[0-9a-f]{12}')
        self.assertRegex(html, r'assets/app\.js\?v=[0-9a-f]{12}')
        self.assertEqual((public / "social-card.png").stat().st_size > 10_000, True)
        webmanifest = json.loads(
            (public / "site.webmanifest").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            {
                icon["src"]
                for icon in webmanifest["icons"]
            },
            {
                "icon-192-2026.png?v=20260729l1",
                "icon-512-2026.png?v=20260729l1",
            },
        )
        expected_png_sizes = {
            "apple-touch-icon-2026.png": (180, 180),
            "icon-192-2026.png": (192, 192),
            "icon-512-2026.png": (512, 512),
        }
        for filename, expected_size in expected_png_sizes.items():
            payload = (public / filename).read_bytes()
            self.assertEqual(
                payload[:8],
                b"\x89PNG\r\n\x1a\n",
            )
            self.assertEqual(
                (
                    int.from_bytes(payload[16:20], "big"),
                    int.from_bytes(payload[20:24], "big"),
                ),
                expected_size,
            )
        for filename in (
            "favicon-2026.ico",
            "favicon.ico",
        ):
            icon = (public / filename).read_bytes()
            self.assertEqual(icon[:4], b"\x00\x00\x01\x00")
        self.assertIn("Sitemap:", (public / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn("<urlset", (public / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertIn("Page not found", (public / "404.html").read_text(encoding="utf-8"))

    def test_tournament_defaults_empty_states_and_lineages(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")

        helper_start = javascript.index(
            "const MAJOR_TOURNAMENT_PRECEDENCE"
        )
        helper_end = javascript.index(
            "  async function renderTournaments",
            helper_start,
        )
        helper = javascript[helper_start:helper_end]
        scenarios = (
            'const family = (name, after, ongoing = false) => ({' + "\n"
            '  name,' + "\n"
            '  editions: [{ after, ongoing }],' + "\n"
            '});' + "\n"
            'const scenarios = [' + "\n"
            '  [' + "\n"
            '    family("FIFA World Cup", "2026-07-15"),' + "\n"
            '    family("Copa América", "2026-07-20", true),' + "\n"
            '  ],' + "\n"
            '  [' + "\n"
            '    family("UEFA European Championship", "2026-07-18", true),' + "\n"
            '    family("Copa América", "2026-07-20", true),' + "\n"
            '  ],' + "\n"
            '  [' + "\n"
            '    family("FIFA World Cup", "2026-07-01"),' + "\n"
            '    family("Copa América", "2026-07-20"),' + "\n"
            '  ],' + "\n"
            '  [' + "\n"
            '    family("FIFA World Cup", "2026-06-01"),' + "\n"
            '    family("Copa América", "2026-07-20"),' + "\n"
            '  ],' + "\n"
            '];' + "\n"
            'console.log(JSON.stringify(' + "\n"
            '  scenarios.map(' + "\n"
            '    (families) => defaultMajorTournamentFamily(families)?.name,' + "\n"
            '  ),' + "\n"
            '));' + "\n"
        )
        completed = subprocess.run(
            ["node", "-e", helper + scenarios],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertEqual(
            json.loads(completed.stdout),
            [
                "Copa América",
                "UEFA European Championship",
                "FIFA World Cup",
                "Copa América",
            ],
        )

        from build_site import (  # noqa: PLC0415
            annotate_ongoing_tournament_editions,
        )

        catalog = {
            "categories": [
                "Global championships",
                "Continental championships",
            ],
            "families": [
                {
                    "name": "FIFA World Cup",
                    "editions": [
                        {
                            "start": "2026-06-01",
                            "end": "2026-07-15",
                            "after": "2026-07-15",
                        }
                    ],
                },
                {
                    "name": "Copa América",
                    "editions": [
                        {
                            "start": "2026-07-01",
                            "end": "2026-07-20",
                            "after": "2026-07-20",
                        }
                    ],
                },
            ],
        }
        fixture_payload = {
            "fixtures": [
                {
                    "date": "2026-07-24",
                    "tournament_code": "",
                    "tournament_name": "Copa América",
                }
            ]
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            path.write_text(
                json.dumps(catalog),
                encoding="utf-8",
            )
            annotate_ongoing_tournament_editions(
                path,
                fixture_payload,
            )
            annotated = json.loads(
                path.read_text(encoding="utf-8")
            )
        by_name = {
            family["name"]: family
            for family in annotated["families"]
        }
        self.assertNotIn(
            "ongoing",
            by_name["FIFA World Cup"]["editions"][0],
        )
        self.assertTrue(
            by_name["Copa América"]["editions"][0]["ongoing"]
        )
        self.assertEqual(
            by_name["Copa América"]["editions"][0][
                "scheduled_through"
            ],
            "2026-07-24",
        )

        serbia_names = {
            "Serbia",
            "Serbia and Montenegro",
            "Yugoslavia",
        }
        serbia = next(
            team
            for team in self.summary["teams"]
            if serbia_names
            & set(
                [team["nation"]]
                + team.get("aliases", [])
                + team.get("lineage_names", [])
            )
        )
        self.assertTrue(
            serbia_names <= set(serbia["lineage_names"])
        )

        for marker in (
            "filteredEmptyState",
            "Change or clear the filters to see results.",
            "completePublicLineageNames",
            "formatPublicNameList",
            "team-lineage-note",
            "const lineageNamesByCode = new Map(",
            "source.length",
        ):
            self.assertIn(marker, javascript)

    def test_other_tournament_audit_and_historical_record_labels(self) -> None:
        registry = json.loads(
            (
                ROOT
                / "config"
                / "tournament_classification.json"
            ).read_text(encoding="utf-8")
        )
        catalog = json.loads(
            (
                ROOT
                / "public"
                / "data"
                / "tournaments"
                / "index.json"
            ).read_text(encoding="utf-8")
        )
        app = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")

        friendly = {
            "ABC", "ACV", "ADC", "AFD", "AIM", "ANF", "ARR",
            "AYA", "AZT", "BIC", "BLA", "BLR", "BLT", "BQR",
            "BRI", "CBG", "CDM", "CDS", "CFS", "CLG", "CNT",
            "CNY", "CON", "CRO", "CTS", "CVP", "DBT", "DNS",
            "DVC", "EAC", "ECO", "EDT", "ETR", "FFT", "GBT",
            "GLT", "GRC", "GRD", "INC", "INL", "IPC", "KOR",
            "MGC", "MJT", "MKR", "MLM", "N7C", "NBT", "NKB",
            "NRZ", "NSM", "NTC", "OCH", "OPS", "OSN", "PCC",
            "PMC", "PMT", "PRC", "PRS", "PST", "RMA", "RVC",
            "SAT", "SBA", "SLV", "SMB", "TRP", "UCT", "VFF",
            "VIC", "WUC",
        }
        competitive = {
            "ATL", "BG", "CMS", "FPG", "FRN", "GNF", "GSG",
            "ILG", "JCM", "LIT", "NKR", "RCD", "TCC", "TRE",
            "VWC", "WIT",
        }
        for code in friendly:
            self.assertEqual(
                registry["tournaments"][code]
                ["operational_class"],
                "friendly",
            )
        other_codes = {
            code
            for family in catalog["families"]
            if family["category"] == "Other tournaments"
            for code in family.get("source_codes", [])
        }
        self.assertEqual(other_codes, competitive)
        self.assertFalse(other_codes & friendly)

        self.assertNotIn("const tournamentLabels = new Map(", app)
        self.assertNotIn(
            "row.display_nation || row.nation, row.after",
            app,
        )
        self.assertIn(
            "teamLink(row.code, row.nation, row.after)",
            app,
        )
        self.assertIn(
            "label: currentFirstRecordLabel(code, names)",
            app,
        )

        world_cup = next(
            family
            for family in catalog["families"]
            if family["name"] == "FIFA World Cup"
        )
        edition_names = {
            edition["label"]: {
                participant["code"]: participant["nation"]
                for participant in edition["participants"]
            }
            for edition in world_cup["editions"]
        }
        self.assertEqual(
            edition_names["1954"]["DE"],
            "West Germany",
        )
        self.assertEqual(
            edition_names["2014"]["DE"],
            "Germany",
        )


if __name__ == "__main__":
    unittest.main()
