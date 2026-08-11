from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_live_replay import validate_live_replay  # noqa: E402


def audited_documents() -> tuple[dict, dict]:
    selected = {
        "log_loss": 0.87833346,
        "network_log_loss": 0.87992071,
        "brier": 0.51716153,
        "rps": 0.17194856,
        "accuracy": 0.59169676,
    }
    research = {
        "audit_cutoff": "2026-07-11",
        "scored_matches": 46_801,
        "end_to_end": {
            "selected": selected,
            "baseline": {"log_loss": 0.88016905},
        },
    }
    summary = {
        "meta": {
            "methodology_version": "2026-07-27-country-home-dependence",
        },
        "parameters": {
            "network": {"friendly_information_ratio_exact": "0.78621"},
            "forecast_temperature_exact": {
                "friendly": "0.896294991479",
                "competitive": "1.061356232973",
            },
        },
        "validation": {
            "retrospective": {
                "cutoff": "2026-07-11",
                "matches": 46_801,
                "log_loss": selected["log_loss"],
                "network_only_log_loss": selected["network_log_loss"],
                "brier": selected["brier"],
                "rps": selected["rps"],
                "accuracy": selected["accuracy"],
            },
        },
    }
    return summary, research


class LiveReplayContractTests(unittest.TestCase):
    def test_the_failed_live_source_accuracy_case_is_valid(self) -> None:
        summary, research = audited_documents()
        replay = summary["validation"]["retrospective"]
        replay["matches"] = 46_806
        replay["accuracy"] = 27_709 / 46_806

        diagnostics = validate_live_replay(summary, research)

        self.assertEqual(diagnostics["historical_correction_drift"], 5)
        self.assertLess(
            abs(diagnostics["metric_deltas"]["accuracy"]),
            diagnostics["metric_tolerances"]["accuracy"],
        )

    def test_a_material_accuracy_change_still_fails(self) -> None:
        summary, research = audited_documents()
        changed = copy.deepcopy(summary)
        changed["validation"]["retrospective"]["accuracy"] += 0.011

        with self.assertRaisesRegex(
            AssertionError,
            "accuracy moved outside the live-source tolerance",
        ):
            validate_live_replay(changed, research)


class TournamentInterfaceRepairTests(unittest.TestCase):
    def test_title_chance_copy_and_layout_are_plain_and_balanced(self) -> None:
        javascript = (ROOT / "public/assets/app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "public/assets/styles.css").read_text(
            encoding="utf-8"
        )
        faq_answer = javascript.split(
            'question: "What does Title chance mean on a tournament page?"',
            1,
        )[1].split("},", 1)[0]

        self.assertIn("20 out of every 100 computer replays", faq_answer)
        self.assertNotIn("deterministic simulations", faq_answer)
        self.assertIn(
            '<td class="numeric title-chance-column"><span class="rating-main">',
            javascript,
        )
        recent_form = javascript.index(
            '<div class="ranking-card-snapshot${showTitleChance ? "" : " ranking-card-snapshot-single"}">'
        )
        mobile_chance = javascript.index(
            '<div class="tournament-title-chance"><span>Title chance</span><strong>',
            recent_form,
        )
        self.assertGreater(mobile_chance, recent_form)

        chance_css = stylesheet.split(
            "Tournament title chances share the rating and recent-form hierarchy",
            1,
        )[1].split("Tournament opening portrait", 1)[0]
        self.assertIn("min-inline-size: 7.25rem;", chance_css)
        self.assertIn("position: static;", chance_css)
        self.assertIn("justify-items: end;", chance_css)
        self.assertIn("background: none;", chance_css)
        self.assertIn("border: 0;", chance_css)
        self.assertNotIn("grid-column: 1 / -1;", chance_css)
        self.assertNotIn("border-radius: 999px;", chance_css)

    def test_pages_scheduler_has_no_installer_logic(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "pages.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("name: Validate, refresh and deploy Pages", workflow)
        self.assertIn("python scripts/validate_live_replay.py", workflow)
        self.assertNotIn("install_compact_title_chance:", workflow)
        self.assertNotIn("install_repair:", workflow)
        self.assertNotIn("release_gate:", workflow)

    def test_mobile_faq_boxes_keep_equal_gutters(self) -> None:
        stylesheet = (ROOT / "public/assets/styles.css").read_text(
            encoding="utf-8"
        )
        repair = stylesheet.split("Mobile FAQ measure repair 2026-08-09", 1)[1]
        self.assertIn('body[data-route="faq"] .faq-page', repair)
        self.assertGreaterEqual(repair.count("calc(100vw - 32px)"), 2)
        self.assertIn("width: 100%;", repair)
        self.assertIn("max-width: 100%;", repair)
        self.assertIn("min-width: 0;", repair)

    def test_every_generated_route_uses_the_repaired_assets(self) -> None:
        stylesheet = ROOT / "public/assets/styles.css"
        javascript = ROOT / "public/assets/app.js"
        css_revision = hashlib.sha256(stylesheet.read_bytes()).hexdigest()[:12]
        js_revision = hashlib.sha256(javascript.read_bytes()).hexdigest()[:12]
        routes = sorted(route for route in (ROOT / "public").rglob("index.html") if "clubs" not in route.relative_to(ROOT / "public").parts)
        self.assertGreaterEqual(len(routes), 250)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertEqual(
                html.count(f"assets/styles.css?v={css_revision}"),
                3,
                route,
            )
            self.assertEqual(
                html.count(f"assets/app.js?v={js_revision}"),
                1,
                route,
            )


if __name__ == "__main__":
    unittest.main()
