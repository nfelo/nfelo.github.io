from __future__ import annotations

import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
APP_PATH = PUBLIC / "assets" / "app.js"
MARKER = "Centred editorial geometry repair 2026-08-03."
METHODOLOGY_MARKER = "Mobile Methodology tables edge-to-edge 2026-07-30."
RECORDS_MARKER = "Mobile Records country width 2026-07-30."


class CentredEditorialGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.app = APP_PATH.read_text(encoding="utf-8")
        start = cls.css.index(MARKER)
        end = cls.css.index(METHODOLOGY_MARKER, start)
        cls.layer = cls.css[start:end]

    def test_release_is_unique_and_balanced(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        self.assertEqual(self.app.count(MARKER), 1)
        self.assertEqual(self.layer.count("{"), self.layer.count("}"))

    def test_release_precedes_both_protected_mobile_layers(self) -> None:
        self.assertEqual(self.css.count(METHODOLOGY_MARKER), 1)
        self.assertEqual(self.css.count(RECORDS_MARKER), 1)
        self.assertLess(self.css.index(MARKER), self.css.index(METHODOLOGY_MARKER))
        self.assertLess(
            self.css.index(METHODOLOGY_MARKER),
            self.css.index(RECORDS_MARKER),
        )
        methodology_layer = self.css[
            self.css.index(METHODOLOGY_MARKER):self.css.index(RECORDS_MARKER)
        ]
        self.assertEqual(methodology_layer.count("@media"), 1)
        records_layer = self.css.split(RECORDS_MARKER, 1)[1]
        self.assertEqual(records_layer.count("@media"), 1)

    def test_wrapped_title_ribbons_follow_visible_text_geometry(self) -> None:
        for value in (
            "const syncHeadingRibbonGeometry = () =>",
            'document.querySelectorAll(".page-heading h1")',
            "document.createRange()",
            "range.selectNodeContents(heading)",
            "range.getClientRects()",
            "const visibleLeft = Math.min(",
            "const visibleRight = Math.max(",
            'heading.style.setProperty(',
            '"--nfelo-ribbon-inline"',
            "syncHeadingRibbonGeometry();",
            "document.fonts?.ready.then(queueQ8ResponsivePresentation);",
        ):
            self.assertIn(value, self.app)
        self.assertIn(
            "left: var(--nfelo-ribbon-inline, 50%);",
            self.layer,
        )
        self.assertIn("--nfelo-ribbon-inline: 50%;", self.layer)

    def test_methodology_cards_share_the_centred_reading_axis(self) -> None:
        for selector in (
            'body[data-route="methodology"] .methodology-page .formula',
            'body[data-route="methodology"] .methodology-page .method-details',
        ):
            self.assertIn(selector, self.layer)
        for value in (
            "margin-inline: auto;",
            "width: min(var(--pv-reading), 100%);",
            "max-inline-size: var(--pv-reading);",
            "@media (max-width: 720px)",
        ):
            self.assertIn(value, self.layer)

    def test_wide_technical_tables_are_not_narrowed(self) -> None:
        self.assertNotIn(".table-shell", self.layer)
        self.assertNotIn(".parameter-table", self.layer)

    def test_every_route_references_current_asset_revisions(self) -> None:
        css_revision = hashlib.sha256(CSS_PATH.read_bytes()).hexdigest()[:12]
        app_revision = hashlib.sha256(APP_PATH.read_bytes()).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertEqual(len(routes), 260)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertEqual(
                html.count(f"assets/styles.css?v={css_revision}"),
                3,
                route,
            )
            self.assertEqual(
                html.count(f"assets/app.js?v={app_revision}"),
                1,
                route,
            )


if __name__ == "__main__":
    unittest.main()
