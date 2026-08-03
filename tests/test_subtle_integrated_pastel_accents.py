from __future__ import annotations

import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
SIGNATURE = "Subtle integrated pastel accents 2026-08-02."
END_MARKER = "Velvet botanical ledger unified system 2026-08-03."


class SubtleIntegratedPastelAccentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.finish = cls.css.split(SIGNATURE, 1)[1].split(END_MARKER, 1)[0]

    def test_layer_replaces_the_flag_finish_and_remains_balanced(self) -> None:
        self.assertEqual(self.css.count(SIGNATURE), 1)
        self.assertLess(self.css.index(SIGNATURE), self.css.index(END_MARKER))
        self.assertEqual(self.finish.count("{"), self.finish.count("}"))
        self.assertNotIn("Pastel five-band undertone", self.css)
        self.assertNotIn("--q9-five-band", self.css)

    def test_existing_feminine_palette_remains_authoritative(self) -> None:
        for value in (
            "Romantic editorial feminine tablet v8 2026-08-02.",
            "--q8-champagne: #e7c98e",
            "--q8-sage: #b9d4c3",
            "--q8-powder-blue: #c8d9ef",
            "--q8-rose-petal: #efafd0",
            "--q8-lilac-mist: #d8c6ed",
            "--pv-rose: #eaa8ca",
            "--pv-lilac: #c7b2e3",
            "--pv-aqua: #9fd4cf",
            "--pv-champagne: #e4c8a9",
        ):
            self.assertIn(value, self.css)

    def test_exact_new_colours_are_low_share_accents(self) -> None:
        for value in (
            "--q10-sky-blue: #5bcefa",
            "--q10-blush-pink: #f5a9b8",
            "--q10-pearl-white: #ffffff",
            "var(--pv-border) 91%",
            "var(--pv-border) 90%",
            "var(--pv-border) 92%",
            "var(--q10-sky-blue) 7%",
            "var(--q10-blush-pink) 8%",
            "var(--rose-focus) 93%",
            "var(--rosewater-selection) 92%",
        ):
            self.assertIn(value, self.finish)

    def test_no_flag_surface_or_decorative_band_remains(self) -> None:
        for forbidden in (
            "five-band",
            "linear-gradient(",
            "radial-gradient(",
            "background:",
            "box-shadow:",
            'body[data-route="home"] .hero-actions::after',
            ".site-footer::before",
            "0 20%",
            "20% 40%",
            "40% 60%",
            "60% 80%",
            "80% 100%",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_accents_are_distributed_without_recolouring_components(self) -> None:
        for value in (
            "::selection",
            ".site-header",
            '.site-nav a[aria-current="page"]',
            "body .button",
            'input:not([type="checkbox"]):not([type="radio"])',
            ".hero-actions .home-action-rankings",
            ".hero-actions .home-action-fixtures",
            ".hero-actions .home-action-predict",
            'body[data-route="home"] .home-explore-links a,',
            'body[data-route="rankings"] .ranking-card',
            "body .faq-item summary::after",
            ".analysis-disclosure",
            "body .table-shell",
            "body .chart-stage",
            ".comparison-selection",
            ".record-note",
            ".site-footer a:hover",
        ):
            self.assertIn(value, self.finish)
        for forbidden in (
            "font-family:",
            "font-size:",
            "padding:",
            "margin:",
            "width:",
            "height:",
            "position:",
            "transform:",
            "opacity:",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_finish_does_not_touch_assets_motion_or_result_semantics(self) -> None:
        for forbidden in (
            "url(",
            ".svg",
            ".png",
            "-webkit-mask:",
            "mask:",
            "animation:",
            "display: none",
            "visibility: hidden",
            "z-index: -1;",
            "--result-",
            ".result-win",
            ".result-draw",
            ".result-loss",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_every_display_preference_has_a_deliberate_treatment(self) -> None:
        for value in (
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "@media print",
            "outline-color: transparent",
            "border-color: currentColor",
            "background-color: Highlight",
            "border-color: #777",
        ):
            self.assertIn(value, self.finish)

    def test_every_route_uses_the_exact_stylesheet_revision(self) -> None:
        revision = hashlib.sha256(CSS_PATH.read_bytes()).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertGreaterEqual(len(routes), 250)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(f"assets/styles.css?v={revision}", html, route)


if __name__ == "__main__":
    unittest.main()
