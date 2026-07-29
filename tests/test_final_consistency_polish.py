from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Final consistency polish."
BASE_MARKER = "Pearl vanity unification finale."

LOGO_HASHES = {
    "favicon-2026.svg":
        "649147e32d2ae5e000a6cc44b2bc9d5ab1e1f2ec32b62fd3d0b04a7734fed1ff",
    "favicon.svg":
        "649147e32d2ae5e000a6cc44b2bc9d5ab1e1f2ec32b62fd3d0b04a7734fed1ff",
    "favicon-2026.ico":
        "0f0bc225dd59f4b5b840b660f20149c61c39536546452acfd807be57807e61d7",
    "favicon.ico":
        "0f0bc225dd59f4b5b840b660f20149c61c39536546452acfd807be57807e61d7",
    "apple-touch-icon-2026.png":
        "cb6431e450e087b89060fe432246563fbf75f7b0dfd77204fcda95acfa7b6d86",
    "icon-192-2026.png":
        "8cdb242ebbc757fcfe7ba37b707dda392fc55b618342ddf927c030d1dd8c2987",
    "icon-512-2026.png":
        "cc648859f5f6dbebcbb0fa862b4e510c2212137df76659cba517f182d699c38b",
    "icon-maskable-2026.svg":
        "87d39efb6f49ba8725a742b99bdbada6018e2ca7aa631597e1627667c6cd74a6",
    "social-card.svg":
        "ddd65437e8c70d129eb53ad362a50f9740af54335c05f05fdabd5d9573ca8558",
    "social-card.png":
        "0a96079b8755dae00361ce74a76a3e0fb2f0d6d346ee2bab66639ed2fd700b73",
    "site.webmanifest":
        "76f0094e761fd804591ff44320648ec8ef42a9139f193c23b3f4eb273a560364",
}


class FinalConsistencyPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The final consistency marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_layer_is_unique_last_and_structurally_balanced(self) -> None:
        self.assertIn(BASE_MARKER, self.css)
        self.assertEqual(self.css.count(MARKER), 1)
        self.assertGreater(self.css.index(MARKER), self.css.index(BASE_MARKER))
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)
        self.assertTrue(self.css.rstrip().endswith("}"))

    def test_compare_counter_uses_the_readable_compact_scale(self) -> None:
        for marker in (
            ".comparison-add-area > .button span {",
            "color: var(--pv-muted);",
            "font-size: 12.5px;",
            "font-weight: 720;",
            "line-height: 1.25;",
        ):
            self.assertIn(marker, self.finish)

    def test_technical_labels_match_the_main_metric_scale(self) -> None:
        block = self.finish.split(
            ".venue-detail-grid span {",
            1,
        )[1].split("}", 1)[0]
        for marker in (
            "color: var(--pv-muted);",
            "font-size: 12.5px;",
            "font-weight: 740;",
            "letter-spacing: 0.035em;",
            "line-height: 1.35;",
        ):
            self.assertIn(marker, block)

    def test_team_disclosures_are_accessible_pearl_controls(self) -> None:
        for marker in (
            ".venue-profile-details > summary {",
            "display: inline-flex;",
            "width: fit-content;",
            "max-width: 100%;",
            "min-height: 44px;",
            "font-family: var(--font-display);",
            "font-size: 14.5px;",
            "border-radius: 999px;",
            ".venue-profile-details > summary::after {",
            "width: 20px;",
            "height: 20px;",
            'content: "+";',
            ".venue-profile-details[open] > summary::after {",
            'content: "−";',
        ):
            self.assertIn(marker, self.finish)

    def test_all_preference_modes_keep_the_control_usable(self) -> None:
        for marker in (
            "@media (prefers-color-scheme: dark)",
            "@media (hover: none) and (pointer: coarse)",
            "min-height: 48px;",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "color: ButtonText;",
            "background: ButtonFace;",
            "@media print",
        ):
            self.assertIn(marker, self.finish)

    def test_polish_is_presentation_only_and_motion_neutral(self) -> None:
        for forbidden in (
            "url(",
            ".svg",
            ".png",
            "animation:",
            "--result-",
            ".form .W",
            ".form .D",
            ".form .L",
        ):
            self.assertNotIn(forbidden, self.finish)
        tiny = [
            float(value)
            for value in re.findall(
                r"font-size:\s*([0-9]+(?:\.[0-9]+)?)px",
                self.finish,
            )
            if float(value) < 12
        ]
        self.assertEqual(tiny, [])

    def test_logo_assets_remain_byte_for_byte_locked(self) -> None:
        for filename, wanted in LOGO_HASHES.items():
            actual = hashlib.sha256(
                (PUBLIC / filename).read_bytes()
            ).hexdigest()
            self.assertEqual(actual, wanted, filename)

    def test_every_route_uses_the_final_stylesheet_hash(self) -> None:
        wanted = hashlib.sha256(CSS_PATH.read_bytes()).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertEqual(len(routes), 260)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(
                f"assets/styles.css?v={wanted}",
                html,
                route,
            )


if __name__ == "__main__":
    unittest.main()
