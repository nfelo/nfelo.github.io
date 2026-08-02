from __future__ import annotations

import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
SIGNATURE = "Pastel five-band undertone 2026-08-02."
END_MARKER = "Mobile Methodology tables edge-to-edge 2026-07-30."


class PastelFiveBandUndertoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.finish = cls.css.split(SIGNATURE, 1)[1].split(END_MARKER, 1)[0]

    def test_layer_is_unique_ordered_and_balanced(self) -> None:
        self.assertEqual(self.css.count(SIGNATURE), 1)
        self.assertLess(self.css.index(SIGNATURE), self.css.index(END_MARKER))
        self.assertEqual(self.finish.count("{"), self.finish.count("}"))

    def test_exact_palette_and_reversible_five_band_order(self) -> None:
        for value in (
            "--q9-sky-blue: #5bcefa",
            "--q9-blush-pink: #f5a9b8",
            "--q9-soft-white: #ffffff",
            "var(--q9-sky-blue) 0 20%",
            "var(--q9-blush-pink) 20% 40%",
            "var(--q9-soft-white) 40% 60%",
            "var(--q9-blush-pink) 60% 80%",
            "var(--q9-sky-blue) 80% 100%",
        ):
            self.assertIn(value, self.finish)

    def test_accents_are_subtle_structural_and_distributed(self) -> None:
        for value in (
            'body[data-route="home"] .hero-actions::after',
            ".site-footer::before",
            "body .faq-item:nth-child(5n + 2)",
            'body[data-route="home"] .home-explore-links a:nth-child(5n + 4)',
            'body[data-route="rankings"] .ranking-card:nth-child(5n + 3)',
            "opacity: 0.24",
            "right: 20%",
            "left: 20%",
        ):
            self.assertIn(value, self.finish)

    def test_finish_respects_existing_asset_and_semantic_contracts(self) -> None:
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
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_every_preference_mode_has_a_deliberate_treatment(self) -> None:
        for value in (
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "@media print",
            "content: normal",
            "border-color: currentColor",
            "border-color: CanvasText",
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
