from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS = PUBLIC / "assets" / "styles.css"
APP = PUBLIC / "assets" / "app.js"
BUILD_TESTS = ROOT / "tests" / "test_build.py"
SIGNATURE = "Romantic editorial feminine tablet v8 2026-08-02."
END_MARKER = "Velvet botanical ledger unified system 2026-08-03."


class RomanticEditorialFeminineTabletV8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS.read_text(encoding="utf-8")
        cls.app = APP.read_text(encoding="utf-8")
        cls.build_tests = BUILD_TESTS.read_text(encoding="utf-8")
        cls.finish = cls.css.split(SIGNATURE, 1)[1].split(
            END_MARKER,
            1,
        )[0]

    def test_release_is_unique_ordered_and_balanced(self) -> None:
        self.assertEqual(self.css.count(SIGNATURE), 1)
        self.assertEqual(self.app.count(SIGNATURE), 1)
        self.assertLess(self.css.index(SIGNATURE), self.css.index(END_MARKER))
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)

    def test_supporting_palette_is_complete_in_both_modes(self) -> None:
        for value in (
            "--q8-champagne: #e7c98e",
            "--q8-sage: #b9d4c3",
            "--q8-powder-blue: #c8d9ef",
            "--q8-rose-petal: #efafd0",
            "--q8-lilac-mist: #d8c6ed",
            "--q8-champagne: #e2c58f",
            "--q8-sage: #91c7aa",
            "--q8-powder-blue: #9ebde1",
            "--q8-rose-petal: #db83b5",
            "--q8-lilac-mist: #ad91ca",
        ):
            self.assertIn(value, self.finish)

    def test_finish_respects_every_existing_asset_contract(self) -> None:
        for forbidden in (
            "url(",
            ".svg",
            ".png",
            "-webkit-mask:",
            "mask:",
            "animation:",
            "display: none",
            "visibility: hidden",
            "z-index: -1;",
            "--result-",
            ".form .W",
            ".form .D",
            ".form .L",
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

    def test_tablet_rankings_are_two_column_and_state_driven(self) -> None:
        for value in (
            "@media (min-width: 901px) and (max-width: 1180px)",
            '.ranking-cards[data-q8-tablet="true"]',
            "grid-template-columns: repeat(2, minmax(0, 1fr))",
            ".ranking-card:nth-child(3n + 2)",
            ".ranking-card:nth-child(3n)",
            'body[data-route="rankings"] .toolbar',
            'body[data-route="home"] .home-explore-links',
            ".site-footer > p:last-of-type",
        ):
            self.assertIn(value, self.finish)
        for value in (
            "const syncTabletRankingPresentation = () =>",
            'desktop.toggleAttribute("hidden", tablet)',
            'cards.toggleAttribute("data-q8-tablet", tablet)',
            'window.matchMedia("(min-width: 901px) and (max-width: 1180px)")',
        ):
            self.assertIn(value, self.app)

    def test_overflow_accessibility_is_guarded_and_author_safe(self) -> None:
        for value in (
            'typeof document.querySelectorAll !== "function"',
            "const syncScrollableTableRegions = () =>",
            'shell.setAttribute("tabindex", "0")',
            'shell.setAttribute("role", "region")',
            "Scroll horizontally for more columns.",
            "queueQ8ResponsivePresentation",
        ):
            self.assertIn(value, self.app)

    def test_modes_preserve_information_and_remove_only_atmosphere(self) -> None:
        for value in (
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "@media print",
            "content: normal",
            "background: none",
        ):
            self.assertIn(value, self.finish)

    def test_current_log_loss_remains_live_and_not_hard_coded(self) -> None:
        self.assertGreaterEqual(
            self.build_tests.count("LIVE_SOURCE_TOLERANCES"),
            2,
        )
        self.assertIn(
            "validate_live_replay(summary, research)",
            self.build_tests,
        )
        self.assertNotIn(
            'replay["log_loss"],\n            0.87833346',
            self.build_tests,
        )
        self.assertEqual(self.app.count("number(replay.log_loss, 6)"), 1)
        self.assertIn('getJSON("data/summary.json")', self.app)
        self.assertIn('{ cache: "no-cache" }', self.app)
        self.assertIsNone(re.search(r"\b0\.878(?:33346|31572)\b", self.app))

    def test_home_copy_and_mobile_repairs_remain_authoritative(self) -> None:
        for value in (
            "A predictive rating, rebuilt from 1872",
            "International football, ranked in context.",
            "Opponents—and their opponents—matter.",
        ):
            self.assertIn(value, self.app)
        for value in (
            "Mobile Methodology tables edge-to-edge 2026-07-30",
            "Mobile Records country width 2026-07-30",
        ):
            self.assertIn(value, self.css)

    def test_every_route_uses_exact_current_asset_revisions(self) -> None:
        css_revision = hashlib.sha256(CSS.read_bytes()).hexdigest()[:12]
        app_revision = hashlib.sha256(APP.read_bytes()).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertGreaterEqual(len(routes), 250)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(
                f"assets/styles.css?v={css_revision}",
                html,
                route,
            )
            self.assertIn(
                f"assets/app.js?v={app_revision}",
                html,
                route,
            )


if __name__ == "__main__":
    unittest.main()
