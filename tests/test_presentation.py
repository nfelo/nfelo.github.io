from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
STYLES = PUBLIC / "assets" / "styles.css"


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


class PresentationReleaseTests(unittest.TestCase):
    def test_every_route_uses_the_same_versioned_presentation(self) -> None:
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertGreaterEqual(len(routes), 250)
        stylesheet_hash = hashlib.sha256(
            STYLES.read_bytes()
        ).hexdigest()[:12]
        required = (
            (
                '<meta name="theme-color" content="#43133c" '
                'media="(prefers-color-scheme: light)">'
            ),
            (
                '<meta name="theme-color" content="#10070e" '
                'media="(prefers-color-scheme: dark)">'
            ),
            "favicon-2026.ico?v=20260727",
            "favicon-2026.svg?v=20260727",
            "apple-touch-icon-2026.png?v=20260727",
            "site.webmanifest?v=20260727",
            "social-card.png?v=20260727",
            f"assets/styles.css?v={stylesheet_hash}",
            '<span class="brand-mark" aria-hidden="true">',
        )
        obsolete = (
            'content="#301032"',
            "site.webmanifest?v=20260723",
            "styles.css?v=6be8afb7b626",
        )
        for route in routes:
            html = route.read_text(encoding="utf-8")
            for marker in required:
                self.assertIn(marker, html, route)
            for marker in obsolete:
                self.assertNotIn(marker, html, route)

    def test_type_and_component_system_remains_readable(self) -> None:
        stylesheet = STYLES.read_text(encoding="utf-8")
        for marker in (
            '--font-body: "Aptos", Calibri',
            "--font-display: Corbel, Candara",
            '--font-numeric: "Aptos", Calibri',
            'font-feature-settings: "lnum" 1, "tnum" 1;',
            "font-variant-numeric: lining-nums tabular-nums;",
            "Refined rose-and-lavender presentation system",
            ".brand-mark::after",
            ".eyebrow::before",
            "@media (prefers-color-scheme: dark)",
            "@media (max-width: 720px)",
            "min-height: 44px;",
        ):
            self.assertIn(marker, stylesheet)
        weights = [
            int(value)
            for value in re.findall(
                r"font-weight:\s*([0-9]+)",
                stylesheet,
            )
        ]
        self.assertTrue(weights)
        self.assertGreaterEqual(min(weights), 400)
        self.assertGreaterEqual(
            stylesheet.count("--result-win: #2f7657;"),
            2,
        )
        self.assertGreaterEqual(
            stylesheet.count("--result-loss: #a93b55;"),
            2,
        )
        definitions = set(
            re.findall(r"--([\w-]+)\s*:", stylesheet)
        )
        references = set(
            re.findall(r"var\(--([\w-]+)", stylesheet)
        )
        self.assertEqual(references - definitions, set())

    def test_light_and_dark_text_contrast(self) -> None:
        pairs = (
            ("#3d1f38", "#fffafd"),
            ("#705268", "#fffafd"),
            ("#7b286b", "#fffafd"),
            ("#fff9fd", "#43133c"),
            ("#f1dceb", "#43133c"),
            ("#35102e", "#ff9bd5"),
            ("#fff9fd", "#27111f"),
            ("#e4ccdc", "#27111f"),
            ("#f3a8dc", "#27111f"),
            ("#fff9fd", "#6f3466"),
            ("#fff9fd", "#2f7657"),
            ("#fff9fd", "#a93b55"),
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

    def test_brand_assets_cover_browser_apple_android_and_sharing(self) -> None:
        expected_png_sizes = {
            "apple-touch-icon-2026.png": (180, 180),
            "icon-192-2026.png": (192, 192),
            "icon-512-2026.png": (512, 512),
            "social-card.png": (1200, 630),
        }
        for filename, dimensions in expected_png_sizes.items():
            self.assertEqual(
                png_dimensions(PUBLIC / filename),
                dimensions,
            )
        for filename in ("favicon-2026.ico", "favicon.ico"):
            icon = (PUBLIC / filename).read_bytes()
            self.assertEqual(icon[:4], b"\x00\x00\x01\x00")
            self.assertEqual(
                int.from_bytes(icon[4:6], "little"),
                3,
            )
        primary_svg = (PUBLIC / "favicon-2026.svg").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            primary_svg,
            (PUBLIC / "favicon.svg").read_text(encoding="utf-8"),
        )
        for marker in (
            'aria-label="Network Football Elo"',
            'stop-color="#ff8fce"',
            'fill="#ffe0f2"',
        ):
            self.assertIn(marker, primary_svg)
        social_svg = (PUBLIC / "social-card.svg").read_text(
            encoding="utf-8"
        )
        self.assertIn("Corbel, Candara", social_svg)
        self.assertIn("International ratings, results", social_svg)

        manifest = json.loads(
            (PUBLIC / "site.webmanifest").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["background_color"], "#fff8fc")
        self.assertEqual(manifest["theme_color"], "#43133c")
        self.assertEqual(
            {icon["src"] for icon in manifest["icons"]},
            {
                "icon-192-2026.png?v=20260727",
                "icon-512-2026.png?v=20260727",
            },
        )

    def test_standalone_404_matches_the_presentation(self) -> None:
        html = (ROOT / "config" / "404.html").read_text(
            encoding="utf-8"
        )
        for marker in (
            'content="#43133c"',
            'content="#10070e"',
            "favicon-2026.svg?v=20260727",
            "apple-touch-icon-2026.png?v=20260727",
            "font-variant-numeric: lining-nums tabular-nums",
            "font-family: Corbel, Candara",
            "background: #fff8fc",
            "background: #170b14",
            "@media (max-width: 480px)",
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
