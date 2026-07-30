from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "public" / "assets" / "styles.css"
MARKER = "Mobile Records country width 2026-07-30."


class MobileRecordsCountryWidthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError(
                "Mobile Records country-width marker missing."
            )
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_layer_is_unique_last_and_balanced(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        self.assertIn(
            "Balanced interface unification 2026-07-30.",
            self.css,
        )
        self.assertGreater(
            self.css.index(MARKER),
            self.css.index(
                "Balanced interface unification 2026-07-30."
            ),
        )
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)
        self.assertTrue(self.css.rstrip().endswith("}"))

    def test_fix_is_mobile_and_records_only(self) -> None:
        for expected in (
            "@media (max-width: 720px)",
            'body[data-route="records"] #record-table',
            'a.team-link[href^="#/team/"]',
        ):
            self.assertIn(expected, self.finish)
        self.assertEqual(self.finish.count("@media"), 1)
        self.assertNotIn(
            'body[data-route="rankings"]',
            self.finish,
        )
        self.assertNotIn(
            'body[data-route="tournaments"]',
            self.finish,
        )

    def test_country_cells_have_a_readable_floor(self) -> None:
        for expected in (
            'td:has(a.team-link[href^="#/team/"])',
            "min-inline-size: 13rem;",
        ):
            self.assertIn(expected, self.finish)

    def test_country_names_do_not_split(self) -> None:
        for expected in (
            "display: inline-block;",
            "max-inline-size: none;",
            "white-space: nowrap;",
            "overflow-wrap: normal;",
            "word-break: normal;",
            "hyphens: none;",
        ):
            self.assertIn(expected, self.finish)


if __name__ == "__main__":
    unittest.main()
