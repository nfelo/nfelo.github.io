from __future__ import annotations

from html.parser import HTMLParser
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger import read_matches, read_successors, read_supplemental_matches  # noqa: E402
from model import three_way_probabilities  # noqa: E402


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
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        self.assertEqual(peaks, sorted(peaks, reverse=True))
        self.assertEqual(matches, sorted(matches, reverse=True))
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
                self.assertAlmostEqual(sum(match["p"]), 1.0, places=6)
                self.assertNotIn(match["id"], ids)
                ids.add(match["id"])
        self.assertEqual(total, self.summary["meta"]["matches"])

    def test_probability_swap_invariance(self) -> None:
        first = three_way_probabilities(137.5, 12_345.0, 2026, friendly=False)
        second = three_way_probabilities(-137.5, 12_345.0, 2026, friendly=False)
        self.assertAlmostEqual(float(first[0]), float(second[2]), places=12)
        self.assertAlmostEqual(float(first[1]), float(second[1]), places=12)
        self.assertAlmostEqual(float(first[2]), float(second[0]), places=12)
        self.assertAlmostEqual(float(first.sum()), 1.0, places=12)

    def test_upcoming_fixtures_are_sorted_and_probabilistic(self) -> None:
        fixtures = self.fixtures["fixtures"]
        self.assertGreaterEqual(len(fixtures), 2)
        self.assertEqual(
            fixtures,
            sorted(fixtures, key=lambda item: (item["date"], item["team1_name"])),
        )
        for fixture in fixtures:
            self.assertGreater(fixture["date"], self.summary["meta"]["results_through"])
            self.assertAlmostEqual(sum(fixture["probabilities"]), 1.0, places=7)
            self.assertIn(fixture["team1_code"], self.state["codes"])
            self.assertIn(fixture["team2_code"], self.state["codes"])

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

    def test_public_metadata_and_discovery_files(self) -> None:
        public = ROOT / "public"
        html = (public / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="canonical"', html)
        self.assertIn('property="og:image"', html)
        self.assertIn('rel="icon"', html)
        self.assertEqual((public / "social-card.png").stat().st_size > 10_000, True)
        self.assertIn("Sitemap:", (public / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn("<urlset", (public / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertIn("Page not found", (public / "404.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
