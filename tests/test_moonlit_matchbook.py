from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
MARKER = "Moonlit matchbook visibility correction."

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


class MoonlitMatchbookReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        if MARKER not in cls.css:
            raise AssertionError("The moonlit matchbook marker is missing.")
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

    def test_dark_tokens_are_reasserted_after_the_light_finish(self) -> None:
        dark = self.finish.split(
            "@media (prefers-color-scheme: dark)",
            1,
        )[1]
        for marker in (
            "--atelier-ink: #fff6fc;",
            "--atelier-muted: #e8cede;",
            "--atelier-paper: #140911;",
            "--atelier-surface: #27101f;",
            "--atelier-surface-soft: #3a1a30;",
            "--ink: #fff6fc;",
            "--ink-soft: #e8cede;",
            "--paper: #140911;",
            "--surface: #27101f;",
            "--surface-subtle: #3a1a30;",
            "--link: #f3a9d8;",
            "--eyebrow: #f1b0d9;",
            "html,\n  body,\n  main {",
            "color: var(--ink);",
            "background-color: var(--paper);",
        ):
            self.assertIn(marker, dark)
        self.assertNotIn("--ink: var(--atelier-ink);", dark)

    def test_dark_text_and_surfaces_exceed_wcag_aa(self) -> None:
        pairs = (
            ("#fff6fc", "#140911"),
            ("#e8cede", "#140911"),
            ("#fff6fc", "#27101f"),
            ("#e8cede", "#27101f"),
            ("#f3a9d8", "#140911"),
            ("#f1b0d9", "#140911"),
            ("#ffe8f5", "#4a203b"),
        )
        for foreground, background in pairs:
            self.assertGreaterEqual(
                contrast(foreground, background),
                4.5,
                (foreground, background),
            )

    def test_mobile_matchup_is_one_team_v_team_line(self) -> None:
        mobile = self.finish.split("@media (max-width: 520px)", 1)[1]
        mobile = mobile.split(
            "@media (prefers-color-scheme: dark)",
            1,
        )[0]
        for marker in (
            "grid-template-columns:\n"
            "      minmax(0, 1fr)\n"
            "      18px\n"
            "      minmax(0, 1fr);",
            "> a:first-of-type {\n"
            "    grid-column: 1;\n"
            "    grid-row: 1;",
            "> i {\n"
            "    grid-column: 2;\n"
            "    grid-row: 1;",
            "> a:last-of-type {\n"
            "    grid-column: 3;\n"
            "    grid-row: 1;",
            "> small {\n"
            "    grid-column: 1 / -1;\n"
            "    grid-row: 2;",
            "font-size: clamp(12px, 3.8vw, 14.5px);",
            "white-space: nowrap;",
            "word-break: keep-all;",
        ):
            self.assertIn(marker, mobile)
        self.assertIn("text-transform: uppercase;", self.finish)
        self.assertNotIn("text-wrap: balance;", mobile)
        self.assertNotIn("grid-row: 3;", mobile)
        self.assertNotIn("grid-row: 4;", mobile)

    def test_date_has_more_emphasis_than_team_names(self) -> None:
        team = re.search(
            r"\.home-records li > div > a \{(?P<body>.*?)\n\}",
            self.finish,
            re.S,
        )
        date = re.search(
            r"\.home-records li > div > small \{(?P<body>.*?)\n\}",
            self.finish,
            re.S,
        )
        self.assertIsNotNone(team)
        self.assertIsNotNone(date)
        self.assertIn("font-size: 14.5px;", team.group("body"))
        self.assertIn("font-weight: 560;", team.group("body"))
        self.assertIn("font-size: 14px;", date.group("body"))
        self.assertIn("font-weight: 750;", date.group("body"))
        self.assertIn("border-radius: 999px;", date.group("body"))
        self.assertIn("font-family: var(--font-numeric);", date.group("body"))

    def test_release_is_css_only_and_preference_safe(self) -> None:
        for marker in (
            "@media (prefers-color-scheme: dark)",
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
