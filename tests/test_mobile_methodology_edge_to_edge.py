from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "public" / "assets" / "styles.css"
MARKER = (
    "Mobile Methodology tables edge-to-edge 2026-07-30."
)
NEXT_MARKER = "Mobile Records country width 2026-07-30."


class MobileMethodologyEdgeToEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError(
                "Mobile Methodology edge-to-edge marker missing."
            )
        start = cls.css.index(MARKER)
        end = cls.css.index(NEXT_MARKER, start)
        cls.layer = cls.css[start:end]

    def test_layer_is_unique_ordered_and_balanced(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        self.assertEqual(self.css.count(NEXT_MARKER), 1)
        self.assertLess(
            self.css.index(MARKER),
            self.css.index(NEXT_MARKER),
        )
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)

    def test_only_methodology_tables_are_targeted(self) -> None:
        for expected in (
            "@media (max-width: 720px)",
            'body[data-route="methodology"]',
            ".methodology-page",
            "> .method-section > .table-shell",
        ):
            self.assertIn(expected, self.layer)
        for forbidden in (
            'body[data-route="records"]',
            'body[data-route="faq"]',
            'body[data-route="about"]',
            ".formula",
            ".method-details",
        ):
            self.assertNotIn(forbidden, self.layer)

    def test_mobile_tables_reclaim_both_page_insets(self) -> None:
        for expected in (
            "width: calc(100% + 24px);",
            "max-width: none;",
            "margin-inline: -12px;",
            "border-right: 0;",
            "border-left: 0;",
            "border-radius: 0;",
        ):
            self.assertIn(expected, self.layer)


if __name__ == "__main__":
    unittest.main()
