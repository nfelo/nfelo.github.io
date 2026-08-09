from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tournament_odds import (  # noqa: E402
    FormatUnavailable,
    INFERRED_PROFILE,
    entrant_kind,
    infer_universal_manifest,
    load_configuration,
    normalise_knockout_graph,
    normalise_two_leg_graph,
    parse_match_id,
    parse_third_place_tables,
    retryable_format_failure,
    strip_comments_positioned,
    update_manifest,
    validate_manifest,
)
from tournament_simulation import (  # noqa: E402
    TournamentSimulator,
    cached_row_is_valid,
    digest,
    pooled_probabilities,
    rounded_tenths,
    stable_covariance_root,
)


MANIFEST_PATH = ROOT / "source" / "tournament_odds" / "manifest.json"
CACHE_PATH = ROOT / "source" / "tournament_odds" / "probabilities.json"
CATALOG_PATH = ROOT / "public" / "data" / "tournaments" / "index.json"
JS_PATH = ROOT / "public" / "assets" / "app.js"
CSS_PATH = ROOT / "public" / "assets" / "styles.css"


def deployment_workflow_text() -> str:
    path = ROOT / ".github" / "workflows" / "pages.yml"
    if not path.is_file():
        raise AssertionError("The permanent Pages workflow is missing")
    text = path.read_text(encoding="utf-8")
    if "python scripts/validate_live_replay.py" not in text:
        raise AssertionError("The Pages workflow is missing live replay validation")
    return text


class TournamentFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = load_configuration(ROOT / "config" / "tournament_odds.json")
        cls.manifest = validate_manifest(MANIFEST_PATH)

    def test_precise_profile_registry_remains_unambiguous(self) -> None:
        profiles = self.configuration["profiles"]
        self.assertGreaterEqual(len(profiles), 10)
        codes = [code for profile in profiles for code in profile["source_codes"]]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(self.configuration["trials"], 100_000)

    def test_pinned_ready_revisions_are_preopening_and_attributed(self) -> None:
        ready = [
            entry
            for entry in self.manifest["editions"].values()
            if entry["status"] == "ready" and entry["profile"] != INFERRED_PROFILE
        ]
        self.assertGreaterEqual(len(ready), 10)
        for entry in ready:
            self.assertEqual(entry["facts_version"], 4)
            self.assertTrue(entry["provenance"])
            opening = datetime.fromisoformat(entry["cutoff"].replace("Z", "+00:00"))
            for source in entry["provenance"]:
                timestamp = datetime.fromisoformat(source["timestamp"].replace("Z", "+00:00"))
                self.assertLess(timestamp, opening)
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                self.assertIn(f"oldid={source['revision']}", source["url"])
                self.assertEqual(source["license"], "CC BY-SA 4.0")

    def test_universal_coverage_exceeds_ninety_nine_percent(self) -> None:
        coverage = self.manifest["coverage"]
        self.assertGreaterEqual(coverage["editions"], 1_000)
        self.assertGreaterEqual(coverage["ready"] / coverage["editions"], 0.99)
        unsupported = [
            entry for entry in self.manifest["editions"].values()
            if entry["status"] != "ready"
        ]
        self.assertTrue(unsupported)
        self.assertTrue(all(entry["confidence"] == "truly-inconclusive" for entry in unsupported))

    def test_inferred_group_scoring_follows_the_historical_era(self) -> None:
        lookup = {
            (entry["family"], entry["start"]): entry
            for entry in self.manifest["editions"].values()
        }
        self.assertEqual(
            lookup[("AFC Asian Cup", "1956-09-01")]["rules"]
            ["points_for_win"],
            2,
        )
        self.assertEqual(
            lookup[("ASEAN Championship", "2026-07-24")]["rules"]
            ["points_for_win"],
            3,
        )
        self.assertEqual(
            lookup[("FIFA World Cup", "1990-06-08")]["rules"]
            ["points_for_win"],
            2,
        )
        self.assertEqual(
            lookup[("FIFA World Cup", "1994-06-17")]["rules"]
            ["points_for_win"],
            3,
        )

    def test_gold_cup_and_asean_are_no_longer_artificially_excluded(self) -> None:
        lookup = {
            (entry["family"], entry["start"]): entry
            for entry in self.manifest["editions"].values()
        }
        self.assertEqual(lookup[("CONCACAF Gold Cup", "2025-06-14")]["status"], "ready")
        self.assertEqual(lookup[("ASEAN Championship", "2026-07-24")]["status"], "ready")

    def test_world_cup_allocation_and_causal_graph_are_complete(self) -> None:
        world = next(
            entry for entry in self.manifest["editions"].values()
            if entry["family"] == "FIFA World Cup" and entry["start"] == "2026-06-11"
        )
        rules = world["rules"]
        self.assertEqual(len(rules["third_place_allocation"]), 495)
        title_path = [node for node in rules["knockout_matches"] if node["championship"] or node["team1"][0] != "loser"]
        self.assertEqual(sum(node["team1"][0] != "loser" for node in rules["knockout_matches"]), 31)
        self.assertEqual(sum(bool(node["championship"]) for node in rules["knockout_matches"]), 1)
        self.assertGreaterEqual(len(title_path), 31)
        venues = [node["venue_host"] for node in rules["knockout_matches"]]
        self.assertEqual(venues.count("CA"), 3)
        self.assertEqual(venues.count("MX"), 3)
        self.assertEqual(venues.count("US"), 26)

    def test_every_single_leg_graph_has_pinned_dates_and_valid_venue_hosts(self) -> None:
        for key, entry in self.manifest["editions"].items():
            if entry.get("status") != "ready":
                continue
            rules = entry["rules"]
            if rules["knockout_kind"] != "revision_graph":
                continue
            hosts = set(rules["hosts"])
            for node in rules["knockout_matches"]:
                self.assertRegex(node["date"], r"^\d{4}-\d{2}-\d{2}$", key)
                self.assertIn(node["venue_host"], hosts | {None}, key)

    def test_asean_two_leg_graph_uses_published_dates_and_hosts(self) -> None:
        edition = next(
            entry for entry in self.manifest["editions"].values()
            if entry["family"] == "ASEAN Championship" and entry["start"] == "2024-12-08"
        )
        rules = edition["rules"]
        self.assertEqual(rules["knockout_kind"], "two_leg_graph")
        self.assertTrue(rules["away_goals"])
        self.assertEqual(
            [leg["date"] for tie in rules["knockout_ties"] for leg in tie["legs"]],
            [
                "2024-12-26", "2024-12-29",
                "2024-12-27", "2024-12-30",
                "2025-01-02", "2025-01-05",
            ],
        )

    def test_knockout_rules_never_store_realised_team_codes(self) -> None:
        allowed = {"group1", "group2", "group3", "third-options", "winner", "loser"}
        for entry in self.manifest["editions"].values():
            if entry.get("status") != "ready":
                continue
            for node in entry["rules"].get("knockout_matches", []):
                self.assertIn(node["team1"][0], allowed)
                self.assertIn(node["team2"][0], allowed)

    def test_unicode_comment_removal_preserves_offsets(self) -> None:
        value = "ßé<!--Winner Match 999\n-->Winner Match 4"
        cleaned = strip_comments_positioned(value)
        self.assertEqual(len(value), len(cleaned))
        self.assertEqual(value.count("\n"), cleaned.count("\n"))
        self.assertIn("Winner Match 4", cleaned)

    def test_score_link_uses_its_own_last_match_label(self) -> None:
        score = "{{score link|Winner Match 73 vs Winner Match 75|Match 90}}"
        self.assertEqual(parse_match_id(score, ""), 90)

    def test_symbolic_knockout_graph_is_topologically_normalised(self) -> None:
        boxes = [
            {"match": None, "section_id": "R16-M1", "date": "2024-01-01", "team1": "Winner Group A", "team2": "Runner-up Group B"},
            {"match": None, "section_id": "R16-M2", "date": "2024-01-01", "team1": "Winner Group B", "team2": "Runner-up Group A"},
            {"match": None, "section_id": "Final", "date": "2024-01-04", "team1": "Winner R1", "team2": "Winner R2"},
        ]
        graph = normalise_knockout_graph(boxes, 2, 4)
        self.assertEqual([node["id"] for node in graph], ["R16-M1", "R16-M2", "Final"])
        self.assertTrue(graph[-1]["championship"])

    def test_two_leg_boxes_become_a_causal_tie_graph(self) -> None:
        boxes = [
            {"section_id": "sf1-1stleg", "date": "2024-12-26", "team1": "Runner-up Group A", "team2": "Winner Group B", "title": "Knockout"},
            {"section_id": "sf1-2ndleg", "date": "2024-12-29", "team1": "Winner Group B", "team2": "Runner-up Group A", "title": "Knockout"},
            {"section_id": "sf2-1stleg", "date": "2024-12-27", "team1": "Runner-up Group B", "team2": "Winner Group A", "title": "Knockout"},
            {"section_id": "sf2-2ndleg", "date": "2024-12-30", "team1": "Winner Group A", "team2": "Runner-up Group B", "title": "Knockout"},
            {"section_id": "f-1stleg", "date": "2025-01-02", "team1": "Winner Semi-final 1", "team2": "Winner Semi-final 2", "title": "Final"},
            {"section_id": "f-2ndleg", "date": "2025-01-05", "team1": "Winner Semi-final 2", "team2": "Winner Semi-final 1", "title": "Final"},
        ]
        graph = normalise_two_leg_graph(boxes, 4)
        self.assertEqual([row["id"] for row in graph], ["SF1", "SF2", "FINAL"])
        self.assertTrue(graph[-1]["championship"])

    def test_inline_third_place_table_parser(self) -> None:
        table = """{| class="wikitable"
|-
! colspan=4 | Third-placed teams qualify
! 1A<br />vs
! 1B<br />vs
|-
| '''A''' || '''B''' || || || 3B || 3A
|}
"""
        self.assertEqual(
            parse_third_place_tables([table], 4),
            {"AB": {"A": "B", "B": "A"}},
        )

    def test_entrant_parser_accepts_federation_symbols(self) -> None:
        self.assertEqual(entrant_kind("Winner QFA"), ("winner", "QFA"))
        self.assertEqual(entrant_kind("Third-place Group A/C/D"), ("third-options", "A/C/D"))

    def test_future_top_two_pathway_is_discovered_without_a_profile(self) -> None:
        rows = []
        match_id = 0
        groups = (("A", "B", "C"), ("D", "E", "F"))
        for group in groups:
            for first, second in ((group[0], group[1]), (group[0], group[2]), (group[1], group[2])):
                rows.append({
                    "id": match_id, "date": f"2032-06-{match_id + 1:02d}",
                    "a": first, "b": second, "sa": 1, "sb": 0,
                    "tc": "NEW", "home": 0,
                })
                match_id += 1
        rows.extend([
            {"id": 6, "date": "2032-06-10", "a": "A", "b": "E", "sa": 1, "sb": 0, "tc": "NEW", "home": 0},
            {"id": 7, "date": "2032-06-10", "a": "D", "b": "B", "sa": 1, "sb": 0, "tc": "NEW", "home": 0},
            {"id": 8, "date": "2032-06-14", "a": "A", "b": "D", "sa": 1, "sb": 0, "tc": "NEW", "home": 0},
        ])
        evidence = [{
            "id": "new-cup-2032", "family": "New Cup", "category": "Regional championships",
            "start": "2032-06-01", "state_date": "2032-06-01", "end": "2032-06-14",
            "participants": list("ABCDEF"), "source_codes": ["NEW"], "rows": rows,
        }]
        manifest = infer_universal_manifest(evidence, self.configuration)
        entry = next(iter(manifest["editions"].values()))
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(entry["profile"], INFERRED_PROFILE)
        self.assertEqual(entry["rules"]["advance_per_group"], 2)
        self.assertEqual(len(entry["rules"]["active_groups"]), 2)

    def test_format_retry_policy_distinguishes_future_and_immutable_failures(self) -> None:
        self.assertTrue(
            retryable_format_failure(FormatUnavailable("incomplete graph"), "2999-01-01")
        )
        self.assertFalse(
            retryable_format_failure(FormatUnavailable("incomplete graph"), "2000-01-01")
        )
        self.assertTrue(
            retryable_format_failure(
                FormatUnavailable("Wikipedia request failed: timed out"),
                "2000-01-01",
            )
        )


