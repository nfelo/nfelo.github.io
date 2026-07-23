from __future__ import annotations

import json
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
            0.75185,
        )
        self.assertEqual(
            fit["coefficient_only_current_temperatures"]["ratio"],
            0.75408,
        )


class PublicCopyTests(unittest.TestCase):
    def test_faq_uses_requested_rounded_title(self) -> None:
        javascript = (ROOT / "public" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn(
            "Why is a friendly’s rating change not always "
            "75.2% of a competitive match?",
            javascript,
        )
        self.assertNotIn("63.901%", javascript)
        self.assertNotIn("0.63901", javascript)
        self.assertNotIn("0.75185", javascript)
        self.assertIn(
            '<div class="formula">qₖ = '
            '${number(p.network.friendly_information_ratio, 5)}',
            javascript,
        )


if __name__ == "__main__":
    unittest.main()
