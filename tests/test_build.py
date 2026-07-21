from __future__ import annotations

from html.parser import HTMLParser
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger import read_matches, read_successors, read_supplemental_matches  # noqa: E402
from forecast_layer import (  # noqa: E402
    outcome_preserving_pool,
    poisson_wdl,
    raked_score_matrix,
)
from fetch_sources import fetch_world_table  # noqa: E402
from model import joint_gaussian_update, three_way_probabilities  # noqa: E402
from open_results import merge_record, venue_country  # noqa: E402


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
        self.assertTrue(all(math.isfinite(value) for value in self.state["means"]))
        covariance = np.asarray(self.state["covariance"], dtype=np.float64).reshape(count, count)
        self.assertTrue(np.allclose(covariance, covariance.T, atol=1e-8))
        self.assertGreaterEqual(float(np.linalg.eigvalsh(covariance).min()), -1e-5)
        self.assertEqual(
            meta["methodology_version"],
            "2026-07-20-friendly-information-0.63901",
        )
        self.assertAlmostEqual(
            self.summary["parameters"]["network"]["friendly_information_ratio"],
            0.63901,
            places=10,
        )

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
        self.assertIn('document.getElementById("history-next").disabled = chosen >= index.last;', javascript)

    def test_public_readme_avoids_internal_setup_language(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        normalised_readme = " ".join(readme.split())
        self.assertNotIn("codex", readme)
        self.assertNotIn("bake-off", readme)
        self.assertIn("nested historical holdout", normalised_readme)
        self.assertIn("retrospective diagnostic", normalised_readme)
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
            historical_opponents.intersection({"USSR", "Czechoslovakia", "Yugoslavia"})
        )

    def test_probability_swap_invariance(self) -> None:
        first = three_way_probabilities(137.5, 12_345.0, 2026, friendly=False)
        second = three_way_probabilities(-137.5, 12_345.0, 2026, friendly=False)
        self.assertAlmostEqual(float(first[0]), float(second[2]), places=12)
        self.assertAlmostEqual(float(first[1]), float(second[1]), places=12)
        self.assertAlmostEqual(float(first[2]), float(second[0]), places=12)
        self.assertAlmostEqual(float(first.sum()), 1.0, places=12)

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
        layer = self.state["forecast_layer"]
        calibration = layer["calibration"]
        self.assertEqual(layer["release"], "selected-through-2019")
        self.assertEqual(
            (calibration["training_first_year"], calibration["training_last_year"]),
            (2018, 2025),
        )
        self.assertEqual(calibration["training_matches"], 7922)
        # Powell can differ by a few millionths across BLAS/libm builds while
        # producing indistinguishable forecasts. Keep this tight enough to
        # detect a real release change without requiring bitwise optimisation.
        self.assertAlmostEqual(
            calibration["draw_log_tilt"], 0.15176472, delta=0.00005
        )
        self.assertAlmostEqual(
            calibration["nfelo_weight"], 0.5257464, delta=0.00005
        )
        self.assertEqual(len(layer["attack"]), len(self.state["codes"]))
        self.assertEqual(len(layer["defence"]), len(self.state["codes"]))
        self.assertEqual(len(layer["last_day"]), len(self.state["codes"]))

        losses = []
        matches = 0
        for path in sorted((self.data / "matches").glob("[0-9][0-9][0-9][0-9].json")):
            for match in json.loads(path.read_text(encoding="utf-8"))["matches"]:
                if match["year"] < 1960 or match["date"] > "2026-07-11":
                    continue
                outcome = 0 if match["sa"] > match["sb"] else 1 if match["sa"] == match["sb"] else 2
                losses.append(-math.log(max(match["p"][outcome], 1e-15)))
                matches += 1
        self.assertEqual(matches, 46_801)
        validation = self.summary["validation"]
        actual_log_loss = sum(losses) / matches
        self.assertAlmostEqual(
            actual_log_loss, validation["retrospective"]["log_loss"], places=6
        )
        self.assertAlmostEqual(actual_log_loss, 0.88025, delta=0.0003)
        self.assertEqual(validation["primary_evidence"], "nested_historical_holdout")
        self.assertIn(
            "rolling historical holdout",
            validation["nested"]["description"].lower(),
        )
        self.assertIn(
            "final constants replayed",
            validation["retrospective"]["description"].lower(),
        )
        self.assertEqual(validation["retrospective"]["unknown_dates"], "sequential")

    def test_faq_page_is_complete_and_discoverable(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        sitemap = (ROOT / "public" / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn('href="#/faq">FAQ</a>', html)
        self.assertIn('case "faq": renderFAQ(); break;', javascript)
        self.assertEqual(javascript.count('question: "'), 29)
        self.assertIn("Search questions", javascript)
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
        self.assertIn("Relevant change-date result(s)", javascript)
        self.assertIn("Swipe to see every column", javascript)
        self.assertTrue(all("match" in spell for spell in spells))
        summaries = self.summary["number_one_summary"]
        self.assertTrue(summaries)
        self.assertEqual(summaries, sorted(
            summaries, key=lambda row: (-row["days"], row["first"], row["nation"])
        ))
        self.assertEqual(sum(row["spells"] for row in summaries), len(spells))
        self.assertIn("Leadership is determined jointly after all results on each date", javascript)
        brazil_2013 = next(
            spell for spell in spells
            if spell["code"] == "BR" and spell["from"] == "2013-11-19"
        )
        self.assertEqual(
            {brazil_2013["match"]["team1_code"], brazil_2013["match"]["team2_code"]},
            {"ES", "ZA"},
        )
        self.assertEqual(
            sorted((brazil_2013["match"]["score1"], brazil_2013["match"]["score2"])),
            [0, 1],
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
        self.assertIn('const filtering = view === "numberones";', javascript)
        self.assertNotIn('view === "numberones" || view === "numberonesummary"', javascript)
        self.assertIn("From date cannot be after To date.", javascript)
        self.assertIn("To date cannot be before From date.", javascript)
        self.assertIn("from > to", javascript)
        self.assertIn('number-one-from-calendar").max', javascript)
        self.assertIn('number-one-to-calendar").min', javascript)

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
        for phrase in (
            "Add scoring tendencies",
            "changes probabilities only",
            "Hidden attack and defence forecast",
            "Annual calibration and boundary gate",
            "preceding eight complete calendar years",
            "joint date update",
            "nested historical holdout",
            "retrospective replay",
            "Public rating and match forecast",
            "marginal posterior uncertainty",
            "Why friendlies use 0.63901",
            "0.63901",
        ):
            self.assertIn(phrase, javascript)
        self.assertIn("applyForecastLayer", javascript)

    def test_rating_forecast_explanation_and_validation_comparison(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        for phrase in (
            "Why can the lower-rated team be the forecast favourite?",
            "Why can a lower-rated team be the forecast favourite?",
            "ratingForecastExplanation()",
            "Best tested scalar Elo",
            "G-Elo comparison",
            "Published World Football Elo forecast",
            "precisePercent(nested.published_wfe_accuracy)",
            "yearNumber(f.calibration.year)",
            "yearNumber(f.calibration.training_first_year)",
            "yearNumber(f.calibration.training_last_year)",
        ):
            self.assertIn(phrase, javascript)
        self.assertNotIn("number(f.calibration.year)", javascript)
        self.assertNotIn("number(f.calibration.training_first_year)", javascript)
        self.assertNotIn("number(f.calibration.training_last_year)", javascript)
        self.assertNotIn("Does that mean a friendly is treated exactly like a World Cup match?", javascript)
        nested = self.summary["validation"]["nested"]
        self.assertEqual(nested["best_scalar_elo_accuracy"], 0.58527)
        self.assertEqual(nested["g_elo_log_loss"], 0.895187)
        self.assertEqual(nested["g_elo_accuracy"], 0.58779)
        self.assertEqual(nested["published_wfe_accuracy"], 0.58804)

    def test_same_date_and_publication_safeguards_are_present(self) -> None:
        model = (ROOT / "scripts" / "model.py").read_text(encoding="utf-8")
        forecast = (ROOT / "scripts" / "forecast_layer.py").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn("debut = self.debut_mean(year)", model)
        self.assertIn("self.initialise_with(index, first_match.day, debut)", model)
        self.assertIn("joint_gaussian_update(", model)
        self.assertIn("FRIENDLY_INFORMATION_RATIO = 0.63901", model)
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
        model = (ROOT / "scripts" / "model.py").read_text(encoding="utf-8")
        self.assertIn(
            "marginal_se = math.sqrt(max(0.0, float(self.covariance[index, index])))",
            model,
        )
        self.assertIn("rating = adjusted_mean - CONFIDENCE_Z * marginal_se", model)
        self.assertNotIn("strength_rating =", model)
        self.assertNotIn("record_rating", model)

        peaks = self.summary["peaks"]
        early_british = [
            peak for peak in peaks
            if peak["code"] in {"EN", "SC", "WA", "EI"}
            and peak["date"] < "1914-07-28"
        ]
        self.assertTrue(early_british)
        self.assertLess(max(peak["rating"] for peak in early_british), 2040.0)
        self.assertNotIn(peaks[0], early_british)
        self.assertLessEqual(
            sum(peak in early_british for peak in peaks[:20]),
            1,
        )
        top_codes = [peak["code"] for peak in peaks[:5]]
        self.assertEqual(set(top_codes[:2]), {"ES", "BR"})
        self.assertIn("EN", top_codes)

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

    def test_historical_rankings_use_contemporary_names(self) -> None:
        history = json.loads((self.data / "rankings-history" / "1990.json").read_text(encoding="utf-8"))
        names = {row["nation"] for row in history["opening"]} | {
            row["nation"] for row in history["events"]
        }
        self.assertIn("West Germany", names)
        self.assertIn("USSR", names)
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
            (self.data / "tournaments" / "index.json").read_text(
                encoding="utf-8"
            )
        )
        owners: dict[str, set[str]] = {}
        by_name = {
            family["name"]: family
            for family in catalog["families"]
        }
        for family in catalog["families"]:
            for code in family.get("source_codes", []):
                owners.setdefault(code, set()).add(family["name"])
            for edition in family["editions"]:
                participants = edition.get("participants", [])
                self.assertEqual(
                    {item["code"] for item in participants},
                    set(edition["teams"]),
                )
                self.assertEqual(
                    len(participants),
                    len(edition["teams"]),
                )
                self.assertTrue(
                    all(item["nation"] for item in participants)
                )

        self.assertEqual(
            set(by_name["Olympic Games"]["source_codes"]),
            {"OG"},
        )
        self.assertNotIn("OQ", owners)
        self.assertNotIn("OGC", owners)

        expected_owners = {
            "BGC": "Bangabandhu Gold Cup",
            "NGC": "Nehru Gold Cup",
            "PRG": "President's Gold Cup",
            "CFC": "CONCACAF Cup",
            "SQC": "AFC Challenge Cup",
            "NQC": "Central American Cup",
            "NQU": "UNCAF Nations Cup",
            "FQC": "Caribbean Cup",
            "FQB": "Caribbean Championship",
        }
        for code, family_name in expected_owners.items():
            if code in owners:
                self.assertEqual(owners[code], {family_name})

        gold_codes = set(
            by_name["CONCACAF Gold Cup"]["source_codes"]
        )
        self.assertFalse(
            gold_codes & {"BGC", "NGC", "PRG"}
        )

        pure_qualifier_codes = {
            "OQ", "GCQ", "CHQ", "CHT", "TGQ", "AEQ",
            "SEQ", "SET", "CLQ", "NLQ", "UNQ", "UNT",
            "EAQ", "EAT", "ARQ", "AQT",
        }
        self.assertFalse(pure_qualifier_codes & owners.keys())

        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '<option value="rating">Rating</option>'
            '<option value="rating_gain">Rating gain</option>'
            '<option value="name">Name</option>',
            javascript,
        )
        self.assertIn(
            '<option value="rating">Rating</option>'
            '<option value="name">Name</option>',
            javascript,
        )
        self.assertIn("editionParticipants", javascript)
        self.assertIn(
            "including teams without a published rating",
            javascript,
        )


    def test_best_tournament_records_and_rating_sort_options(self) -> None:
        records = self.summary.get("best_tournaments", [])
        self.assertTrue(records)
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
            ),
        )
        self.assertTrue(
            all(row["rating_gain"] > 0 for row in records)
        )
        self.assertTrue(
            all(
                abs(
                    row["after_rating"]
                    - row["before_rating"]
                    - row["rating_gain"]
                ) < 1e-7
                for row in records
            )
        )
        self.assertTrue(
            all(
                row["tournament_id"]
                and row["edition_id"]
                and row["code"]
                for row in records
            )
        )

        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'data-record="tournaments"',
            javascript,
        )
        self.assertIn(
            "function bestTournamentTable",
            javascript,
        )
        self.assertIn(
            "summary.best_tournaments",
            javascript,
        )
        self.assertNotIn(
            '<option value="mean">Adjusted estimate</option>',
            javascript,
        )
        self.assertNotIn(
            '["rating", "mean", "matches", "name"]',
            javascript,
        )

    def test_public_metadata_and_discovery_files(self) -> None:
        public = ROOT / "public"
        html = (public / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="canonical"', html)
        self.assertIn('property="og:image"', html)
        self.assertIn('rel="icon"', html)
        self.assertRegex(html, r'assets/styles\.css\?v=[0-9a-f]{12}')
        self.assertRegex(html, r'assets/app\.js\?v=[0-9a-f]{12}')
        self.assertEqual((public / "social-card.png").stat().st_size > 10_000, True)
        self.assertIn("Sitemap:", (public / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn("<urlset", (public / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertIn("Page not found", (public / "404.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
