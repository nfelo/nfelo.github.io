from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Editorial keepsake corrective finishing system."

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


class EditorialKeepsakeReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The editorial keepsake marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_corrective_layer_is_unique_balanced_and_last(self) -> None:
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

    def test_header_descriptor_and_hero_strapline_are_legible(self) -> None:
        for marker in (
            "body .site-header a.brand > span > small {",
            "color: #f8e8f2;",
            "font-weight: 650;",
            ".home-intro .home-intro-copy > .eyebrow {",
            "font-weight: 620;",
            "letter-spacing: 0.105em;",
        ):
            self.assertIn(marker, self.finish)
        self.assertGreaterEqual(contrast("#f8e8f2", "#35102e"), 4.5)

    def test_home_actions_are_a_coherent_three_colour_set(self) -> None:
        for marker in (
            ".home-intro .hero-actions .home-action {",
            "border-radius: 999px;",
            ".home-intro .hero-actions .home-action-rankings {",
            "#f3b7d4 48%",
            ".home-intro .hero-actions .home-action-fixtures {",
            "#ddccef 50%",
            ".home-intro .hero-actions .home-action-predict {",
            "#cbe8e4 50%",
            "grid-template-columns: minmax(0, 1fr);",
            "min-height: 48px;",
        ):
            self.assertIn(marker, self.finish)
        for background in ("#f3b7d4", "#ddccef", "#cbe8e4"):
            self.assertGreaterEqual(contrast("#3d1733", background), 4.5)

    def test_home_matchups_are_compact_and_reflow_on_phones(self) -> None:
        for marker in (
            "minmax(420px, 520px);",
            "width: min(1120px, 100%);",
            "max-width: 520px;",
            "grid-template-columns:\n"
            "    28px\n"
            "    minmax(0, 1fr)\n"
            "    66px;",
            "@media (max-width: 720px)",
            "body[data-route=\"home\"] .home-support {\n"
            "    grid-template-columns: minmax(0, 1fr);\n"
            "    width: 100%;",
            "@media (max-width: 430px)",
            "grid-template-columns: 22px minmax(0, 1fr);",
            "grid-row: 1 / span 2;",
        ):
            self.assertIn(marker, self.finish)

    def test_editorial_pages_share_shell_and_content_geometry(self) -> None:
        for marker in (
            "--keepsake-shell: 1040px;",
            "--keepsake-lane: 900px;",
            "--keepsake-reading: 780px;",
            ".faq-page,",
            ".methodology-page,",
            "body[data-route=\"about\"] .page-narrow",
            "width: min(var(--keepsake-shell), calc(100vw - 48px));",
            "width: min(var(--keepsake-lane), 100%);",
            "width: min(var(--keepsake-reading), 100%);",
        ):
            self.assertIn(marker, self.finish)

    def test_formulae_are_bounded_and_scroll_internally(self) -> None:
        for marker in (
            "--keepsake-formula: 820px;",
            ".methodology-page .formula {",
            "box-sizing: border-box;",
            "inline-size: min(var(--keepsake-formula), 100%);",
            "max-inline-size: var(--keepsake-formula);",
            "overflow-x: auto;",
            ".methodology-page .method-details .formula {",
            "max-inline-size: 780px;",
        ):
            self.assertIn(marker, self.finish)

    def test_records_bow_is_removed_not_replaced(self) -> None:
        self.assertIn(
            ".record-tabs::after {\n  content: none;\n}",
            self.finish,
        )
        self.assertIn(
            "A flat point-d'esprit seam",
            self.finish,
        )

    def test_playful_details_are_css_only_and_preference_safe(self) -> None:
        for marker in (
            "--keepsake-point-desprit:",
            "point-d'esprit",
            "tulle dots",
            "fine lace seam",
            "pearl wayfinding",
            "veil-like light",
            "satin",
            "piping and small glass catchlights",
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
        routes = sorted(route for route in PUBLIC.rglob("index.html") if "clubs" not in route.relative_to(PUBLIC).parts)
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
