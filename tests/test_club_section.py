from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import unittest

from scripts.club_ledger import (
    ClubRegistry,
    EXPLICIT_SOURCE_ALIASES,
    display_country,
    normalise_name,
)
from scripts.club_model import (
    ClubRatingModel,
    aggregate_leg_weight,
    three_way_probabilities,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "clubs" / "data"


class ClubModelUnitTests(unittest.TestCase):
    def test_controlled_four_one_aggregate_is_discounted_but_not_erased(self) -> None:
        # First leg A 4-0 B; second leg is listed B v A and B wins 1-0.
        weight = aggregate_leg_weight(-4, -3, 0.1, 1.0, score=1.0)
        self.assertAlmostEqual(weight, 0.1 + 0.9 * math.exp(-3.0), places=12)
        self.assertGreater(weight, 0.1)
        self.assertLess(weight, 0.2)

    def test_confirming_result_and_comeback_keep_full_leg_weight(self) -> None:
        self.assertEqual(aggregate_leg_weight(-4, -5, 0.1, 1.0, score=0.0), 1.0)
        self.assertEqual(aggregate_leg_weight(-3, 1, 0.1, 1.0, score=1.0), 1.0)
        self.assertEqual(aggregate_leg_weight(-2, 0, 0.1, 1.0, score=1.0), 1.0)

    def test_probabilities_are_normalised_and_swap_invariant(self) -> None:
        for difference in (-900, -180, 0, 245, 1100):
            first = three_way_probabilities(difference, 0.285)
            swapped = three_way_probabilities(-difference, 0.285)
            self.assertAlmostEqual(sum(first), 1.0, places=13)
            self.assertAlmostEqual(first[0], swapped[2], places=13)
            self.assertAlmostEqual(first[1], swapped[1], places=13)
            self.assertAlmostEqual(first[2], swapped[0], places=13)

    def test_penalty_decision_is_learned_as_a_match_draw(self) -> None:
        self.assertEqual(ClubRatingModel._score(5, 4, "P"), 0.5)
        self.assertEqual(ClubRatingModel._score(2, 1, "F"), 1.0)

    def test_reviewed_aliases_are_country_scoped(self) -> None:
        self.assertEqual(
            EXPLICIT_SOURCE_ALIASES[("netherlands", normalise_name("PSV Eindhoven"))],
            normalise_name("PSV"),
        )
        self.assertEqual(
            EXPLICIT_SOURCE_ALIASES[("spain", normalise_name("Athletic Bilbao"))],
            normalise_name("Athletic Club"),
        )
        self.assertNotIn(("england", normalise_name("AFC Wimbledon")), EXPLICIT_SOURCE_ALIASES)
        self.assertEqual(
            EXPLICIT_SOURCE_ALIASES[("brazil", normalise_name("Athletico PR"))],
            normalise_name("Atletico Paranaense"),
        )

    def test_brazil_state_identity_prevents_same_name_interstate_merge(self) -> None:
        registry = ClubRegistry()
        rio = registry.add(
            "brazil:RJ:fluminense",
            "Fluminense",
            "brazil",
            resolution="test CBF identity",
        )
        maranhao = registry.resolve_brazil_team(
            "Fluminense",
            "MA",
            create_identity="brazil-state:MA:fluminense",
            resolution="test state identity",
            state_strict=True,
        )
        rio_from_state = registry.resolve_brazil_team(
            "Fluminense",
            "RJ",
            create_identity="brazil-state:RJ:fluminense",
            resolution="test state identity",
            state_strict=True,
        )
        self.assertNotEqual(maranhao, rio)
        self.assertEqual(rio_from_state, rio)


class ClubPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = [
            DATA / "meta.json",
            DATA / "rankings.json",
            DATA / "clubs.json",
            DATA / "matches" / "index.json",
            DATA / "records.json",
        ]
        missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
        if missing:
            raise AssertionError(
                "Build the site before running publication tests; missing " + ", ".join(missing)
            )
        cls.meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
        cls.rankings = json.loads((DATA / "rankings.json").read_text(encoding="utf-8"))["clubs"]
        cls.catalog = json.loads((DATA / "clubs.json").read_text(encoding="utf-8"))["clubs"]
        cls.match_index = json.loads(
            (DATA / "matches" / "index.json").read_text(encoding="utf-8")
        )

    def test_publication_has_expected_global_scale_and_span(self) -> None:
        self.assertGreater(self.meta["matches"], 1_500_000)
        self.assertGreater(self.meta["rated_clubs"], 9_000)
        self.assertGreater(self.meta["active_clubs"], 2_500)
        self.assertGreater(self.meta["associations"], 200)
        self.assertGreater(self.meta["competitions"], 250)
        self.assertGreater(self.meta["explicit_second_legs"], 5_000)
        self.assertLessEqual(self.meta["first_result"], "1871-12-31")
        self.assertGreaterEqual(self.meta["coverage"]["maximum_tier"], 8)

    def test_match_archive_index_is_complete(self) -> None:
        years = self.match_index["years"]
        self.assertEqual(self.match_index["schema"], self.meta["match_schema"])
        self.assertEqual(sum(row["count"] for row in years), self.meta["matches"])
        self.assertEqual(years[0]["year"], 1871)
        self.assertTrue((DATA / "matches" / years[-1]["file"]).is_file())

    def test_rankings_are_unique_sorted_and_identity_splits_are_fixed(self) -> None:
        codes = [club["code"] for club in self.rankings]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(
            [club["rank"] for club in self.rankings],
            list(range(1, len(self.rankings) + 1)),
        )
        self.assertEqual(
            [club["rating"] for club in self.rankings],
            sorted((club["rating"] for club in self.rankings), reverse=True),
        )
        names = [club["name"] for club in self.rankings]
        for canonical, rejected in (
            ("PSV", "PSV Eindhoven"),
            ("Mainz 05", "1. FSV Mainz 05"),
            ("Athletic Club", "Athletic Bilbao"),
            ("Sunderland", "Sunderland Afc"),
        ):
            self.assertIn(canonical, names)
            self.assertNotIn(rejected, names)

    def test_latest_match_rows_have_pre_match_probabilities_and_provenance(self) -> None:
        latest = self.match_index["years"][-1]
        payload = json.loads(
            (DATA / "matches" / latest["file"]).read_text(encoding="utf-8")
        )
        positions = {name: index for index, name in enumerate(self.match_index["schema"])}
        self.assertEqual(len(payload["matches"]), latest["count"])
        for row in payload["matches"][:: max(1, len(payload["matches"]) // 100)]:
            total = sum(
                float(row[positions[name]])
                for name in ("home_probability", "draw_probability", "away_probability")
            )
            self.assertAlmostEqual(total, 1.0, places=3)
            self.assertTrue(row[positions["source"]])
            self.assertTrue(row[positions["source_ref"]])

    def test_aggregate_record_examples_expose_context_and_weight(self) -> None:
        records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
        positions = {name: index for index, name in enumerate(records["match_schema"])}
        examples = records["aggregate_examples"]
        self.assertGreater(len(examples), 100)
        for row in examples:
            self.assertEqual(row[positions["leg"]], 2)
            self.assertIsNotNone(row[positions["aggregate_before_home"]])
            self.assertLess(row[positions["aggregate_weight"]], 1.0)

    def test_every_catalog_club_has_a_profile(self) -> None:
        self.assertEqual(len(self.catalog), self.meta["rated_clubs"])
        for club in self.catalog[:: max(1, len(self.catalog) // 200)]:
            self.assertTrue((DATA / "club" / f"{club['code']}.json").is_file())

    def test_model_release_and_fit_are_frozen(self) -> None:
        parameters = self.meta["parameters"]
        self.assertEqual(parameters["version"], "2026-08-11-global-club-v3")
        self.assertEqual(parameters["k_factor"], 18.0)
        self.assertEqual(parameters["country_share"], 0.65)
        self.assertEqual(parameters["confederation_share"], 0.5)
        self.assertEqual(parameters["home_advantage_domestic"], 45.0)
        self.assertEqual(parameters["home_advantage_cross_border"], 80.0)
        self.assertEqual(parameters["aggregate_floor"], 0.0)
        self.assertEqual(parameters["aggregate_scale"], 1.0)
        self.assertEqual(self.meta["fit"]["validation_period"], ["2018-01-01", "2022-12-31"])

    def test_shell_routes_and_root_cross_link_are_present(self) -> None:
        shell = (ROOT / "public" / "clubs" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "public" / "clubs" / "clubs.js").read_text(encoding="utf-8")
        root_shell = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        sitemap = (ROOT / "public" / "sitemap.xml").read_text(encoding="utf-8")
        for route in (
            "rankings", "history", "clubs", "matches", "records", "compare",
            "predict", "methodology", "sources",
        ):
            self.assertIn(f"#/" + route, shell)
        self.assertIn("/clubs/", root_shell)
        self.assertIn("https://nfelo.github.io/clubs/", sitemap)
        self.assertIn("aggregate_weight", script)
        self.assertIn('../assets/critical.css', shell)
        self.assertIn('../assets/styles.css', shell)
        self.assertIn('class="site-header"', shell)
        self.assertIn('class="site-nav"', shell)
        self.assertIn("useGrouping: false", script)
        self.assertIn("minimumFractionDigits: 1", script)
        club_css = (ROOT / "public" / "clubs" / "clubs.css").read_text(encoding="utf-8")
        self.assertIn("table th { position: static; }", club_css)

    def test_public_country_names_match_nfelo_conventions(self) -> None:
        expected = {
            "korea-republic": "South Korea",
            "korea-dpr": "North Korea",
            "czech-republic": "Czechia",
            "turkey": "Türkiye",
            "cape-verde": "Cabo Verde",
            "democratic-republic-of-congo": "DR Congo",
            "taiwan": "Chinese Taipei",
        }
        for raw, public in expected.items():
            self.assertEqual(display_country(raw), public)

    def test_club_browser_javascript_parses(self) -> None:
        subprocess.run(
            ["node", "--check", "public/clubs/clubs.js"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_repository_brazil_snapshot_matches_its_manifest(self) -> None:
        snapshot = ROOT / "source" / "club_brazil.csv.gz"
        manifest = json.loads(
            (ROOT / "source" / "club_brazil.manifest.json").read_text(encoding="utf-8")
        )
        self.assertGreater(manifest["matches"], 18_000)
        self.assertEqual(snapshot.stat().st_size, manifest["snapshot_bytes"])
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), manifest["snapshot_sha256"])

    def test_repository_brazil_state_snapshot_matches_its_manifest(self) -> None:
        snapshot = ROOT / "source" / "club_brazil_states.csv.gz"
        manifest = json.loads(
            (ROOT / "source" / "club_brazil_states.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertGreater(manifest["matches"], 6_500)
        self.assertGreaterEqual(manifest["competitions"], 14)
        self.assertEqual(snapshot.stat().st_size, manifest["snapshot_bytes"])
        self.assertEqual(
            hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            manifest["snapshot_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
