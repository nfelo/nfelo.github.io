from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tournament_classification import (  # noqa: E402
    classify_candidate,
    classify_match,
    load_registry,
    runtime_is_friendly,
    operational_class,
    validate_registry,
)


class RuleTests(unittest.TestCase):
    def test_dedicated_friendly_code(self) -> None:
        decision = classify_candidate("F", ["Friendly"], 0)
        self.assertEqual(decision.status, "friendly")

    def test_qualifier_beats_memorial_wording(self) -> None:
        decision = classify_candidate(
            "NEW",
            ["World Cup qualifier and Memorial Cup"],
            1,
        )
        self.assertEqual(decision.status, "competitive")

    def test_world_cup_is_competitive(self) -> None:
        decision = classify_candidate(
            "WCX",
            ["FIFA World Cup"],
            4,
        )
        self.assertEqual(decision.status, "competitive")

    def test_fifa_series_exception_is_friendly(self) -> None:
        decision = classify_candidate(
            "FFX",
            ["FIFA Series"],
            1,
        )
        self.assertEqual(decision.status, "friendly")

    def test_unknown_level_one_is_uncertain_but_competitive(self) -> None:
        decision = classify_candidate(
            "ZZZ",
            ["Sponsor Trophy"],
            1,
        )
        self.assertEqual(decision.status, "uncertain")
        self.assertEqual(decision.operational_class, "competitive")

    def test_new_invitational_is_friendly(self) -> None:
        decision = classify_candidate(
            "INV",
            ["Summer Invitational Tournament"],
            1,
        )
        self.assertEqual(decision.status, "friendly")

    def test_runtime_new_invitational_is_friendly(self) -> None:
        self.assertTrue(runtime_is_friendly(
            "NEW", "2030-06-01", {"tournaments": {}},
            aliases=("Summer Invitational Tournament",), level=1,
        ))

    def test_future_independence_tournament_is_friendly(self) -> None:
        decision = classify_candidate(
            "NEW",
            ["National Independence Tournament"],
            1,
        )
        self.assertEqual(decision.status, "friendly")

    def test_future_merdeka_tournament_is_friendly(self) -> None:
        decision = classify_candidate(
            "NEW",
            ["Merdeka Tournament"],
            1,
        )
        self.assertEqual(decision.status, "friendly")

    def test_runtime_ambiguous_future_code_is_competitive(self) -> None:
        self.assertFalse(runtime_is_friendly(
            "NEW", "2030-06-01", {"tournaments": {}},
            aliases=("Sponsor Trophy",), level=1,
        ))

    def test_explicit_official_evidence_wins(self) -> None:
        decision = classify_candidate(
            "ABC",
            ["Friendship Championship"],
            1,
            {
                "status": "competitive",
                "source_url": "https://organiser.example/regulations",
                "source_statement": (
                    "The winner qualifies for the continental final."
                ),
            },
        )
        self.assertEqual(decision.status, "competitive")
        self.assertEqual(
            decision.evidence_type,
            "official_source_declaration",
        )


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = ROOT / "config" / "tournament_classification.json"
        cls.registry = load_registry(cls.path)

    def test_registry_validates(self) -> None:
        validate_registry(self.registry)

    def test_current_protected_codes(self) -> None:
        tournaments = self.registry["tournaments"]
        self.assertEqual(tournaments["F"]["status"], "friendly")
        self.assertEqual(tournaments["FFS"]["status"], "friendly")
        self.assertEqual(tournaments["WC"]["status"], "competitive")
        self.assertEqual(tournaments["WQ"]["status"], "competitive")
        self.assertEqual(tournaments["EQ"]["status"], "competitive")

    def test_uncertain_is_operationally_competitive(self) -> None:
        for entry in self.registry["tournaments"].values():
            if entry["status"] == "uncertain":
                self.assertEqual(
                    entry["operational_class"],
                    "competitive",
                )

    def test_unknown_code_is_competitive(self) -> None:
        self.assertEqual(
            classify_match(
                "NEW_UNKNOWN",
                "2030-03-01",
                self.registry,
            ),
            "competitive",
        )

    def test_date_override(self) -> None:
        registry = {
            "tournaments": {
                "MIX": {
                    "status": "uncertain",
                    "operational_class": "competitive",
                    "overrides": [
                        {
                            "effective_from": "2026-01-01",
                            "effective_to": "2026-12-31",
                            "status": "friendly",
                        }
                    ],
                }
            }
        }
        self.assertEqual(
            classify_match("MIX", "2026-06-01", registry),
            "friendly",
        )
        self.assertEqual(
            classify_match("MIX", "2027-06-01", registry),
            "competitive",
        )

    def test_fit_value_is_recorded(self) -> None:
        fit = self.registry["fit"]
        self.assertEqual(
            fit["primary_joint_refit"]["ratio"],
            0.76064,
        )
        self.assertEqual(
            fit["primary_joint_refit"]["friendly_matches"],
            17724,
        )

    def test_independence_codes_are_friendly(self) -> None:
        tournaments = self.registry["tournaments"]
        for code in ("IND", "MRD"):
            self.assertEqual(
                tournaments[code]["status"],
                "friendly",
            )
            self.assertEqual(
                tournaments[code]["operational_class"],
                "friendly",
            )


