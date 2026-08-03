from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
CRITICAL_PATH = PUBLIC / "assets" / "critical.css"
APP_PATH = PUBLIC / "assets" / "app.js"
INDEX_PATH = PUBLIC / "index.html"
BUILDER_PATH = ROOT / "scripts" / "build_site.py"
SIGNATURE = "Velvet botanical ledger unified system 2026-08-03."
END_MARKER = "Mobile Methodology tables edge-to-edge 2026-07-30."


def gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9))


class VelvetBotanicalLedgerPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.critical = CRITICAL_PATH.read_text(encoding="utf-8")
        cls.app = APP_PATH.read_text(encoding="utf-8")
        cls.index = INDEX_PATH.read_text(encoding="utf-8")
        cls.builder = BUILDER_PATH.read_text(encoding="utf-8")
        cls.finish = cls.css.split(SIGNATURE, 1)[1].split(END_MARKER, 1)[0]

    def test_release_is_unique_ordered_and_syntactically_balanced(self) -> None:
        self.assertEqual(self.css.count(SIGNATURE), 1)
        self.assertLess(self.css.index(SIGNATURE), self.css.index(END_MARKER))
        self.assertEqual(self.css.count("{"), self.css.count("}"))
        self.assertEqual(self.finish.count("{"), self.finish.count("}"))

    def test_semantic_palette_uses_every_supporting_accent(self) -> None:
        for value in (
            "--q11-plum: #4a173e",
            "--q11-rose: var(--q8-rose-petal)",
            "--q11-lilac: var(--q8-lilac-mist)",
            "--q11-sage: var(--q8-sage)",
            "--q11-champagne: var(--q8-champagne)",
            "--q11-powder: var(--q8-powder-blue)",
            'body[data-route="history"]',
            'body[data-route="records"]',
            'body[data-route="methodology"]',
            'body[data-route="predict"]',
            'body[data-route="faq"]',
        ):
            self.assertIn(value, self.finish)

    def test_pages_share_three_coherent_editorial_families(self) -> None:
        for value in (
            'home: "cover"',
            'team: "cover"',
            'methodology: "salon"',
            'faq: "salon"',
            'about: "salon"',
            'document.body.dataset.pageFamily =',
            'class="page-heading page-heading-salon"',
            'class="page page-narrow prose about-page"',
        ):
            self.assertIn(value, self.app)
        for value in (
            'body[data-page-family="ledger"] .page',
            'body[data-page-family="salon"] .page',
            'body[data-page-family="cover"] :is(.home-intro, .team-hero)',
            "body .page-heading",
            "body .page-heading-salon",
        ):
            self.assertIn(value, self.finish)

    def test_major_interactive_surfaces_receive_real_redesigns(self) -> None:
        for value in (
            'body[data-route="predict"] .predictor',
            "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)",
            'body[data-route="predict"] .versus',
            'body[data-route="compare"] .comparison-team-list',
            "grid-template-columns: repeat(2, minmax(0, 1fr))",
            "body .table-shell thead",
            "repeating-linear-gradient(",
            "body .methodology-page .method-section > h2:first-child::before",
            "counter(q11-chapter, decimal-leading-zero)",
            "body .faq-item[open]",
            "body .record-note",
        ):
            self.assertIn(value, self.finish)

    def test_every_screen_class_and_accessibility_mode_is_deliberate(self) -> None:
        for value in (
            "@media (min-width: 901px) and (max-width: 1180px)",
            "@media (min-width: 721px) and (max-width: 900px)",
            "@media (max-width: 720px)",
            "@media (max-width: 430px)",
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-transparency: reduce)",
            "@media (prefers-contrast: more)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (forced-colors: active)",
            "@media print",
        ):
            self.assertIn(value, self.finish)

    def test_long_pages_skip_offscreen_rendering_without_hiding_content(self) -> None:
        for value in (
            "content-visibility: auto",
            "contain-intrinsic-size: auto 540px",
            "contain: layout paint",
        ):
            self.assertIn(value, self.finish)
        for forbidden in (
            "display: none",
            "visibility: hidden",
            "content-visibility: hidden",
            "animation:",
            "url(",
        ):
            self.assertNotIn(forbidden, self.finish)

    def test_browser_loads_small_route_specific_data_with_safe_fallback(self) -> None:
        for value in (
            'getJSON("data/bootstrap.json")',
            'getJSON("data/team-index.json")',
            'getJSON("data/records.json")',
            'getJSON("data/home.json")',
            'getJSON("data/summary.json")',
            "const ensureRouteData = async (section) =>",
            "const TEAM_DATA_ROUTES = new Set([",
        ):
            self.assertIn(value, self.app)
        self.assertNotIn('getJSON("data/catalog.json")', self.app)
        home = self.app.split("async function renderHome()", 1)[1].split(
            "function movementHTML", 1
        )[0]
        self.assertNotIn('getJSON("data/fixtures.json")', home)
        self.assertIn('getJSON("data/home.json")', home)

    def test_builder_emits_exact_route_fragments_and_dated_home_payload(self) -> None:
        for value in (
            'data / "bootstrap.json"',
            'data / "team-index.json"',
            'data / "records.json"',
            'data / "home.json"',
            "def homepage_fixtures(",
            'fixture.get("date_precision", "day") == "day"',
            'str(fixture["date"]),',
            "-combined,",
        ):
            self.assertIn(value, self.builder)

        data = PUBLIC / "data"
        summary = json.loads((data / "summary.json").read_text(encoding="utf-8"))
        bootstrap = json.loads((data / "bootstrap.json").read_text(encoding="utf-8"))
        teams = json.loads((data / "team-index.json").read_text(encoding="utf-8"))
        records = json.loads((data / "records.json").read_text(encoding="utf-8"))
        home = json.loads((data / "home.json").read_text(encoding="utf-8"))["fixtures"]
        self.assertEqual(bootstrap["current"], summary["current"][:10])
        self.assertEqual(teams["current"], summary["current"])
        self.assertEqual(teams["teams"], summary["teams"])
        self.assertEqual(records["peaks"], summary["peaks"])
        self.assertLessEqual(len(home), 5)
        self.assertTrue(all(row.get("date_precision", "day") == "day" for row in home))
        self.assertEqual(
            [(row["date"], -float(row["combined_rating"])) for row in home],
            sorted((row["date"], -float(row["combined_rating"])) for row in home),
        )

    def test_critical_shell_and_async_full_style_are_fail_safe(self) -> None:
        for value in (
            'rel="stylesheet" href="assets/critical.css?v=',
            'rel="preload" href="assets/styles.css?v=',
            'id="nfelo-full-style"',
            'media="print"',
            "this.media='all';window.__nfeloStyleResolve?.()",
            'fetchpriority="high"',
            'fetchpriority="low"',
        ):
            self.assertIn(value, self.index)
        self.assertIn("window.__nfeloStyleReady || Promise.resolve()", self.app)
        self.assertIn("font-display: optional", self.css)
        for value in (".site-header", ".loading-shell", ".site-footer"):
            self.assertIn(value, self.critical)

    def test_compressed_first_view_stays_within_slow_connection_budget(self) -> None:
        data = PUBLIC / "data"
        budgets = {
            CRITICAL_PATH: 4_000,
            CSS_PATH: 90_000,
            APP_PATH: 75_000,
            data / "bootstrap.json": 12_000,
            data / "home.json": 3_000,
            data / "team-index.json": 120_000,
            data / "records.json": 150_000,
        }
        for path, maximum in budgets.items():
            self.assertLessEqual(gzip_size(path), maximum, path)
        first_home_view = sum(
            gzip_size(path)
            for path in (
                CRITICAL_PATH,
                CSS_PATH,
                APP_PATH,
                data / "bootstrap.json",
                data / "home.json",
            )
        )
        self.assertLessEqual(first_home_view, 165_000)

    def test_every_generated_route_uses_all_exact_asset_revisions(self) -> None:
        revisions = {
            asset: hashlib.sha256((PUBLIC / asset).read_bytes()).hexdigest()[:12]
            for asset in (
                "assets/critical.css",
                "assets/styles.css",
                "assets/app.js",
            )
        }
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertGreaterEqual(len(routes), 250)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            for asset, revision in revisions.items():
                self.assertIn(f"{asset}?v={revision}", html, route)
            self.assertEqual(len(re.findall(r"assets/critical\.css\?v=", html)), 1)

    def test_model_inputs_and_live_accuracy_contract_remain_untouched(self) -> None:
        self.assertEqual(self.app.count("number(replay.log_loss, 6)"), 1)
        self.assertIn('{ cache: "no-cache" }', self.app)
        self.assertIsNone(re.search(r"\b0\.878(?:33346|31572)\b", self.app))
        for forbidden in (
            "from model import",
            "CALIBRATION_PARAMETERS",
            "source/elo_pages",
            "config/model",
        ):
            self.assertNotIn(forbidden, self.finish)


if __name__ == "__main__":
    unittest.main()
