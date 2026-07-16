from __future__ import annotations

from html.parser import HTMLParser
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger import read_matches, read_successors, read_supplemental_matches  # noqa: E402
from forecast_layer import outcome_preserving_pool, poisson_wdl  # noqa: E402
from model import three_way_probabilities  # noqa: E402
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
        self.assertNotIn("codex", readme)
        self.assertNotIn("bake-off", readme)

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
        final, reverted = outcome_preserving_pool(network, score, 0.55)
        self.assertTrue(reverted)
        self.assertTrue(np.array_equal(final, network))

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
            calibration["draw_log_tilt"], 0.1502408248, delta=0.00005
        )
        self.assertAlmostEqual(
            calibration["nfelo_weight"], 0.5655029347, delta=0.00005
        )
        self.assertEqual(len(layer["attack"]), len(self.state["codes"]))
        self.assertEqual(len(layer["defence"]), len(self.state["codes"]))
        self.assertEqual(len(layer["last_day"]), len(self.state["codes"]))

        losses = []
        correct = 0
        matches = 0
        for path in sorted((self.data / "matches").glob("[0-9][0-9][0-9][0-9].json")):
            for match in json.loads(path.read_text(encoding="utf-8"))["matches"]:
                if match["year"] < 1960 or match["date"] > "2026-07-11":
                    continue
                outcome = 0 if match["sa"] > match["sb"] else 1 if match["sa"] == match["sb"] else 2
                losses.append(-math.log(max(match["p"][outcome], 1e-15)))
                correct += int(max(range(3), key=lambda index: match["p"][index]) == outcome)
                matches += 1
        self.assertEqual(matches, 46_801)
        # Daily results legitimately move this aggregate by a few millionths.
        # Allow harmless data drift while still detecting a material forecast change.
        self.assertAlmostEqual(
            sum(losses) / matches, 0.8807100827, delta=0.00005
        )
        # Top-pick accuracy is discontinuous: a few-millionths optimiser change
        # can move one near-tied match across the argmax boundary even though
        # the probability forecast and aggregate log loss are unchanged.
        self.assertLessEqual(abs(correct - 27_677), 1)

    def test_faq_page_is_complete_and_discoverable(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        sitemap = (ROOT / "public" / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn('href="#/faq">FAQ</a>', html)
        self.assertIn('case "faq": renderFAQ(); break;', javascript)
        self.assertEqual(javascript.count('question: "'), 25)
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
        self.assertIn('href="#/faq">Questions? Read the FAQ →</a>', javascript)
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
        self.assertIn("Change-triggering match", javascript)
        self.assertIn("Swipe to see every column", javascript)
        self.assertTrue(all("match" in spell for spell in spells))
        summaries = self.summary["number_one_summary"]
        self.assertTrue(summaries)
        self.assertEqual(summaries, sorted(
            summaries, key=lambda row: (-row["days"], row["first"], row["nation"])
        ))
        self.assertEqual(sum(row["spells"] for row in summaries), len(spells))
        self.assertIn("Leadership is determined after all matches on each date", javascript)
        brazil_2010 = next(
            spell for spell in spells
            if spell["code"] == "BR" and spell["from"] == "2010-11-17"
        )
        self.assertEqual(
            {brazil_2010["match"]["team1_code"], brazil_2010["match"]["team2_code"]},
            {"ES", "PT"},
        )
        self.assertEqual(
            sorted((brazil_2010["match"]["score1"], brazil_2010["match"]["score2"])),
            [0, 4],
        )

    def test_methodology_explains_probability_only_layer_in_plain_english(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        for phrase in (
            "Check how the teams have been scoring",
            "changes match probabilities only",
            "Hidden attack and defence layer",
            "Annual calibration, blend and safety rule",
            "preceding eight complete calendar years",
        ):
            self.assertIn(phrase, javascript)
        self.assertIn("applyForecastLayer", javascript)

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
        self.assertIn("<title>Rankings · Network Football Elo</title>", rankings)
        self.assertIn("https://nfelo.github.io/rankings/", rankings)
        self.assertIn("<title>Argentina · Network Football Elo</title>", argentina)
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

    def test_historical_rankings_are_chunked_by_year(self) -> None:
        index = json.loads((self.data / "rankings-history" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["first"][:4], str(index["years"][0]["year"]))
        self.assertEqual(index["last"][:4], str(index["years"][-1]["year"]))
        self.assertGreaterEqual(len(index["world_cups"]), 20)
        latest = json.loads((self.data / "rankings-history" / index["years"][-1]["file"]).read_text(encoding="utf-8"))
        self.assertEqual(latest["year"], int(index["last"][:4]))
        self.assertTrue(latest["opening"])
        self.assertEqual(latest["events"], sorted(latest["events"], key=lambda row: (row["date"], row["id"], row["code"])))
        self.assertTrue(all(row["matches"] >= 30 for row in latest["opening"] + latest["events"]))

    def test_history_date_mask_and_world_cup_order(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn("formatHistoryDateInput", javascript)
        self.assertIn('maxlength="10"', javascript)
        self.assertIn("Day must be between 01 and 31.", javascript)
        self.assertIn("Month must be between 01 and 12.", javascript)
        after = '`<option value="${cup.after}">After ${cup.year} World Cup</option>`'
        before = '`<option value="${cup.before}">Before ${cup.year} World Cup</option>`'
        self.assertLess(javascript.index(after), javascript.index(before))

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