class PublicCopyTests(unittest.TestCase):
    def test_faq_uses_requested_rounded_title(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn(
            "Why is a friendly’s rating change not always "
            "76.1% of a competitive match?",
            javascript,
        )
        self.assertNotIn("63.901%", javascript)
        self.assertNotIn("0.63901", javascript)
        self.assertIn(
            '${p.network.friendly_information_ratio_exact}',
            javascript,
        )
        self.assertIn(
            '<div class="formula">qₖ = '
            '${number(p.network.friendly_information_ratio, 5)}',
            javascript,
        )

    def test_methodology_uses_exact_deployment_values(self) -> None:
        summary = json.loads(
            (ROOT / "public" / "data" / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            summary["parameters"]["network"]
            ["friendly_information_ratio_exact"],
            "0.76064",
        )
        self.assertEqual(
            summary["parameters"]["forecast_temperature_exact"],
            {
                "friendly": "0.890357703717",
                "competitive": "1.060042606190",
            },
        )

    def test_friendly_events_are_absent_from_tournament_records(self) -> None:
        registry = load_registry(
            ROOT / "config" / "tournament_classification.json"
        )
        friendly_codes = {
            code
            for code, entry in registry["tournaments"].items()
            if entry["operational_class"] == "friendly"
        }
        catalog = json.loads(
            (
                ROOT / "public" / "data" / "tournaments" / "index.json"
            ).read_text(encoding="utf-8")
        )
        catalog_codes = {
            code
            for family in catalog["families"]
            for code in family.get("source_codes", [])
        }
        self.assertFalse(friendly_codes & catalog_codes)
        summary = json.loads(
            (ROOT / "public" / "data" / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        family_ids = {
            family["id"] for family in catalog["families"]
        }
        self.assertTrue(
            all(
                row["tournament_id"] in family_ids
                for row in summary["best_tournaments"]
            )
        )

    def test_current_number_one_days_include_today(self) -> None:
        summary = json.loads(
            (ROOT / "public" / "data" / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        current = next(
            spell for spell in summary["number_ones"]
            if spell["to"] is None
        )
        as_of = max(
            date.today(),
            date.fromisoformat(summary["meta"]["results_through"]),
        )
        expected = (
            as_of - date.fromisoformat(current["from"])
        ).days + 1
        self.assertEqual(current["days"], expected)
        total = next(
            row for row in summary["number_one_summary"]
            if row["code"] == current["code"]
        )
        self.assertEqual(total["latest"], as_of.isoformat())
        self.assertEqual(
            total["days"],
            sum(
                spell["days"]
                for spell in summary["number_ones"]
                if spell["code"] == current["code"]
            ),
        )

    def test_public_class_tools_use_registry_flag(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'if (cls === "friendly" && !match.friendly)',
            javascript,
        )
        self.assertIn(
            'if (cls === "competitive" && match.friendly)',
            javascript,
        )
        self.assertNotIn("match.level !== 0", javascript)
        self.assertNotIn("match.level === 0", javascript)
        self.assertNotIn(
            'fixture.tournament_code === "F"',
            javascript,
        )

    def test_public_copy_has_a_timeless_voice(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "What do the Tournaments and Best tournaments pages show?",
            javascript,
        )
        self.assertIn(
            "How is the methodology tested?",
            javascript,
        )
        for phrase in (
            "Tournament class was subsequently separated",
            "The current attack/defence layer",
            "while the full grid now sums",
        ):
            self.assertNotIn(phrase, javascript)
        for phrase in (
            "What the 19 July 2026 audit changed",
            "This release adopts",
            "From this release onward",
            "are now separate",
        ):
            self.assertNotIn(phrase, readme)

    def test_probability_links_preserve_the_displayed_forecast(self) -> None:
        javascript = (
            ROOT / "public" / "assets" / "app.js"
        ).read_text(encoding="utf-8")
        for phrase in (
            "matchId: match.id",
            "probabilities = linkedMatch.p.map(Number)",
            "date: fixture.date",
            "maximumPredictionDate",
        ):
            self.assertIn(phrase, javascript)

        # Formatting is intentionally multiline in app.js. Collapse
        # whitespace before checking the two start-of-day ternaries.
        normalized = " ".join(javascript.split())
        self.assertIn(
            (
                "beforeDate ? event.date < dateValue "
                ": event.date <= dateValue"
            ),
            normalized,
        )
        self.assertIn(
            (
                "beforeDate ? item.date < dateValue "
                ": item.date <= dateValue"
            ),
            normalized,
        )
        self.assertNotIn(
            "date: previousISODate(match.date)",
            javascript,
        )
        self.assertNotIn(
            "date: todayISO(),\n      first: fixture.team1_code",
            javascript,
        )


if __name__ == "__main__":
    unittest.main()
