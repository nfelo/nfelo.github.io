from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "public" / "assets" / "styles.css"
APP_PATH = ROOT / "public" / "assets" / "app.js"
MARKER = "Transient geometry and honest overflow repair 2026-08-03."
NEXT_MARKER = "Mobile Methodology tables edge-to-edge 2026-07-30."


class TransientGeometryHonestOverflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.app = APP_PATH.read_text(encoding="utf-8")
        start = cls.css.index(MARKER)
        end = cls.css.index(NEXT_MARKER, start)
        cls.layer = cls.css[start:end]

    def test_release_is_unique_ordered_and_balanced(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        self.assertEqual(self.app.count(MARKER), 1)
        self.assertLess(self.css.index(MARKER), self.css.index(NEXT_MARKER))
        self.assertEqual(self.layer.count("{"), self.layer.count("}"))

    def test_route_presentation_commits_only_after_render(self) -> None:
        route = self.app.split("async function route({", 1)[1].split(
            'nav?.querySelectorAll(".nav-group")',
            1,
        )[0]
        before_render = route.split("switch (current.section)", 1)[0]
        after_render = route.split("switch (current.section)", 1)[1]
        self.assertNotIn("document.body.dataset.route", before_render)
        self.assertNotIn("document.body.dataset.pageFamily", before_render)
        self.assertNotIn("setActiveNav(current.section)", before_render)
        self.assertIn("document.body.dataset.pageFamily", after_render)
        self.assertIn("setRouteMetadata(current)", after_render)
        self.assertIn("setActiveNav(current.section)", after_render)

    def test_formula_guidance_requires_measured_overflow(self) -> None:
        for value in (
            "const syncScrollableFormulaRegions = () =>",
            'formula.removeAttribute("data-nfelo-formula-overflow")',
            "formula.scrollWidth > formula.clientWidth + 2",
            'formula.dataset.nfeloFormulaOverflow = "true"',
            'formula.setAttribute("tabindex", "0")',
            "syncScrollableFormulaRegions();",
            'content.addEventListener?.("toggle",',
            "new ResizeObserver(queueQ8ResponsivePresentation)",
        ):
            self.assertIn(value, self.app)
        self.assertIn(
            '.formula[data-nfelo-formula-overflow="true"]::before',
            self.layer,
        )
        self.assertIn('content: "Swipe to see the full formula →";', self.layer)

    def test_table_guidance_is_bound_to_its_scroll_shell(self) -> None:
        for value in (
            'shell.previousElementSibling?.matches(".table-hint")',
            "hint.hidden = !active",
            'hint.toggleAttribute("data-nfelo-scroll-hint", active)',
        ):
            self.assertIn(value, self.app)
        for value in (
            "body .table-hint[hidden]",
            "body .table-hint[data-nfelo-scroll-hint]",
        ):
            self.assertIn(value, self.layer)

    def test_title_ribbons_and_methodology_reading_lane_are_centred(self) -> None:
        for value in (
            "body .page-heading h1::after",
            "left: 50%;",
            "transform: translateX(-50%);",
            "width: fit-content;",
            "@media (min-width: 901px)",
            'body[data-route="methodology"] .methodology-page',
            "width: min(var(--pv-reading), 100%);",
            "margin-inline: auto;",
        ):
            self.assertIn(value, self.layer)

    def test_accessibility_modes_keep_the_repairs_deliberate(self) -> None:
        for value in (
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "@media print",
            "outline-color: Highlight;",
        ):
            self.assertIn(value, self.layer)


if __name__ == "__main__":
    unittest.main()
