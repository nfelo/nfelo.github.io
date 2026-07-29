from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Rosewater couture hybrid."
ASSET_VERSION = "20260729l1"


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


def png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path.name} is not a PNG")
    return (
        int.from_bytes(payload[16:20], "big"),
        int.from_bytes(payload[20:24], "big"),
    )


class RosewaterCoutureHybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The rosewater hybrid marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_number_one_is_data_not_a_selected_state(self) -> None:
        self.assertNotIn("Haloed priority", self.css)
        self.assertIn(
            "Honest hierarchy keeps rank as data, "
            "never a selection state.",
            self.css,
        )
        for selector in (
            ".home-ranking-list li:first-child",
            ".ranking-table tbody tr:first-child",
            ".ranking-card:first-child",
        ):
            self.assertIn(selector, self.finish)
        self.assertIn(
            ".home-ranking-list li:first-child,\n"
            ".ranking-table tbody tr:first-child,\n"
            ".ranking-card:first-child {\n"
            "  background: transparent;\n"
            "  box-shadow: none;",
            self.finish,
        )

    def test_palette_is_feminine_without_recolouring_results(self) -> None:
        for marker in (
            "--hybrid-rose:",
            "--hybrid-lilac:",
            "--hybrid-aqua:",
            "--hybrid-apricot:",
            "--hybrid-champagne:",
            "--hybrid-velvet:",
            "rose-porcelain",
            "macaron and fine-seam presentation",
            "rosewater materials remain luminous",
        ):
            self.assertIn(marker, self.finish)
        for forbidden in (
            "--result-win:",
            "--result-loss:",
            ".form .W",
            ".form .L",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_reading_system_has_clear_minima_and_measure(self) -> None:
        for marker in (
            "font-size: 16px;",
            "line-height: 1.6;",
            "max-width: 72ch;",
            "font-size: 17px;",
            "line-height: 1.74;",
            "min-height: 46px;",
            "min-height: 48px;",
            "font-variant-numeric: lining-nums tabular-nums;",
            'font-feature-settings: "lnum" 1, "tnum" 1;',
        ):
            self.assertIn(marker, self.finish)
        tiny_sizes = [
            float(value)
            for value in re.findall(
                r"font-size:\s*([0-9]+(?:\.[0-9]+)?)px",
                self.finish,
            )
            if float(value) < 12
        ]
        self.assertEqual(tiny_sizes, [])

    def test_light_and_dark_text_pairs_exceed_wcag_aa(self) -> None:
        pairs = (
            ("#3d1835", "#fffafd"),
            ("#69475f", "#fffafd"),
            ("#701d59", "#fffafd"),
            ("#7b3265", "#fffafd"),
            ("#5e3b53", "#fffafd"),
            ("#fff5fb", "#29121f"),
            ("#efd7e7", "#29121f"),
            ("#ffaddb", "#29121f"),
            ("#ebcfe1", "#29121f"),
            ("#ead0e1", "#29121f"),
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

    def test_every_responsive_and_preference_mode_is_explicit(self) -> None:
        for marker in (
            "@media (min-width: 721px) and (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media (max-width: 430px)",
            "@media (hover: none), (pointer: coarse)",
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (forced-colors: active)",
            "@media print",
        ):
            self.assertIn(marker, self.finish)

    def test_finish_uses_material_and_not_downloaded_decoration(self) -> None:
        for forbidden in (
            "url(",
            ".svg",
            "-webkit-mask:",
            "mask:",
            "--bow-mask",
            "--flower-mask",
            "animation:",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_editorial_type_is_separate_from_working_type(self) -> None:
        for marker in (
            "Fraunces is an editorial accent, not the working typeface.",
            ".faq-item summary,\n  .team-picker select,",
            "font-family: var(--font-body);",
            "font-family: var(--font-display);",
            "font-size: clamp(42px, 5.5vw, 64px);",
            "font-size: 12.5px;",
        ):
            self.assertIn(marker, self.finish)

    def test_home_matchups_are_an_aligned_readable_grid(self) -> None:
        for marker in (
            "make the record list read as five",
            "grid-template-columns: 31px minmax(0, 1fr) 76px;",
            "grid-template-columns: minmax(0, 1fr) 22px minmax(0, 1fr);",
            ".home-records li > div > a:first-of-type {\n  text-align: right;",
            ".home-records li > div > small {\n  grid-column: 1 / -1;",
            ".home-records li > strong {\n  justify-self: end;",
            "@media (max-width: 430px)",
        ):
            self.assertIn(marker, self.finish)

    def test_faq_has_a_calm_desktop_column_and_mobile_layout(self) -> None:
        for marker in (
            "FAQ desktop: a centred editorial reading column",
            "width: min(1040px, calc(100vw - 44px));",
            "width: min(860px, 100%);",
            "grid-template-columns: minmax(300px, 1fr) auto;",
            "counter-reset: hybrid-faq;",
            "content: counter(hybrid-faq, decimal-leading-zero);",
            "font-family: var(--font-body);",
            "font-size: 17px;",
            "@media (max-width: 720px)",
            ".faq-tools {\n    grid-template-columns: 1fr;",
            ".faq-actions {\n    display: grid;\n    grid-template-columns: 1fr 1fr;",
        ):
            self.assertIn(marker, self.finish)

    def test_all_brand_outputs_come_from_one_updated_identity(self) -> None:
        primary = (PUBLIC / "favicon-2026.svg").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            primary,
            (PUBLIC / "favicon.svg").read_text(encoding="utf-8"),
        )
        for marker in (
            '<linearGradient id="aurora"',
            '<linearGradient id="rim"',
            '<radialGradient id="moonstone"',
            'd="M21 44.5V20.5l21.5 24V20.5"',
            'd="M15.5 25.5c9.5-5.5 22.5-5.5 32 0"',
        ):
            self.assertIn(marker, primary)
        maskable = (
            PUBLIC / "icon-maskable-2026.svg"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'd="M21 44.5V20.5l21.5 24V20.5"',
            maskable,
        )
        social = (PUBLIC / "social-card.svg").read_text(
            encoding="utf-8"
        )
        self.assertIn('<radialGradient id="aqua-glow">', social)
        self.assertIn(
            "International ratings, results and match forecasts",
            social,
        )
        expected = {
            "apple-touch-icon-2026.png": (180, 180),
            "icon-192-2026.png": (192, 192),
            "icon-512-2026.png": (512, 512),
            "social-card.png": (1200, 630),
        }
        for filename, dimensions in expected.items():
            self.assertEqual(
                png_dimensions(PUBLIC / filename),
                dimensions,
            )
        for filename in ("favicon-2026.ico", "favicon.ico"):
            icon = (PUBLIC / filename).read_bytes()
            self.assertEqual(icon[:4], b"\x00\x00\x01\x00")
            self.assertEqual(int.from_bytes(icon[4:6], "little"), 3)

    def test_routes_use_the_exact_new_identity_and_stylesheet(self) -> None:
        css_hash = hashlib.sha256(
            CSS_PATH.read_bytes()
        ).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertGreaterEqual(len(routes), 250)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(
                f"assets/styles.css?v={css_hash}",
                html,
                route,
            )
            self.assertIn(
                f"favicon-2026.svg?v={ASSET_VERSION}",
                html,
                route,
            )
            self.assertIn(
                f"apple-touch-icon-2026.png?v={ASSET_VERSION}",
                html,
                route,
            )
            self.assertIn(
                'content="#3b1232" '
                'media="(prefers-color-scheme: light)"',
                html,
                route,
            )
        manifest = json.loads(
            (PUBLIC / "site.webmanifest").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["background_color"], "#fff8fc")
        self.assertEqual(manifest["theme_color"], "#3b1232")
        self.assertTrue(
            all(
                ASSET_VERSION in icon["src"]
                for icon in manifest["icons"]
            )
        )


if __name__ == "__main__":
    unittest.main()
