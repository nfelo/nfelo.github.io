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
            "favicon-2026.ico?v=20260728f2",
            "favicon-2026.svg?v=20260728f2",
            "apple-touch-icon-2026.png?v=20260728f2",
            "site.webmanifest?v=20260728f2",
            "social-card.png?v=20260728f2",
            f"assets/styles.css?v={stylesheet_hash}",
            (
                '<img class="brand-mark" '
                'src="favicon-2026.svg?v=20260728f2"'
            ),
        )
        obsolete = (
            'content="#301032"',
            "site.webmanifest?v=20260723",
            "styles.css?v=6be8afb7b626",
            "favicon-2026.svg?v=20260727",
            "favicon-2026.svg?v=20260728\"",
            '<span class="brand-mark"',
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
            '--font-display: "Fraunces Variable", Candara, Corbel',
            '--font-numeric: "Aptos", Calibri',
            'font-feature-settings: "lnum" 1, "tnum" 1;',
            "font-variant-numeric: lining-nums tabular-nums;",
            "Floral editorial presentation system",
            "Floral couture refinement",
            "Dainty botanical wash",
            "atmosphere rather than applied ornament",
            "Repeated information should read as data",
            "Pearlescent editorial finish",
            "maximal femininity without applied decoration",
            ".brand:hover .brand-mark",
            ".eyebrow::before",
            ".page-heading::after",
            ".button-primary::before",
            ".chronology-cause::before",
            "--botanical-blush:",
            "--botanical-lilac:",
            "--botanical-edge:",
            "--pearl-sheen:",
            "--powder-pink:",
            "--rose-focus:",
            '"SOFT" 92',
            "@media (hover: hover) and (pointer: fine)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (min-width: 721px) and (max-width: 1024px)",
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
        final_cascade = stylesheet.split(
            "Dainty botanical wash",
            1,
        )[1]
        for applied_art in (
            "botanical-sprig-2026.svg",
            "floral-divider-2026.svg",
            "floral-corner-rose-2026.svg",
            "floral-corner-blossom-2026.svg",
            "floral-ribbon-2026.svg",
            "--bow-mask",
            "--blossom-mask",
        ):
            self.assertNotIn(applied_art, final_cascade)
        self.assertIn(
            ".button-primary::before",
            final_cascade,
        )
        self.assertIn(
            "content: none;",
            final_cascade,
        )
        pearlescent_cascade = stylesheet.split(
            "Pearlescent editorial finish",
            1,
        )[1]
        for applied_art in (
            "botanical-sprig-2026.svg",
            "floral-divider-2026.svg",
            "floral-corner-rose-2026.svg",
            "floral-corner-blossom-2026.svg",
            "floral-ribbon-2026.svg",
            "--bow-mask",
            "--blossom-mask",
        ):
            self.assertNotIn(
                applied_art,
                pearlescent_cascade,
            )
        for interaction in (
            "background-position 0.25s ease;",
            "tbody tr:hover",
            "outline: 3px solid rgba(226, 112, 177, 0.25);",
        ):
            self.assertIn(
                interaction,
                pearlescent_cascade,
            )
        definitions = set(
            re.findall(r"--([\w-]+)\s*:", stylesheet)
        )
        references = set(
            re.findall(r"var\(--([\w-]+)", stylesheet)
        )
        self.assertEqual(references - definitions, set())
        font = PUBLIC / "assets" / "fonts" / "fraunces-variable-latin-v38.woff2"
        self.assertEqual(font.read_bytes()[:4], b"wOF2")
        self.assertIn(
            "SIL OPEN FONT LICENSE",
            (
                PUBLIC
                / "assets"
                / "fonts"
                / "Fraunces-OFL.txt"
            ).read_text(encoding="utf-8"),
        )

    def test_light_and_dark_text_contrast(self) -> None:
        pairs = (
            ("#3d1f38", "#fffafd"),
            ("#705268", "#fffafd"),
            ("#7b286b", "#fffafd"),
            ("#944174", "#fffafd"),
            ("#8f3d70", "#fffafd"),
            ("#7c3a68", "#f7d9e9"),
            ("#7c3a68", "#d9c5e5"),
            ("#fff9fd", "#43133c"),
            ("#f1dceb", "#43133c"),
            ("#35102e", "#ff9bd5"),
            ("#35102e", "#f6b2d5"),
            ("#35102e", "#d5e7e5"),
            ("#35102e", "#ffe8f3"),
            ("#35102e", "#f7bad9"),
            ("#35102e", "#e3caef"),
            ("#fff9fd", "#27111f"),
            ("#e4ccdc", "#27111f"),
            ("#f3a8dc", "#27111f"),
            ("#fff9fd", "#6f3466"),
            ("#fff9fd", "#8b537b"),
            ("#fff9fd", "#583046"),
            ("#fff9fd", "#493554"),
            ("#ffc3e2", "#43133c"),
            ("#ffc3e2", "#4c193f"),
            ("#fff9fd", "#5c3151"),
            ("#fff9fd", "#44223b"),
            ("#fff9fd", "#35233f"),
            ("#fff9fd", "#2f7657"),
            ("#fff9fd", "#a93b55"),
            ("#35102e", "#f3b9d8"),
            ("#fff9fd", "#a64f84"),
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

    def test_fairytale_couture_finish_is_material_led_and_responsive(
        self,
    ) -> None:
        stylesheet = STYLES.read_text(encoding="utf-8")
        marker = (
            "Fairytale couture spectrum: "
            "ten material-led feminine refinements"
        )
        self.assertIn(marker, stylesheet)
        finish = stylesheet.split(marker, 1)[1]

        for numbered_idea in (
            "1. Rosewater, lavender and sea-pearl atmosphere.",
            "2. Softer, fashion-editorial display typography.",
            "3. A perfume-seal setting",
            "4. Organza and tulle layering",
            "5. Mother-of-pearl inner frames",
            "6. Powder-compact surfaces",
            "7. Satin controls",
            "8. Pearl-like details",
            "9. Whisper-soft row rhythm",
            "10. A moonlit version",
        ):
            self.assertIn(numbered_idea, finish)

        for implementation in (
            "--fairy-rose:",
            "--princess-lilac:",
            "--mermaid-pearl:",
            '"SOFT" 100',
            "font-weight: 445;",
            "text-wrap: balance;",
            ".brand-mark {",
            ".hero::before,",
            "--couture-tint: var(--fairy-rose);",
            "--couture-tint: var(--princess-lilac);",
            "--couture-tint: var(--mermaid-pearl);",
            "background-size: 175% 100%;",
            ".home-rank {",
            "tbody tr:nth-child(even)",
            "@media (prefers-color-scheme: dark)",
            "@media (min-width: 721px) and (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media (prefers-reduced-motion: reduce)",
        ):
            self.assertIn(implementation, finish)

        for excluded_decoration in (
            ".svg",
            "url(",
            "-webkit-mask:",
            "mask:",
            "--bow-mask",
            "--blossom-mask",
        ):
            self.assertNotIn(excluded_decoration, finish)

        self.assertNotIn("--result-win:", finish)
        self.assertNotIn("--result-loss:", finish)

    def test_atelier_reverie_adds_ten_distinct_accessible_finishes(
        self,
    ) -> None:
        stylesheet = STYLES.read_text(encoding="utf-8")
        marker = (
            "Atelier reverie: "
            "ten further feminine refinements"
        )
        self.assertIn(marker, stylesheet)
        finish = stylesheet.split(marker, 1)[1]

        for numbered_idea in (
            "1. Ballet-wrap geometry",
            "2. Porcelain cameo settings",
            "3. Micro-embroidered seams",
            "4. Opal and moonstone mats",
            "5. Fine-jewellery tray compartments",
            "6. Glossed silk data bars",
            "7. Delicate perfume-label microtype",
            "8. Pink-sapphire double focus halos",
            "9. Alternating draped silhouettes",
            "10. Bridal-stationery double rules",
        ):
            self.assertIn(numbered_idea, finish)

        for implementation in (
            "--ballet-ribbon-light:",
            "--cameo-edge:",
            "--embroidery-stitch:",
            "--opal-rose:",
            "--atelier-focus:",
            ".record-tabs .button[aria-pressed=\"true\"]",
            ".team-rating {",
            "border-radius: 50% / 44%;",
            ".page-heading::after {",
            ".chart-stage {",
            ".probability .pw,",
            "font-style: italic;",
            "):focus-visible {",
            "> :nth-child(4n + 1)",
            "border: 3px double var(--stationery-line);",
            "@media (prefers-color-scheme: dark)",
            "@media (min-width: 721px) and (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media print",
        ):
            self.assertIn(implementation, finish)

        for excluded_decoration in (
            ".svg",
            "url(",
            "-webkit-mask:",
            "mask:",
            "--bow-mask",
            "--blossom-mask",
            "--flower-mask",
            "animation:",
        ):
            self.assertNotIn(excluded_decoration, finish)

        self.assertNotIn("--result-win:", finish)
        self.assertNotIn("--result-loss:", finish)
        self.assertIn(
            "without changing W/D/L colours",
            finish,
        )
        self.assertIn(
            "min-width: 320px;",
            stylesheet,
        )
        self.assertIn(
            "min-height: 44px;",
            stylesheet,
        )

    def test_final_keepsake_polish_adds_ten_responsive_finishes(
        self,
    ) -> None:
        stylesheet = STYLES.read_text(encoding="utf-8")
        marker = (
            "Final keepsake polish: "
            "nine interface refinements plus one unified emblem"
        )
        self.assertIn(marker, stylesheet)
        finish = stylesheet.split(marker, 1)[1]

        for numbered_idea in (
            "1. A restrained scalloped couture hem",
            "2. Selected and pressed controls",
            "3. Form controls read like blush-glass vanity drawers",
            "4. Table headings use a very fine pleated-satin rhythm",
            "5. Horizontally scrollable data",
            "6. Small data markers become polished cabochons",
            "7. Expandable explanations open like powder compacts",
            "8. Pagination reads as one compact vanity tray",
            "9. Rosewater selection and ink details",
            "10. A unified pearl-cameo N emblem",
        ):
            self.assertIn(numbered_idea, finish)

        for implementation in (
            "--keepsake-lace:",
            "--lacquer-glint:",
            "--vanity-lip:",
            "--pearl-scroll:",
            ".site-footer::before",
            "[aria-disabled=\"true\"]",
            "caret-color: var(--atelier-focus);",
            "repeating-linear-gradient(",
            "::-webkit-scrollbar-thumb",
            ".venue-code {",
            ")[open] > summary",
            ".match-pagination {",
            "::selection {",
            "@media (prefers-color-scheme: dark)",
            "@media (min-width: 721px) and (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media print",
            "@media (prefers-reduced-motion: reduce)",
        ):
            self.assertIn(implementation, finish)

        self.assertNotIn("--result-win:", finish)
        self.assertNotIn("--result-loss:", finish)
        self.assertIn("min-width: 320px;", stylesheet)
        self.assertIn("min-height: 44px;", stylesheet)

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
            '<radialGradient id="pearl"',
            '<linearGradient id="monogram"',
            'd="M21.5 44V21l21 23V21"',
            '<circle cx="49.2" cy="15.2"',
        ):
            self.assertIn(marker, primary_svg)
        self.assertEqual(primary_svg.count("<ellipse"), 2)
        self.assertNotIn('<radialGradient id="petal">', primary_svg)
        self.assertNotIn("l1.5 4.5L56 15", primary_svg)
        maskable_svg = (
            PUBLIC / "icon-maskable-2026.svg"
        ).read_text(encoding="utf-8")
        self.assertIn('<rect width="64" height="64" fill="#35102f"/>', maskable_svg)
        self.assertIn('d="M21.5 44V21l21 23V21"', maskable_svg)
        social_svg = (PUBLIC / "social-card.svg").read_text(
            encoding="utf-8"
        )
        self.assertIn("Fraunces, Corbel, Candara", social_svg)
        self.assertIn('<radialGradient id="pearl"', social_svg)
        self.assertIn('d="M43 92V44l46 48V44"', social_svg)
        self.assertNotIn('<g id="flower">', social_svg)
        self.assertIn("International ratings, results", social_svg)

        manifest = json.loads(
            (PUBLIC / "site.webmanifest").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["background_color"], "#fff8fc")
        self.assertEqual(manifest["theme_color"], "#43133c")
        self.assertEqual(
            {icon["src"] for icon in manifest["icons"]},
            {
                "icon-192-2026.png?v=20260728f2",
                "icon-512-2026.png?v=20260728f2",
            },
        )
        self.assertTrue(
            all(
                icon["purpose"] == "any maskable"
                for icon in manifest["icons"]
            )
        )

    def test_standalone_404_matches_the_presentation(self) -> None:
        html = (ROOT / "config" / "404.html").read_text(
            encoding="utf-8"
        )
        for marker in (
            'content="#43133c"',
            'content="#10070e"',
            "favicon-2026.svg?v=20260728f2",
            "apple-touch-icon-2026.png?v=20260728f2",
            "font-variant-numeric: lining-nums tabular-nums",
            'font-family: "Fraunces Variable", Candara, Corbel',
            "linear-gradient(118deg",
            "radial-gradient(ellipse 34rem 23rem",
            "radial-gradient(ellipse 32rem 22rem",
            "--fairy-rose:",
            "--princess-lilac:",
            "--mermaid-pearl:",
            "--atelier-focus:",
            "--embroidery-stitch:",
            "--stationery-line:",
            "Final keepsake polish for the standalone route",
            "--keepsake-lace:",
            "--lacquer-glint:",
            "--rosewater-selection:",
            "::selection",
            "main::before",
            "main::after",
            "border: 3px double var(--stationery-line)",
            "linear-gradient(35deg",
            "font-weight: 445",
            '"SOFT" 100',
            "text-wrap: balance",
            "#fff8fc;",
            "#170b14;",
            "@media (max-width: 480px)",
            "@media (prefers-reduced-motion: reduce)",
            "@media print",
        ):
            self.assertIn(marker, html)
        for applied_art in (
            "floral-corner-",
            "floral-ribbon",
            "floral-divider",
            "-webkit-mask:",
            "mask:",
        ):
            self.assertNotIn(applied_art, html)


if __name__ == "__main__":
    unittest.main()
