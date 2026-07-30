from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
APP_PATH = PUBLIC / "assets" / "app.js"
MARKER = "Balanced interface unification 2026-07-30."


class BalancedInterfaceUnificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.app = APP_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("Balanced-interface marker missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_layer_is_unique_last_and_balanced(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        self.assertIn("Final consistency polish.", self.css)
        self.assertGreater(
            self.css.index(MARKER),
            self.css.index("Final consistency polish."),
        )
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)
        self.assertTrue(self.css.rstrip().endswith("}"))

    def test_tables_have_no_asymmetric_reserved_gutter(self) -> None:
        for marker in (
            "body .table-shell {",
            "scrollbar-gutter: auto;",
            'body[data-route="records"] #record-table {',
            "width: calc(100% + 24px);",
            "margin-inline: -12px;",
            '#record-table > .table-shell {',
            "margin-inline: 0;",
        ):
            self.assertIn(marker, self.finish)

    def test_history_and_chronology_controls_align(self) -> None:
        for marker in (
            ".field-error:empty {",
            "display: none;",
            "@media (min-width: 1025px)",
            "body .history-toolbar,",
            "body #number-one-filters {",
            "flex-wrap: nowrap;",
            "align-items: flex-end;",
            "min-height: 48px;",
            "height: 48px;",
        ):
            self.assertIn(marker, self.finish)

    def test_homepage_actions_and_matches_are_rebuilt(self) -> None:
        self.assertNotIn(
            "Predict any historical or current matchup",
            self.app,
        )
        self.assertIn(
            "Predict a past or current matchup",
            self.app,
        )
        for marker in (
            'class="home-record-rank"',
            'class="home-record-match"',
            'class="home-record-teams"',
            '<time datetime="${match.date}">',
            "<small>Combined</small>",
        ):
            self.assertIn(marker, self.app)
        for marker in (
            ".home-action-predict {",
            "justify-self: center;",
            "width: min(430px, 100%);",
            ".home-record-teams {",
            "white-space: nowrap;",
            ".home-record-match > time {",
            "font-variant-numeric: lining-nums tabular-nums;",
        ):
            self.assertIn(marker, self.finish)

    def test_faq_jewel_language_reaches_other_disclosures(self) -> None:
        for marker in (
            ".method-details,",
            ".analysis-disclosure,",
            ".team-model-details,",
            ".venue-profile-details",
            "--bu-disc-a: var(--pv-rose);",
            ".method-details:nth-of-type(4n + 2)",
            ".analysis-disclosure:nth-of-type(even)",
            ".score-profile-details {",
            "> summary::after {",
            'content: "+";',
            ")[open] > summary::after {",
            'content: "−";',
        ):
            self.assertIn(marker, self.finish)

    def test_every_display_mode_has_an_explicit_contract(self) -> None:
        for marker in (
            "@media (max-width: 720px)",
            "@media (max-width: 520px)",
            "@media (prefers-color-scheme: dark)",
            "@media (hover: none) and (pointer: coarse)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "color: ButtonText;",
            "background: ButtonFace;",
            "@media print",
        ):
            self.assertIn(marker, self.finish)

    def test_finishing_layer_stays_asset_and_motion_neutral(self) -> None:
        for forbidden in (
            "url(",
            ".svg",
            ".png",
            "animation:",
            "--result-",
        ):
            self.assertNotIn(forbidden, self.finish)
        tiny = [
            float(value)
            for value in re.findall(
                r"font-size:\s*([0-9]+(?:\.[0-9]+)?)px",
                self.finish,
            )
            if float(value) < 12
        ]
        self.assertEqual(tiny, [])

    def test_every_route_has_current_asset_hashes(self) -> None:
        css_hash = hashlib.sha256(
            CSS_PATH.read_bytes()
        ).hexdigest()[:12]
        app_hash = hashlib.sha256(
            APP_PATH.read_bytes()
        ).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertEqual(len(routes), 260)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(
                f"assets/styles.css?v={css_hash}",
                html,
                route,
            )
            self.assertIn(
                f"assets/app.js?v={app_hash}",
                html,
                route,
            )


if __name__ == "__main__":
    unittest.main()
