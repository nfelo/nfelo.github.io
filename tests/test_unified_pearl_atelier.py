from __future__ import annotations

import colorsys
import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Unified pearl atelier finishing system."
END_MARKER = "Velvet botanical ledger unified system 2026-08-03."

LOGO_HASHES = {
    "favicon-2026.svg":
        "649147e32d2ae5e000a6cc44b2bc9d5ab1e1f2ec32b62fd3d0b04a7734fed1ff",
    "favicon.svg":
        "649147e32d2ae5e000a6cc44b2bc9d5ab1e1f2ec32b62fd3d0b04a7734fed1ff",
    "favicon-2026.ico":
        "0f0bc225dd59f4b5b840b660f20149c61c39536546452acfd807be57807e61d7",
    "favicon.ico":
        "0f0bc225dd59f4b5b840b660f20149c61c39536546452acfd807be57807e61d7",
    "apple-touch-icon-2026.png":
        "cb6431e450e087b89060fe432246563fbf75f7b0dfd77204fcda95acfa7b6d86",
    "icon-192-2026.png":
        "8cdb242ebbc757fcfe7ba37b707dda392fc55b618342ddf927c030d1dd8c2987",
    "icon-512-2026.png":
        "cc648859f5f6dbebcbb0fa862b4e510c2212137df76659cba517f182d699c38b",
    "icon-maskable-2026.svg":
        "87d39efb6f49ba8725a742b99bdbada6018e2ca7aa631597e1627667c6cd74a6",
    "social-card.svg":
        "ddd65437e8c70d129eb53ad362a50f9740af54335c05f05fdabd5d9573ca8558",
    "social-card.png":
        "0a96079b8755dae00361ce74a76a3e0fb2f0d6d346ee2bab66639ed2fd700b73",
    "site.webmanifest":
        "76f0094e761fd804591ff44320648ec8ef42a9139f193c23b3f4eb273a560364",
}


