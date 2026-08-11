from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Pearl vanity unification finale."

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


class PearlVanityFinaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The pearl vanity finale marker is missing.")
        cls.finish = cls.css.split(MARKER, 1)[1]

    def test_layer_is_unique_balanced_and_last(self) -> None:
        self.assertEqual(self.css.count(MARKER), 1)
        depth = 0
        for character in self.css:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)
        self.assertTrue(self.css.rstrip().endswith("}"))

    def test_eyebrow_halos_are_removed_and_type_is_clear(self) -> None:
        for marker in (
            "body .eyebrow,",
            "body .home-intro .eyebrow,",
            "body .home-support .eyebrow,",
            "font-size: 13.5px;",
            "font-weight: 620;",
            "text-shadow: none;",
            "body .home-intro .eyebrow {\n  font-size: 14px;",
        ):
            self.assertIn(marker, self.finish)

    def test_repeated_containers_share_one_material_system(self) -> None:
        for marker in (
            "--pv-surface: #fff8fc;",
            "--pv-rose: #eaa8ca;",
            "--pv-lilac: #c7b2e3;",
            "--pv-aqua: #9fd4cf;",
            "--pv-radius: 18px 24px 18px 24px;",
            ".home-ranking-list,",
            ".faq-tools,",
            ".method-contents,",
            ".ranking-card,",
            ".comparison-selection,",
            ".record-note.team-lineage-note",
            "border: 1px solid var(--pv-border);",
            "border-radius: var(--pv-radius);",
            "var(--pv-shadow);",
        ):
            self.assertIn(marker, self.finish)

    def test_buttons_are_one_family_and_records_has_no_detached_trim(
        self,
    ) -> None:
        for marker in (
            "body .button {",
            "min-height: 44px;",
            "font-family: var(--font-display);",
            "font-size: 15.5px;",
            "border-radius: 999px;",
            "body .record-tabs .button:nth-child(n) {",
            "body .record-tabs::before,",
            "body .record-tabs::after {",
            "content: none;",
        ):
            self.assertIn(marker, self.finish)
        self.assertNotIn(".button:nth-child(3n + 1)", self.finish)

    def test_three_home_actions_have_one_pearl_construction(self) -> None:
        for marker in (
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            "body[data-route=\"home\"] "
            ".home-intro .hero-actions .home-action {",
            "grid-template-columns: 16px minmax(0, 1fr);",
            "color: #fff8fc;",
            ".home-action::before {",
            "content: \"\";",
            ".home-action-rankings {",
            "--pv-action-ribbon: #f0a7ca;",
            ".home-action-fixtures {",
            "--pv-action-ribbon: #cab7e6;",
            ".home-action-predict {",
            "--pv-action-ribbon: #9fd4cf;",
            "grid-column: 1 / -1;",
        ):
            self.assertIn(marker, self.finish)

    def test_home_facts_and_explore_copy_are_desktop_readable(self) -> None:
        for marker in (
            ".home-facts dt {",
            "font-size: 14.5px;",
            ".home-facts dd {",
            "font-size: 18px;",
            ".home-explore-links a {",
            "min-height: 112px;",
            ".home-explore-links b {",
            "font-size: 18.5px;",
            ".home-explore-links span {",
            "font-size: 14.5px;",
        ):
            self.assertIn(marker, self.finish)

    def test_mobile_matchbook_is_two_compact_rows(self) -> None:
        mobile = self.finish.split("@media (max-width: 520px)", 1)[1]
        mobile = mobile.split(
            "@media (hover: none) and (pointer: coarse)",
            1,
        )[0]
        for marker in (
            "grid-template-columns:\n"
            "      22px\n"
            "      minmax(0, 1fr)\n"
            "      17px\n"
            "      minmax(0, 1fr)\n"
            "      55px;",
            "grid-template-rows: auto auto;",
            "display: contents;",
            "> a:first-of-type {\n"
            "    grid-column: 2;\n"
            "    grid-row: 1;",
            "> i {\n"
            "    grid-column: 3;\n"
            "    grid-row: 1;",
            "> a:last-of-type {\n"
            "    grid-column: 4;\n"
            "    grid-row: 1;",
            "> small {\n"
            "    grid-column: 2 / 5;\n"
            "    grid-row: 2;",
            "> strong {\n"
            "    grid-column: 5;\n"
            "    grid-row-start: 1;\n"
            "    grid-row-end: 3;",
            "font-size: clamp(12px, 3.65vw, 14.5px);",
            "white-space: nowrap;",
            "text-overflow: ellipsis;",
        ):
            self.assertIn(marker, mobile)
        self.assertNotIn("grid-row: 3;", mobile)
        self.assertNotIn("grid-row: 4;", mobile)

    def test_editorial_pages_share_geometry_and_formulae_fit_content(
        self,
    ) -> None:
        for marker in (
            "--pv-shell: 1040px;",
            "--pv-lane: 900px;",
            "--pv-reading: 780px;",
            ".faq-page,",
            ".methodology-page,",
            "body[data-route=\"about\"] .page-narrow",
            "width: min(var(--pv-shell), calc(100vw - 48px));",
            ".faq-answer,\n.faq-answer > p {",
            "max-inline-size: none;",
            ".methodology-page .formula,",
            ".methodology-page .method-details .formula {",
            "inline-size: fit-content;",
            "max-inline-size: min(var(--pv-formula), 100%);",
            "overflow-x: auto;",
            "font-size: 14.5px;",
        ):
            self.assertIn(marker, self.finish)

    def test_dark_palette_is_reasserted_and_readable(self) -> None:
        for marker in (
            "@media (prefers-color-scheme: dark)",
            "--ink: #fff6fc;",
            "--ink-soft: #e8cede;",
            "--paper: #140911;",
            "--surface: #27101f;",
            "--pv-ink: #fff6fc;",
            "--pv-muted: #e8cede;",
            "--pv-surface: #27101f;",
            "html,\n  body,\n  main {",
            "background-color: var(--paper);",
        ):
            self.assertIn(marker, self.finish)
        for foreground, background in (
            ("#fff6fc", "#140911"),
            ("#e8cede", "#140911"),
            ("#fff6fc", "#27101f"),
            ("#e8cede", "#27101f"),
            ("#f3a9d8", "#140911"),
            ("#3b1830", "#fff8fc"),
            ("#704d64", "#fff8fc"),
        ):
            self.assertGreaterEqual(
                contrast(foreground, background),
                4.5,
                (foreground, background),
            )

    def test_release_is_css_only_and_preference_safe(self) -> None:
        for marker in (
            "@media (prefers-color-scheme: dark)",
            "@media (hover: none) and (pointer: coarse)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (forced-colors: active)",
            "@media print",
        ):
            self.assertIn(marker, self.finish)
        for forbidden in (
            "url(",
            ".svg",
            ".png",
            "-webkit-mask:",
            "mask:",
            "animation:",
            "display: none",
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

    def test_logo_assets_are_byte_for_byte_locked(self) -> None:
        for filename, wanted in LOGO_HASHES.items():
            actual = hashlib.sha256(
                (PUBLIC / filename).read_bytes()
            ).hexdigest()
            self.assertEqual(actual, wanted, filename)

    def test_every_route_uses_the_correct_stylesheet_hash(self) -> None:
        wanted = hashlib.sha256(CSS_PATH.read_bytes()).hexdigest()[:12]
        routes = sorted(route for route in PUBLIC.rglob("index.html") if "clubs" not in route.relative_to(PUBLIC).parts)
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
