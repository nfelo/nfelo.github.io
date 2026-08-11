from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Ribbon atelier definitive finishing system."


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


class RibbonAtelierReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The ribbon atelier marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_css_is_balanced_and_the_final_layer_is_last(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)
        self.assertTrue(
            self.css.rstrip().endswith("}"),
            "The release must be the final cascade.",
        )

    def test_audited_failures_are_addressed(self) -> None:
        for marker in (
            "overflow-x: clip;",
            "@supports not (overflow: clip)",
            ".methodology-page {",
            "width: min(1120px, calc(100vw - 48px));",
            "grid-template-columns: repeat(3, minmax(0, 1fr));",
            ".page-narrow > .split {",
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            ".panel-dark",
            "color: var(--atelier-on-dark-soft);",
            "--atelier-disabled-bg:",
            "opacity: 1;",
        ):
            self.assertIn(marker, self.finish)

    def test_team_names_and_questions_use_fraunces_but_data_does_not(
        self,
    ) -> None:
        for marker in (
            ".team-link,",
            ".comparison-team-name,",
            ".home-ranking-list li > a,",
            ".home-records li > div > a,",
            ".faq-item summary,",
            "font-family: var(--font-display);",
            ".team-picker select,",
            "font-family: var(--font-body);",
            'font-feature-settings: "lnum" 1, "tnum" 1;',
            "font-variant-numeric: lining-nums tabular-nums;",
        ):
            self.assertIn(marker, self.finish)

    def test_working_type_has_legible_floors(self) -> None:
        for marker in (
            "font-size: 16.5px;",
            "line-height: 1.62;",
            "font-size: 17px;",
            "line-height: 1.76;",
            "font-size: 13px;",
            "min-height: 48px;",
            "font-size: 12.5px;",
            "width: 24px;",
            "height: 28px;",
        ):
            self.assertIn(marker, self.finish)
        tiny = [
            float(value)
            for value in re.findall(
                r"font-size:\s*([0-9]+(?:\.[0-9]+)?)px",
                self.finish,
            )
            if float(value) < 12
        ]
        self.assertEqual(tiny, [])

    def test_home_matchups_are_compact_without_false_rank_selection(
        self,
    ) -> None:
        for marker in (
            "grid-template-columns:\n"
            "    minmax(350px, 0.95fr)\n"
            "    minmax(0, 1.05fr);",
            "minmax(280px, 440px)",
            ".home-records li > div > a:first-of-type",
            ".home-records li > div > small",
            ".home-ranking-list li:first-child,\n"
            ".ranking-table tbody tr:first-child,\n"
            ".ranking-card:first-child {\n"
            "  background: transparent;\n"
            "  box-shadow: none;",
        ):
            self.assertIn(marker, self.finish)

    def test_playful_details_are_structural_and_image_free(self) -> None:
        for marker in (
            "--atelier-vichy:",
            "pearl-chain hem",
            "ribbon-tail rule",
            "Picot lace",
            ".record-tabs::after",
            ".home-explore-links a::after",
            "clip-path: polygon(",
            "mother-of-pearl inspection",
            "Moonlit velvet",
        ):
            self.assertIn(marker, self.finish)
        for forbidden in (
            "url(",
            ".svg",
            ".png",
            "-webkit-mask:",
            "mask:",
            "animation:",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_result_semantics_and_logo_assets_are_untouched(self) -> None:
        for forbidden in (
            "--result-win:",
            "--result-draw:",
            "--result-loss:",
            ".form .W",
            ".form .D",
            ".form .L",
        ):
            self.assertNotIn(forbidden, self.finish)
        expected = {
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
        for filename, wanted in expected.items():
            actual = hashlib.sha256(
                (PUBLIC / filename).read_bytes()
            ).hexdigest()
            self.assertEqual(actual, wanted, filename)

    def test_light_dark_and_disabled_text_exceed_wcag_aa(self) -> None:
        pairs = (
            ("#3b1732", "#fff8fc"),
            ("#68475e", "#fff8fc"),
            ("#701c57", "#fff8fc"),
            ("#604052", "#fff8fc"),
            ("#6b5264", "#f0e4eb"),
            ("#fff6fc", "#27101f"),
            ("#e8cede", "#27101f"),
            ("#d1b9c8", "#35232f"),
            ("#edd5e4", "#27101f"),
            ("#fff6fc", "#35102e"),
            ("#f2d8e8", "#35102e"),
        )
        for foreground, background in pairs:
            with self.subTest(
                foreground=foreground,
                background=background,
            ):
                self.assertGreaterEqual(
                    contrast(foreground, background),
                    4.5,
                )

    def test_responsive_and_preference_contracts_are_complete(self) -> None:
        for marker in (
            "@media (min-width: 721px) and (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media (max-width: 430px)",
            "@media (max-width: 360px)",
            "@media (prefers-color-scheme: dark)",
            "@media (hover: none), (pointer: coarse)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (forced-colors: active)",
            "@media print",
        ):
            self.assertIn(marker, self.finish)

    def test_every_route_uses_the_new_stylesheet_hash(self) -> None:
        wanted = hashlib.sha256(
            CSS_PATH.read_bytes()
        ).hexdigest()[:12]
        routes = sorted(route for route in PUBLIC.rglob("index.html") if "clubs" not in route.relative_to(PUBLIC).parts)
        self.assertEqual(len(routes), 260)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(
                f"assets/styles.css?v={wanted}",
                html,
                route,
            )

    def test_standalone_404_echoes_the_release(self) -> None:
        html = (ROOT / "config" / "404.html").read_text(
            encoding="utf-8"
        )
        for marker in (
            "Ribbon atelier definitive echo",
            "--ribbon-rose:",
            "--ribbon-lilac:",
            "--ribbon-aqua:",
            "--ribbon-champagne:",
            "overflow-x: clip;",
            "clip-path: polygon(",
            "@media (prefers-color-scheme: dark)",
            "@media (max-width: 480px)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (forced-colors: active)",
            "@media print",
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