class TournamentSimulationTests(unittest.TestCase):
    def test_full_covariance_root_reconstructs_off_diagonals(self) -> None:
        covariance = np.asarray([[4.0, 1.25], [1.25, 3.0]])
        root = stable_covariance_root(covariance)
        np.testing.assert_allclose(root @ root.T, covariance, atol=1e-10, rtol=0.0)
        self.assertNotEqual(float((root @ root.T)[0, 1]), 0.0)

    def test_largest_remainder_is_exact_and_deterministic(self) -> None:
        chances = rounded_tenths(np.asarray([1, 1, 1]), ["A", "B", "C"])
        self.assertEqual(sum(round(value * 10) for value in chances.values()), 1000)
        self.assertEqual(chances, {"A": 33.4, "B": 33.3, "C": 33.3})

    def test_probability_pool_is_team_swap_invariant(self) -> None:
        network = np.asarray([
            [0.61, 0.24, 0.15],
            [0.22, 0.31, 0.47],
            [0.35, 0.30, 0.35],
        ])
        score = np.asarray([
            [0.54, 0.27, 0.19],
            [0.30, 0.28, 0.42],
            [0.37, 0.26, 0.37],
        ])
        pooled = pooled_probabilities(network, score, 0.7)
        swapped = pooled_probabilities(network[:, ::-1], score[:, ::-1], 0.7)
        np.testing.assert_allclose(swapped, pooled[:, ::-1], atol=1e-14, rtol=0.0)

    def test_small_tournament_is_seed_deterministic(self) -> None:
        entry = {
            "start": "2024-06-01",
            "source_end": "2024-06-02",
            "participants": ["A", "B", "C", "D"],
            "rules": {
                "groups": [
                    {"name": "A", "teams": ["A", "B"]},
                    {"name": "B", "teams": ["C", "D"]},
                ],
                "group_fixtures": [
                    {"date": "2024-06-01", "group": "A", "team1": "A", "team2": "B", "home": 0, "venue": ""},
                    {"date": "2024-06-02", "group": "B", "team1": "C", "team2": "D", "home": 0, "venue": ""},
                ],
                "advance_per_group": 2,
                "best_third": 0,
                "tie_break": "overall_then_head_to_head",
                "knockout_teams": 4,
                "knockout_kind": "standard-neutral",
                "away_goals": False,
            },
        }
        state = {
            "codes": ["A", "B", "C", "D"],
            "means": [100.0, 20.0, -15.0, -80.0],
            "covariance": np.asarray([
                [500.0, 80.0, 20.0, 0.0],
                [80.0, 500.0, 10.0, 0.0],
                [20.0, 10.0, 500.0, 60.0],
                [0.0, 0.0, 60.0, 500.0],
            ]).reshape(-1).tolist(),
            "scale": 1.0,
            "home": 80.0,
            "draw": 0.30,
            "forecast_layer": {
                "attack": [0.0] * 4,
                "defence": [0.0] * 4,
                "last_day": [-1] * 4,
                "parameters": {"gap_scale": 1.0, "annual_decay": 0.5},
                "calibration": {
                    "draw_log_tilt": 0.0,
                    "competitive_temperature": 1.0,
                    "nfelo_weight": 0.7,
                },
                "base_goal": 1.35,
            },
            "venue_effects": {
                "means": [0.0] * 4,
                "variances": [20.0] * 4,
                "home_share": 0.5,
                "away_share": 0.5,
                "predictive_variance_scale": 0.0,
            },
        }
        first = TournamentSimulator(entry, state, 2_000, 12345).simulate()
        second = TournamentSimulator(entry, state, 2_000, 12345).simulate()
        np.testing.assert_array_equal(first, second)
        self.assertEqual(int(first.sum()), 2_000)

    def test_disabled_venue_uncertainty_is_not_silently_reintroduced(self) -> None:
        entry = {
            "start": "2024-06-01",
            "participants": ["A", "B"],
            "rules": {"groups": [], "group_fixtures": []},
        }
        state = {
            "codes": ["A", "B"],
            "means": [0.0, 0.0],
            "covariance": [0.0, 0.0, 0.0, 0.0],
            "scale": 1.0,
            "home": 80.0,
            "draw": 0.3,
            "forecast_layer": {
                "attack": [0.0, 0.0],
                "defence": [0.0, 0.0],
                "last_day": [-1, -1],
                "parameters": {"gap_scale": 1.0, "annual_decay": 0.5},
                "calibration": {
                    "draw_log_tilt": 0.0,
                    "competitive_temperature": 1.0,
                    "nfelo_weight": 0.7,
                },
                "base_goal": 1.35,
            },
            "venue_effects": {
                "means": [7.0, -4.0],
                "variances": [10_000.0, 10_000.0],
                "home_share": 0.5,
                "away_share": 0.5,
                "predictive_variance_scale": 0.0,
            },
        }
        simulator = TournamentSimulator(entry, state, 50, 7)
        np.testing.assert_allclose(simulator.venue[:, 0], 7.0)
        np.testing.assert_allclose(simulator.venue[:, 1], -4.0)

    def test_corrupt_cached_counts_are_never_reused(self) -> None:
        signature = {
            "algorithm": "test-v1",
            "facts_sha256": "f" * 64,
            "state_sha256": "s" * 64,
            "trials": 10,
        }
        payload = {
            **signature,
            "seed": 1,
            "codes": ["A", "B"],
            "wins": [6, 4],
            "title_chances": {"A": 60.0, "B": 40.0},
        }
        payload["simulation_sha256"] = digest(payload)
        self.assertTrue(cached_row_is_valid(payload, signature, 10))
        payload["wins"][0] = 7
        self.assertFalse(cached_row_is_valid(payload, signature, 10))


class PublishedTournamentChanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_every_cached_edition_has_exact_integer_counts(self) -> None:
        self.assertEqual(self.cache["algorithm"], self.manifest["algorithm"])
        ready = sum(
            entry["status"] == "ready"
            for entry in self.manifest["editions"].values()
        )
        self.assertEqual(len(self.cache["editions"]), ready)
        for row in self.cache["editions"].values():
            self.assertGreaterEqual(sum(row["wins"]), 10_000)
            self.assertEqual(sum(row["wins"]), row["trials"])
            self.assertEqual(
                sum(round(float(value) * 10) for value in row["title_chances"].values()),
                1000,
            )
            payload = dict(row)
            recorded = payload.pop("simulation_sha256")
            self.assertEqual(
                recorded,
                hashlib.sha256(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            )
        payload = dict(self.cache)
        recorded = payload.pop("cache_sha256")
        self.assertEqual(recorded, digest(payload))

    def test_public_catalog_contains_percentages_but_no_provenance(self) -> None:
        text = CATALOG_PATH.read_text(encoding="utf-8")
        for forbidden in ("oldid=", "facts_sha256", "covariance", "third_place_allocation", "simulation_sha256"):
            self.assertNotIn(forbidden, text)
        lookup = {
            (entry["family"], entry["start"]): entry
            for entry in self.manifest["editions"].values()
        }
        checked = 0
        for family in self.catalog["families"]:
            for edition in family["editions"]:
                entry = lookup.get((family["name"], edition["start"]))
                if not entry:
                    continue
                values = [participant.get("title_chance") for participant in edition["participants"]]
                if entry["status"] == "ready":
                    self.assertTrue(all(value is not None for value in values))
                    self.assertEqual(sum(round(float(value) * 10) for value in values), 1000)
                else:
                    self.assertTrue(all(value is None for value in values))
                checked += 1
        self.assertEqual(checked, self.manifest["coverage"]["editions"])
        self.assertGreaterEqual(checked, 1_000)

    def test_interface_shows_title_chance_only_before_tournament(self) -> None:
        for marker in (
            'selectedView === "before"',
            'value="title_chance">Title chance',
            'tournamentTitleChance(team.title_chance)',
            'showTitleChance ? `<th class="numeric title-chance-column">Title chance</th>`',
            '<td class="numeric title-chance-column"><span class="rating-main">',
            '<div class="ranking-card-snapshot${showTitleChance ? "" : " ranking-card-snapshot-single"}">',
            '<div class="tournament-title-chance"><span>Title chance</span><strong>',
            "A 20% title chance means the team won about 20 out of every 100 computer replays",
            "A dash means that route is not clear enough to estimate fairly",
        ):
            self.assertIn(marker, self.js)

    def test_explanations_share_the_universal_natural_language_contract(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for marker in (
            "Before the first match",
            "20 out of every 100 computer replays",
            "Old and new tournaments are added whenever that route is clear",
            "otherwise the page shows a dash",
            "Future editions, uncertainty and the final display",
        ):
            self.assertIn(marker, self.js)
        for marker in (
            "## Tournament title chances",
            "universal structural reader",
            "The same discovery step runs inside every normal site build",
            "opening-state",
            "genuinely incoherent evidence as an em dash",
        ):
            self.assertIn(marker, readme)

    def test_title_chance_layout_covers_desktop_table_mobile_cards_and_forced_colours(self) -> None:
        for marker in (
            'body[data-route="tournaments"] .title-chance-column',
            'body[data-route="tournaments"] .tournament-title-chance',
            'body[data-route="tournaments"] .tournament-chance-note',
            "var(--q11-rose) 0 20%",
            "var(--q11-sage) 60% 80%",
            "var(--q11-powder) 80% 100%",
            "min-inline-size: 7.25rem;",
            "position: static;",
            "justify-items: end;",
            "background: none;",
            "border: 0;",
            "font-variant-numeric: lining-nums tabular-nums;",
            "@media (forced-colors: active)",
            "background: Canvas;",
            "border-color: CanvasText;",
        ):
            self.assertIn(marker, self.css)
        self.assertIn("@media (max-width: 900px)", self.css)
        self.assertIn(".ranking-desktop { display: none; }", self.css)
        self.assertIn(".ranking-cards {", self.css)

    def test_plain_tournament_copy_and_mobile_faq_measure_are_regressions(self) -> None:
        faq_copy = self.js.split(
            'question: "What does Title chance mean on a tournament page?"',
            1,
        )[1].split("},", 1)[0]
        for marker in (
            "NFELO’s estimate just before the tournament began",
            "20 out of every 100 computer replays",
            "Old and new tournaments are added whenever that route is clear",
        ):
            self.assertIn(marker, faq_copy)
        for forbidden in (
            "deterministic simulations",
            "joint strength uncertainty",
            "full covariance",
            "classifier",
        ):
            self.assertNotIn(forbidden, faq_copy)

        final_mobile_faq = self.css.split(
            "Mobile FAQ measure repair 2026-08-09",
            1,
        )[1]
        for marker in (
            'body[data-route="faq"] .faq-page',
            "width: calc(100vw - 32px);",
            "grid-template-columns: 31px minmax(0, 1fr) 30px;",
            "overflow-wrap: anywhere;",
        ):
            self.assertIn(marker, final_mobile_faq)

    def test_scheduled_deploy_and_tests_share_one_live_replay_contract(self) -> None:
        pages = deployment_workflow_text()
        validator = (
            ROOT / "scripts" / "validate_live_replay.py"
        ).read_text(encoding="utf-8")
        build_tests = (ROOT / "tests" / "test_build.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("python scripts/validate_live_replay.py", pages)
        self.assertNotIn("install_repair:", pages)
        self.assertNotIn("release_gate:", pages)
        self.assertIn('"accuracy": 0.01', validator)
        self.assertIn("LIVE_SOURCE_TOLERANCES", build_tests)
        self.assertIn("validate_live_replay(summary, research)", build_tests)
        self.assertNotIn("accuracy_change_budget", pages)
        self.assertNotIn("live_correct", pages)

    def test_every_generated_route_uses_current_asset_revisions(self) -> None:
        css_revision = hashlib.sha256(CSS_PATH.read_bytes()).hexdigest()[:12]
        js_revision = hashlib.sha256(JS_PATH.read_bytes()).hexdigest()[:12]
        routes = sorted((ROOT / "public").rglob("index.html"))
        self.assertGreaterEqual(len(routes), 250)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(f"assets/styles.css?v={css_revision}", html, route)
            self.assertIn(f"assets/app.js?v={js_revision}", html, route)

    def test_every_build_discovers_future_tournament_formats(self) -> None:
        source_refresh = (ROOT / "scripts" / "fetch_sources.py").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
        pages = deployment_workflow_text()
        for marker in (
            "infer_universal_manifest(",
            "tournament_evidence_editions(output.matches)",
            "if manifest_changed:",
            "run_replay(",
        ):
            self.assertIn(marker, builder)
        self.assertNotIn("update_manifest(", source_refresh)
        self.assertIn("python scripts/fetch_sources.py --source source", pages)
        self.assertNotIn("Pin and validate pre-tournament formats", pages)


if __name__ == "__main__":
    unittest.main()