def luminance(colour: str) -> float:
    channels = [
        int(colour[index:index + 2], 16) / 255.0
        for index in (1, 3, 5)
    ]
    linear = [
        value / 12.92
        if value <= 0.04045
        else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return (
        0.2126 * linear[0]
        + 0.7152 * linear[1]
        + 0.0722 * linear[2]
    )


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted(
        (luminance(first), luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def hue(colour: str) -> float:
    channels = [
        int(colour[index:index + 2], 16) / 255.0
        for index in (1, 3, 5)
    ]
    return colorsys.rgb_to_hsv(*channels)[0] * 360


class UnifiedPearlAtelierReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The unified pearl atelier marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1].split(END_MARKER, 1)[0]

    def test_layer_is_unique_balanced_and_last(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)
        self.assertTrue(self.css.rstrip().endswith("}"))

    def test_home_actions_are_one_coherent_three_piece_set(self) -> None:
        for marker in (
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            "width: min(690px, 100%);",
            "--action-ribbon: var(--atelier-rose);",
            "grid-template-columns: 16px minmax(0, 1fr);",
            "font-family: var(--font-display);",
            ".home-intro .hero-actions .home-action::before {",
            "z-index: 1;",
            "display: inline-grid;",
            ".home-intro .hero-actions .home-action-rankings {",
            "--action-ribbon: #f0a7ca;",
            ".home-intro .hero-actions .home-action-fixtures {",
            "--action-ribbon: #cab5ea;",
            ".home-intro .hero-actions .home-action-predict {",
            "--action-ribbon: #acd9d5;",
            "grid-column: 1 / -1;",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn("z-index: -1;", self.finish)

    def test_home_panels_share_one_symmetric_frame(self) -> None:
        for marker in (
            "body[data-route=\"home\"] :is(.home-dashboard, .home-support) {",
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            "width: 100%;",
            "max-width: none;",
            "margin-inline: 0;",
            "align-items: stretch;",
            "body[data-route=\"home\"] :is(.home-dashboard, .home-support) > * {",
            "justify-self: stretch;",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn("width: min(1120px, 100%);", self.finish)

    def test_mobile_matchups_use_full_width_without_word_columns(self) -> None:
        for marker in (
            "@media (max-width: 520px)",
            "grid-template-columns: minmax(0, 1fr) auto;",
            "grid-column: 1 / -1;",
            "grid-row: 2;",
            "grid-template-columns: minmax(0, 1fr);",
            "> a:first-of-type {\n"
            "    grid-column: 1;\n"
            "    grid-row: 1;",
            "> i {\n"
            "    grid-column: 1;\n"
            "    grid-row: 2;",
            "> a:last-of-type {\n"
            "    grid-column: 1;\n"
            "    grid-row: 3;",
            "text-wrap: balance;",
            "overflow-wrap: normal;",
            "word-break: normal;",
            "min-height: 0;",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn("grid-row: 1 / span 2;", self.finish)

    def test_starting_strength_formula_fits_but_cards_remain_compact(
        self,
    ) -> None:
        for marker in (
            "--atelier-formula: 680px;",
            "inline-size: fit-content;",
            "width: fit-content;",
            "max-inline-size: min(var(--atelier-formula), 100%);",
            "max-width: min(var(--atelier-formula), 100%);",
            "overflow-x: auto;",
            "@media (max-width: 720px)",
            "max-inline-size: 100%;",
            "max-width: 100%;",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn("min(600px, 100%)", self.finish)
        self.assertNotIn("--atelier-formula: 820px;", self.finish)

    def test_mobile_ranking_cards_are_compact_and_country_led(self) -> None:
        for marker in (
            ".ranking-card-team .team-link {",
            "font-size: inherit;",
            ".ranking-card-heading {\n"
            "    display: contents;",
            "grid-template-areas:",
            "\"team rating\"",
            "\"rank rating\"",
            "\"snapshot snapshot\"",
            "\"details details\";",
            "grid-area: team;",
            "font-size: clamp(21px, 6vw, 24px);",
            "font-weight: 610;",
            "grid-area: rating;",
            "min-width: 76px;",
            "grid-area: snapshot;",
            "margin-top: 11px;",
            "min-height: 0;",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn("margin: -13px", self.finish)

    def test_lineage_is_a_wrapping_non_overlapping_keepsake(self) -> None:
        for marker in (
            ".record-note.team-lineage-note {",
            "grid-template-columns: max-content minmax(0, 1fr);",
            "gap: 10px 16px;",
            "width: 100%;",
            "max-width: 100%;",
            "min-width: 0;",
            ".record-note.team-lineage-note > strong {",
            "font-family: var(--font-display);",
            ".record-note.team-lineage-note > div {",
            "overflow-wrap: anywhere;",
            "grid-template-columns: minmax(0, 1fr);",
            "width: max-content;",
        ):
            self.assertIn(marker, self.finish)

    def test_venue_categories_are_distinct_from_result_semantics(self) -> None:
        palettes = (
            ("#f1d6e7", "#572746", "#deddf5", "#373765"),
            ("#6b456b", "#fff6fc", "#455f86", "#f6f3ff"),
        )
        for home_bg, home_ink, away_bg, away_ink in palettes:
            separation = abs(hue(home_bg) - hue(away_bg))
            separation = min(separation, 360 - separation)
            self.assertGreaterEqual(separation, 75)
            self.assertGreaterEqual(contrast(home_ink, home_bg), 4.5)
            self.assertGreaterEqual(contrast(away_ink, away_bg), 4.5)
        for marker in (
            "--venue-home-bg: #f1d6e7;",
            "--venue-away-bg: #deddf5;",
            ".venue-code.venue-H {",
            "border-radius: 56% 44% 56% 44% / 48% 56% 44% 52%;",
            ".venue-code.venue-A {",
            "border-radius: 8px 14px 8px 14px;",
            ".venue-code.venue-N {",
        ):
            self.assertIn(marker, self.finish)
        for forbidden in (
            "--result-win:",
            "--result-draw:",
            "--result-loss:",
            ".form .W",
            ".form .D",
            ".form .L",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_editorial_and_records_corrections_remain_authoritative(self) -> None:
        for marker in (
            "width: min(1040px, calc(100vw - 48px));",
            ".faq-answer,\n.faq-answer > p {",
            "max-inline-size: none;",
            ".record-tabs::before,\n.record-tabs::after {",
            "background: none;",
            "content: none;",
            "body .site-header a.brand > span > small {",
            "font-weight: 610;",
        ):
            self.assertIn(marker, self.finish)

    def test_playful_details_are_css_only_and_preference_safe(self) -> None:
        for marker in (
            "pearl stud",
            "grosgrain hems",
            "shell-jewel",
            "tulle-soft light",
            "lace-fine",
            "midnight-satin",
            "powder compacts",
            "archive ribbon",
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "@media print",
        ):
            self.assertIn(marker, self.finish)
        for forbidden in (
            "url(",
            ".svg",
            ".png",
            "-webkit-mask:",
            "mask:",
            "animation:",
            "display: none",
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

    def test_logo_assets_are_byte_for_byte_locked(self) -> None:
        for filename, wanted in LOGO_HASHES.items():
            actual = hashlib.sha256(
                (PUBLIC / filename).read_bytes()
            ).hexdigest()
            self.assertEqual(actual, wanted, filename)

    def test_every_route_uses_the_correct_stylesheet_hash(self) -> None:
        wanted = hashlib.sha256(CSS_PATH.read_bytes()).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertEqual(len(routes), 260)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(
                f"assets/styles.css?v={wanted}",
                html,
                route,
            )


if __name__ == "__main__":
    unittest.main()
