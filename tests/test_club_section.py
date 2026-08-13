from __future__ import annotations

import hashlib
import gzip
from html import unescape
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import duckdb

from scripts.club_ledger import (
    ClubRegistry,
    COUNTRY_CODE_ALIASES,
    EXPLICIT_SOURCE_ALIASES,
    canonical_club_name,
    canonical_competition_name,
    clean_country,
    display_country,
    football_confederation,
    normalise_name,
)
from scripts.club_model import (
    ClubRatingModel,
    aggregate_leg_weight,
    load_club_config,
    run_club_model,
    three_way_probabilities,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "clubs" / "data"


def read_json(path: Path) -> object:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def anchor_labels(document: str, pattern: str) -> list[str]:
    match = re.search(pattern, document, flags=re.DOTALL)
    if not match:
        return []
    return [
        unescape(re.sub(r"<[^>]+>", "", label)).strip()
        for label in re.findall(r"<a\b[^>]*>(.*?)</a>", match.group(0), flags=re.DOTALL)
    ]


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
        self.assertEqual(ClubRatingModel._score(0, 0, "P?"), 0.5)
        self.assertEqual(ClubRatingModel._score(2, 1, "F"), 1.0)

    def test_domestic_tier_learning_is_anchored_on_tier_one(self) -> None:
        model = object.__new__(ClubRatingModel)
        model.tier_rating = {
            ("england", 1): 35.0,
            ("england", 2): -25.0,
            ("england", 3): -80.0,
            ("spain", 1): -12.0,
            ("spain", 2): -72.0,
            ("orphan", 2): 9.0,
        }
        model._centre_tier_components()
        self.assertEqual(model.tier_rating[("england", 1)], 0.0)
        self.assertEqual(model.tier_rating[("england", 2)], -60.0)
        self.assertEqual(model.tier_rating[("england", 3)], -115.0)
        self.assertEqual(model.tier_rating[("spain", 1)], 0.0)
        self.assertEqual(model.tier_rating[("spain", 2)], -60.0)
        self.assertEqual(model.tier_rating[("orphan", 2)], 9.0)

    def test_atomic_model_database_reopens_with_every_final_table(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as directory:
            ledger = Path(directory) / "ledger.duckdb"
            output = Path(directory) / "model.duckdb"
            connection = duckdb.connect(str(ledger))
            connection.execute(
                """
                CREATE TABLE clubs(
                    club INTEGER,code VARCHAR,name VARCHAR,country VARCHAR,
                    country_name VARCHAR,country_code VARCHAR,continent VARCHAR,
                    identity VARCHAR,resolution VARCHAR
                )
                """
            )
            connection.executemany(
                "INSERT INTO clubs VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (0, "a", "Alpha", "england", "England", "EN", "Europe", "a", "test"),
                    (1, "b", "Beta", "spain", "Spain", "ES", "Europe", "b", "test"),
                ],
            )
            connection.execute(
                """
                CREATE TABLE matches(
                    match_id VARCHAR,day DATE,season INTEGER,home INTEGER,away INTEGER,
                    home_goals SMALLINT,away_goals SMALLINT,competition VARCHAR,
                    competition_key VARCHAR,kind VARCHAR,home_tier SMALLINT,
                    away_tier SMALLINT,neutral BOOLEAN,cross_border BOOLEAN,
                    status VARCHAR,leg SMALLINT,tie_key VARCHAR,round_name VARCHAR,
                    source VARCHAR,source_ref VARCHAR,aggregate_before_home SMALLINT,
                    aggregate_after_home SMALLINT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO matches VALUES (
                    'm1',DATE '2020-01-01',2020,0,1,2,1,'Test Cup','test',
                    'continental',1,1,false,true,'F',0,NULL,'Final','test','m1',NULL,NULL
                )
                """
            )
            connection.close()

            result = run_club_model(
                ledger,
                load_club_config(ROOT / "config" / "club_model.json"),
                output_database=output,
            )
            self.assertEqual(result["matches"], 1)
            verifier = duckdb.connect(str(output), read_only=True)
            try:
                tables = {row[0] for row in verifier.execute("SHOW TABLES").fetchall()}
                self.assertTrue({
                    "rated_matches", "year_openings", "current_club_ratings",
                    "current_country_ratings", "current_confederation_ratings",
                }.issubset(tables))
                self.assertEqual(
                    verifier.execute("SELECT count(*) FROM rated_matches").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    verifier.execute(
                        "SELECT count(*) FROM current_club_ratings"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    verifier.execute(
                        "SELECT count(*) FROM current_country_ratings"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    verifier.execute(
                        "SELECT count(*) FROM current_confederation_ratings"
                    ).fetchone()[0],
                    1,
                )
            finally:
                verifier.close()
            self.assertFalse(Path(f"{output}.wal").exists())
            self.assertEqual(
                list(output.parent.glob(f".{output.name}.building-*")),
                [],
            )

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
        for country, source_name, canonical_name in (
            ("italy", "FC Internazionale Milano", "Inter"),
            ("portugal", "Sport Lisboa e Benfica", "Benfica"),
            ("spain", "Real Betis Balompié", "Real Betis"),
            ("france", "Racing Club de Lens", "Lens"),
            ("netherlands", "Feyenoord Rotterdam", "Feyenoord"),
        ):
            self.assertEqual(
                EXPLICIT_SOURCE_ALIASES[(country, normalise_name(source_name))],
                normalise_name(canonical_name),
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

    def test_metadata_is_backfilled_after_all_sources_are_loaded(self) -> None:
        registry = ClubRegistry()
        bournemouth = registry.add(
            "backbone:AFC Bournemouth (England)",
            "AFC Bournemouth",
            "england",
        )
        registry.add(
            "backbone:Arsenal (England)",
            "Arsenal",
            "england",
            "ENG",
            "Europe",
        )
        registry.finalise_metadata({"england": "EN"})
        self.assertEqual(registry.clubs[bournemouth].continent, "Europe")
        self.assertEqual(registry.clubs[bournemouth].country_code, "EN")

    def test_association_aliases_and_football_affiliations_are_canonical(self) -> None:
        self.assertEqual(clean_country("Cabo Verde"), "cape-verde")
        self.assertEqual(clean_country("Cape Verde Islands"), "cape-verde")
        self.assertEqual(clean_country("Ireland Republic"), "ireland")
        self.assertEqual(football_confederation("ireland"), "Europe")
        self.assertEqual(football_confederation("cape-verde"), "Africa")
        self.assertEqual(football_confederation("colombia"), "South America")
        for code, association in (
            ("AND", "andorra"), ("ARM", "armenia"),
            ("AZE", "azerbaijan"), ("BUL", "bulgaria"),
            ("FRO", "faroe-islands"), ("GIB", "gibraltar"),
            ("LTU", "lithuania"), ("SMR", "san-marino"),
        ):
            self.assertEqual(COUNTRY_CODE_ALIASES[code], association)

    def test_reviewed_continental_only_club_gets_association_metadata(self) -> None:
        registry = ClubRegistry()
        klaksvik = registry.add(
            "continental-only:ki-klaksvik",
            "KI Klaksvik",
            "",
        )
        registry.finalise_metadata({"faroe islands": "FO"})
        club = registry.clubs[klaksvik]
        self.assertEqual(club.country, "faroe-islands")
        self.assertEqual(club.country_code, "FO")
        self.assertEqual(club.continent, "Europe")

    def test_reviewed_public_club_names_are_canonical(self) -> None:
        self.assertEqual(canonical_club_name("brazil", "Se Palmeiras"), "Palmeiras")
        self.assertEqual(canonical_club_name("congo-dr", "Tp Mazembe"), "TP Mazembe")

    def test_public_competition_names_preserve_acronyms_and_nation_labels(self) -> None:
        self.assertEqual(canonical_competition_name("Uefa Champions League"), "UEFA Champions League")
        self.assertEqual(canonical_competition_name("Fa Cup"), "FA Cup")
        self.assertEqual(canonical_competition_name("Laliga"), "La Liga")
        self.assertEqual(canonical_competition_name("czech republic top division"), "Czechia top division")


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
        self.assertFalse(list(DATA.rglob(".*.tmp")))
        self.assertFalse(
            [path for path in DATA.rglob("*") if path.is_file() and path.stat().st_size == 0]
        )
        for row in years:
            payload = read_json(DATA / "matches" / row["file"])
            self.assertEqual(payload["year"], row["year"])
            self.assertEqual(len(payload["matches"]), row["count"])

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
        payload = read_json(DATA / "matches" / latest["file"])
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
        self.assertEqual(parameters["version"], "2026-08-12-global-club-v7")
        self.assertEqual(parameters["k_factor"], 18.0)
        self.assertEqual(parameters["tier_gap"], 80.0)
        self.assertEqual(parameters["tier_share"], 0.45)
        self.assertEqual(parameters["country_share"], 0.15)
        self.assertEqual(parameters["country_anchor_quantile"], 0.9)
        self.assertEqual(parameters["confederation_share"], 0.5)
        self.assertEqual(parameters["home_advantage_domestic"], 45.0)
        self.assertEqual(parameters["home_advantage_cross_border"], 80.0)
        self.assertEqual(parameters["aggregate_floor"], 0.0)
        self.assertEqual(parameters["aggregate_scale"], 1.0)
        self.assertEqual(parameters["uncertainty_penalty"], 1.25)
        self.assertEqual(self.meta["fit"]["validation_period"], ["2018-01-01", "2022-12-31"])

    def test_shell_routes_and_reciprocal_links_mirror_the_national_site(self) -> None:
        shell = (ROOT / "public" / "clubs" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "public" / "clubs" / "clubs.js").read_text(encoding="utf-8")
        root_shell = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        sitemap = (ROOT / "public" / "sitemap.xml").read_text(encoding="utf-8")
        for route in (
            "rankings", "history", "tournaments", "matches", "fixtures", "records",
            "compare", "predict", "methodology", "faq", "about",
        ):
            self.assertIn(f"#/" + route, shell)
        self.assertIn("/clubs/", root_shell)
        self.assertIn("https://nfelo.github.io/clubs/", sitemap)
        self.assertIn("aggregate_weight", script)
        self.assertIn('../assets/critical.css', shell)
        self.assertIn('../assets/styles.css', shell)
        self.assertIn('class="site-header"', shell)
        self.assertIn('class="site-nav"', shell)
        self.assertIn('<main id="content"', shell)
        self.assertIn('class="loading-shell"', shell)
        self.assertIn("useGrouping: false", script)
        self.assertIn("minimumFractionDigits: 1", script)
        self.assertIn('fallback.src = "clubs.js?fallback="', shell)
        self.assertNotRegex(shell, r"clubs\.js\?v=[^\"']+\?fallback")
        for component in (
            "ranking-desktop", "ranking-cards", "team-hero", "forecast",
            "faq-page", "methodology-page", "about-page", "club-context",
            "club-match-cards", "record-definition", "PAGE_FAMILIES",
        ):
            self.assertIn(component, script)
        faq_source = script[script.index("function faqItems"):script.index("function faqPage")]
        self.assertGreaterEqual(faq_source.count('["'), 25)
        for phrase in (
            "Every release coefficient", "Club identity and duplicate control",
            "Two-leg ties and the Aggregate cases list", "Post-match club peaks",
        ):
            self.assertIn(phrase, script)

        national_nav = anchor_labels(root_shell, r'<nav\s+id="site-nav"[^>]*>.*?</nav>')
        club_nav = anchor_labels(shell, r'<nav\s+id="site-nav"[^>]*>.*?</nav>')
        national_footer = anchor_labels(root_shell, r'<nav\s+class="footer-links"[^>]*>.*?</nav>')
        club_footer = anchor_labels(shell, r'<nav\s+class="footer-links"[^>]*>.*?</nav>')
        self.assertEqual(national_nav[1], "Clubs")
        self.assertEqual(club_nav[1], "Nations")
        self.assertEqual(national_footer[1], "Clubs")
        self.assertEqual(club_footer[1], "Nations")
        self.assertEqual(national_nav[:1] + national_nav[2:], club_nav[:1] + club_nav[2:])
        self.assertEqual(
            national_footer[:1] + national_footer[2:],
            club_footer[:1] + club_footer[2:],
        )

        club_css = (ROOT / "public" / "clubs" / "clubs.css").read_text(encoding="utf-8")
        for selector in (".site-header", ".site-footer", ".site-nav", ".page-heading", ".toolbar"):
            self.assertNotIn(selector, club_css)
        self.assertNotRegex(club_css, r"#[0-9a-fA-F]{3,8}\b")
        self.assertIn(".club-match-table > table", club_css)
        self.assertIn("@media (max-width: 1024px)", club_css)
        self.assertIn(".record-cards", club_css)

    def test_public_country_names_match_nfelo_conventions(self) -> None:
        expected = {
            "korea-republic": "South Korea",
            "korea-dpr": "North Korea",
            "czech-republic": "Czechia",
            "turkey": "Turkey",
            "cape-verde": "Cape Verde",
            "democratic-republic-of-congo": "DR Congo",
            "congo-dr": "DR Congo",
            "cote-divoire": "Ivory Coast",
            "china-pr": "China",
            "taiwan": "Taiwan",
            "antigua-and-barbuda": "Antigua and Barbuda",
            "trinidad-and-tobago": "Trinidad and Tobago",
            "turks-and-caicos-islands": "Turks and Caicos Islands",
            "us-virgin-islands": "US Virgin Islands",
        }
        for raw, public in expected.items():
            self.assertEqual(display_country(raw), public)

        national_labels = {
            fields[1]
            for line in (ROOT / "source" / "en.teams.tsv").read_text(
                encoding="utf-8"
            ).splitlines()
            if len(fields := line.split("\t")) >= 2
            and not fields[0].endswith("_loc")
        }
        club_labels = {club["country_name"] for club in self.catalog}
        self.assertFalse(
            club_labels - national_labels,
            f"club-only country labels: {sorted(club_labels - national_labels)}",
        )

    def test_club_browser_javascript_parses(self) -> None:
        subprocess.run(
            ["node", "--check", "public/clubs/clubs.js"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_shootout_kicks_are_not_published_as_match_goals(self) -> None:
        index = self.match_index
        row = next(item for item in index["years"] if item["year"] == 2019)
        payload = read_json(DATA / "matches" / row["file"])
        positions = {name: i for i, name in enumerate(index["schema"])}
        community_shield = next(
            match for match in payload["matches"]
            if str(match[positions["source_ref"]]).endswith(":3233287")
        )
        self.assertEqual(community_shield[positions["home_goals"]], 1)
        self.assertEqual(community_shield[positions["away_goals"]], 1)
        self.assertEqual(community_shield[positions["status"]], "P")

    def test_club_world_cup_is_a_global_bridge(self) -> None:
        row = next(item for item in self.match_index["years"] if item["year"] == 2025)
        payload = read_json(DATA / "matches" / row["file"])
        positions = {name: i for i, name in enumerate(self.match_index["schema"])}
        matches = [
            match for match in payload["matches"]
            if match[positions["competition"]] == "FIFA Club World Cup"
        ]
        self.assertEqual(len(matches), 63)
        self.assertTrue(all(match[positions["kind"]] == "global" for match in matches))
        self.assertTrue(all(match[positions["neutral"]] for match in matches))
        self.assertTrue(all(match[positions["source"]] == "transfermarkt" for match in matches))
        intercontinental = [
            match for match in payload["matches"]
            if match[positions["competition"]] == "FIFA Intercontinental Cup"
        ]
        self.assertTrue(intercontinental)
        self.assertTrue(
            all(match[positions["kind"]] == "intercontinental" for match in intercontinental)
        )
        self.assertTrue(all(match[positions["neutral"]] for match in intercontinental))

    def test_current_metadata_and_regional_order_pass_release_guardrails(self) -> None:
        by_name = {club["name"]: club for club in self.rankings}
        self.assertEqual(by_name["AFC Bournemouth"]["continent"], "Europe")
        self.assertIn("Palmeiras", by_name)
        self.assertNotIn("Se Palmeiras", by_name)
        catalog_names = {club["name"] for club in self.catalog}
        self.assertIn("TP Mazembe", catalog_names)
        self.assertNotIn("Tp Mazembe", catalog_names)
        best = {
            continent: min(club["rank"] for club in self.rankings if club["continent"] == continent)
            for continent in ("South America", "Asia", "North America")
        }
        self.assertLess(best["South America"], best["Asia"])
        self.assertLess(best["South America"], best["North America"])
        self.assertGreaterEqual(
            sum(club["continent"] == "South America" for club in self.rankings[:100]),
            5,
        )
        for club in self.catalog:
            self.assertTrue(club["country_name"], club["name"])
            self.assertNotIn(club["country_name"], {"Unassigned", "Unknown"})
            self.assertTrue(club["continent"], club["name"])
        self.assertNotIn("NA", catalog_names)
        public_identities = [
            (club["country_name"], club["name"])
            for club in self.catalog
        ]
        self.assertEqual(len(public_identities), len(set(public_identities)))
        self.assertNotIn("Cabo Verde", {club["country_name"] for club in self.catalog})
        self.assertIn("Cape Verde", {club["country_name"] for club in self.catalog})
        for name, country, continent in (
            ("Millonarios", "Colombia", "South America"),
            ("KI Klaksvik", "Faroe Islands", "Europe"),
            ("FK Zalgiris Vilnius", "Lithuania", "Europe"),
            ("Attack Energy", "Afghanistan", "Asia"),
            ("Corvinul", "Romania", "Europe"),
        ):
            candidates = [club for club in self.catalog if club["name"] == name]
            self.assertTrue(candidates, name)
            self.assertTrue(
                any(
                    club["country_name"] == country
                    and club["continent"] == continent
                    for club in candidates
                ),
                f"{name}: {candidates}",
            )
        self.assertGreater(by_name["Stockport County"]["rank"], 50)
        self.assertTrue(all(int(club["tier"]) < 3 for club in self.rankings[:50]))
        for variants in (
            {"Inter", "FC Internazionale Milano"},
            {"Benfica", "Sport Lisboa e Benfica"},
            {"Real Betis", "Real Betis Balompié"},
            {"Lens", "Racing Club de Lens"},
            {"Feyenoord", "Feyenoord Rotterdam"},
        ):
            self.assertLessEqual(len(variants & set(by_name)), 1)

    def test_guarded_records_block_known_false_world_claims(self) -> None:
        records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
        expected = {
            "peaks", "strongest_matches", "upsets", "aggregate_examples",
            "year_opening_number_ones",
        }
        self.assertEqual(set(records["definitions"]), expected)
        for definition in records["definitions"].values():
            self.assertTrue(definition["measure"])
            self.assertTrue(definition["order"])
            self.assertTrue(definition["eligibility"])
            self.assertTrue(definition["interpretation"])
        peaks = {row["name"]: row for row in records["peaks"]}
        self.assertGreater(peaks["Ajax"]["rating"], peaks["Kawasaki Frontale"]["rating"])
        leaders = {row["year"]: row["name"] for row in records["year_opening_number_ones"]}
        self.assertNotEqual(leaders.get(1999), "ES Tunis")

    def test_reviewed_2026_champions_league_final_is_published_exactly(self) -> None:
        row = next(item for item in self.match_index["years"] if item["year"] == 2026)
        payload = read_json(DATA / "matches" / row["file"])
        positions = {name: i for i, name in enumerate(self.match_index["schema"])}
        final = [
            match for match in payload["matches"]
            if match[positions["date"]] == "2026-05-30"
            and match[positions["competition"]] == "UEFA Champions League"
            and match[positions["round"]]
            == "Final · Paris Saint-Germain won 4–3 on penalties"
        ]
        self.assertEqual(len(final), 1)
        match = final[0]
        clubs = {club["code"]: club["name"] for club in self.catalog}
        self.assertEqual(clubs[match[positions["home"]]], "PSG")
        self.assertEqual(clubs[match[positions["away"]]], "Arsenal FC")
        self.assertEqual(match[positions["home_goals"]], 1)
        self.assertEqual(match[positions["away_goals"]], 1)
        self.assertEqual(match[positions["status"]], "P")
        self.assertTrue(match[positions["neutral"]])
        self.assertEqual(
            match[positions["source_ref"]],
            "https://www.uefa.com/uefachampionsleague/match/2047742--paris-vs-arsenal/final/",
        )

    def test_santa_clara_associations_are_not_cross_country_merged(self) -> None:
        santa_claras = [club for club in self.catalog if club["name"] == "Santa Clara"]
        countries = {club["country_name"] for club in santa_claras}
        self.assertIn("Portugal", countries)
        codes = {club["code"]: club["country_name"] for club in santa_claras}
        for year in (2023, 2024, 2025):
            row = next(item for item in self.match_index["years"] if item["year"] == year)
            payload = read_json(DATA / "matches" / row["file"])
            positions = {name: i for i, name in enumerate(self.match_index["schema"])}
            for match in payload["matches"]:
                competition = str(match[positions["competition"]]).lower()
                if competition.startswith("portugal"):
                    for side in ("home", "away"):
                        code = match[positions[side]]
                        if code in codes:
                            self.assertEqual(codes[code], "Portugal")

    def test_all_ledger_quality_checks_are_published_as_passed(self) -> None:
        sources = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(sources["quality_checks"]), 6)
        self.assertTrue(all(row["passed"] for row in sources["quality_checks"]))
        self.assertEqual(self.meta["quality"]["checks"], self.meta["quality"]["passed"])

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
