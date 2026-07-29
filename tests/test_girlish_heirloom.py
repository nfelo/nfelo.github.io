from __future__ import annotations

import colorsys
import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Girlish heirloom corrective finish."

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


class GirlishHeirloomReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The girlish heirloom marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

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

    def test_mobile_matchup_has_semantic_visual_order(self) -> None:
        for marker in (
            "@media (max-width: 520px)",
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
            "> small {\n"
            "    grid-column: 1;\n"
            "    grid-row: 4;",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn("grid-row: 1 / span 2;", self.finish)

    def test_records_has_no_bow_rail_or_dots(self) -> None:
        self.assertIn(
            ".record-tabs::before,\n.record-tabs::after {",
            self.finish,
        )
        for marker in (
            "width: 0;",
            "height: 0;",
            "background: none;",
            "content: none;",
            "padding-bottom: 0;",
        ):
            self.assertIn(marker, self.finish)
        self.assertIn(".record-tabs .button:nth-child(3n + 1)", self.finish)
        self.assertIn(".record-tabs .button[aria-pressed=\"true\"]", self.finish)

    def test_home_buttons_are_fraunces_pearl_satin_and_dark_safe(self) -> None:
        for marker in (
            "font-family: var(--font-display);",
            "font-size: 16.5px;",
            "font-weight: 610;",
            ".home-intro .hero-actions .home-action::before {",
            "border-radius: 50%;",
            "--heirloom-rose: #ee8fbe;",
            "--heirloom-lilac: #c7a4e8;",
            "--heirloom-aqua: #94d2cc;",
            "#ec8dbc 52%",
            "#b58ad8 52%",
            "#5ca9a4 52%",
        ):
            self.assertIn(marker, self.finish)
        for background in (
            "#ee8fbe",
            "#c7a4e8",
            "#94d2cc",
            "#d762a0",
            "#a477ca",
            "#4b9692",
        ):
            self.assertGreaterEqual(contrast("#321128", background), 4.5)

    def test_formulae_are_visibly_compact_on_desktop_and_fluid_on_mobile(
        self,
    ) -> None:
        for marker in (
            "--heirloom-formula: 640px;",
            "inline-size: min(var(--heirloom-formula), 100%);",
            "max-inline-size: var(--heirloom-formula);",
            "width: min(var(--heirloom-formula), 100%);",
            "max-width: var(--heirloom-formula);",
            "inline-size: min(600px, 100%);",
            "max-inline-size: 600px;",
            "@media (max-width: 720px)",
            "max-inline-size: 100%;",
            "max-width: 100%;",
        ):
            self.assertIn(marker, self.finish)

    def test_faq_answer_uses_the_full_accordion_interior(self) -> None:
        for marker in (
            ".faq-answer {",
            "box-sizing: border-box;",
            "inline-size: 100%;",
            "max-inline-size: none;",
            "width: 100%;",
            "max-width: none;",
            ".faq-answer > p {",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn("max-width: 76ch;", self.finish)

    def test_home_and_away_have_distinct_hues_shapes_and_contrast(self) -> None:
        pairs = (
            ("#9b2f6d", "#1d6970"),
            ("#a63372", "#227178"),
        )
        for home, away in pairs:
            separation = abs(hue(home) - hue(away))
            separation = min(separation, 360 - separation)
            self.assertGreaterEqual(separation, 75)
            self.assertGreaterEqual(contrast("#ffffff", home), 4.5)
            self.assertGreaterEqual(contrast("#ffffff", away), 4.5)
        for marker in (
            ".venue-code.venue-H {",
            "border-radius: 50%;",
            ".venue-code.venue-A {",
            "border-radius: 7px 13px 7px 13px;",
            "border: 2px solid #f7bfd9;",
            "border: 2px solid #a9ddd9;",
        ):
            self.assertIn(marker, self.finish)

    def test_playful_details_are_css_only_and_preference_safe(self) -> None:
        for marker in (
            "jewellery-box",
            "pearl catches",
            "satin",
            "picot-like inner seams",
            "rose-quartz",
            "sea-glass",
            "powder-case",
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

    def test_result_semantics_and_logo_assets_are_locked(self) -> None:
        for forbidden in (
            "--result-win:",
            "--result-draw:",
            "--result-loss:",
            ".form .W",
            ".form .D",
            ".form .L",
        ):
            self.assertNotIn(forbidden, self.finish)
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
