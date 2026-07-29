from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "public" / "assets" / "styles.css"
NOT_FOUND_PATH = ROOT / "config" / "404.html"
MARKER = (
    "Couture alphabet: twenty-six new feminine, "
    "functional refinements."
)


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


class CoutureAlphabetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.not_found = NOT_FOUND_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The couture alphabet marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_the_complete_alphabet_is_present_once_and_in_order(
        self,
    ) -> None:
        found = re.findall(
            r"/\*\s*([A-Z])\.\s+([^*]+?)\s*\*/",
            self.finish,
        )
        self.assertEqual(
            [letter for letter, _ in found],
            list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        )
        self.assertEqual(len(found), 26)

    def test_each_refinement_has_a_distinct_material_or_function(
        self,
    ) -> None:
        labels = (
            "Airy editorial measure",
            "Beauty-counter labelling",
            "Corsetry seams",
            "Dewdrop active states",
            "Eau-de-rose route rails",
            "Frosted-blush worktops",
            "Gossamer double rules",
            "Honest hierarchy",
            "Intaglio microtype",
            "Jewellery-casket tabs",
            "Kiss-cut chips",
            "Letterpress notes",
            "Marquise markers",
            "Nacreous table light",
            "Opera-programme rhythm",
            "Perfume-blotter callouts",
            "Quilted metric compartments",
            "Rouge-lacquer primary actions",
            "Silk-thread links",
            "Tulle title veils",
            "Ultrafine data hairlines",
            "Velvet dark mode",
            "Waterline chart inspection",
            "eXpressive scale",
            "Yoked tool layouts",
            "Zero-clutter responsive and preference modes",
        )
        for label in labels:
            self.assertIn(label, self.finish)

    def test_no_information_or_result_semantics_are_hidden_or_recoloured(
        self,
    ) -> None:
        for forbidden in (
            "display: none",
            "visibility: hidden",
            "--result-win:",
            "--result-draw:",
            "--result-loss:",
            ".form .W",
            ".form .L",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_the_finish_uses_no_literal_or_downloaded_decorative_art(
        self,
    ) -> None:
        for forbidden in (
            ".svg",
            "url(",
            "-webkit-mask:",
            "mask:",
            "--bow-mask",
            "--blossom-mask",
            "--flower-mask",
            "animation:",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_focus_and_primary_action_colours_have_strong_contrast(
        self,
    ) -> None:
        pairs = (
            ("#8d296b", "#fff6fb"),
            ("#ff91cf", "#1b0d17"),
            ("#fff4fb", "#8d296b"),
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
        self.assertIn(
            "outline: 3px solid var(--alphabet-lacquer);",
            self.finish,
        )
        self.assertIn("outline-offset: 3px;", self.finish)

    def test_responsive_and_user_preference_contracts_are_complete(
        self,
    ) -> None:
        markers = (
            "@media (min-width: 721px) and (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media (max-width: 360px)",
            "@media (hover: none), (pointer: coarse)",
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (forced-colors: active)",
            "@media print",
            "min-height: 48px;",
            "--content: calc(100vw - 24px);",
        )
        for marker in markers:
            self.assertIn(marker, self.finish)

    def test_numeric_alignment_and_readable_label_sizes_are_explicit(
        self,
    ) -> None:
        self.assertIn(
            "font-variant-numeric: lining-nums tabular-nums;",
            self.finish,
        )
        self.assertIn("font-family: var(--font-numeric);", self.finish)
        self.assertIn("font-size: 12px;", self.finish)
        tiny_sizes = [
            int(value)
            for value in re.findall(
                r"font-size:\s*([0-9]+)px",
                self.finish,
            )
            if int(value) < 12
        ]
        self.assertEqual(tiny_sizes, [])

    def test_translucency_has_an_opaque_accessible_fallback(
        self,
    ) -> None:
        self.assertIn(
            "backdrop-filter: blur(14px) saturate(1.06);",
            self.finish,
        )
        fallback = self.finish.split(
            "@media (prefers-reduced-transparency: reduce)",
            1,
        )[1]
        self.assertIn("background: var(--surface);", fallback)
        self.assertIn("backdrop-filter: none;", fallback)

    def test_standalone_page_echoes_the_system_in_every_mode(
        self,
    ) -> None:
        markers = (
            "Couture alphabet echo for the standalone route.",
            "--alphabet-rose: #ef9ecb;",
            "--alphabet-lacquer: #8d296b;",
            "--alphabet-lacquer: #ff91cf;",
            "outline: 3px solid var(--alphabet-lacquer);",
            "@media (hover: none), (pointer: coarse)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "@media print",
        )
        for marker in markers:
            self.assertIn(marker, self.not_found)

    def test_css_block_is_structurally_balanced(self) -> None:
        without_comments = re.sub(
            r"/\*.*?\*/",
            "",
            self.finish,
            flags=re.DOTALL,
        )
        self.assertEqual(
            without_comments.count("{"),
            without_comments.count("}"),
        )


if __name__ == "__main__":
    unittest.main()
