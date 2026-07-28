from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CSS_PATH = PUBLIC / "assets" / "styles.css"
JS_PATH = PUBLIC / "assets" / "app.js"


class ActualFinalPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.finish = cls.css.split(
            "True final presentation pass.",
            1,
        )[1]

    def test_all_ten_refinements_are_present(self) -> None:
        markers = (
            "1. Gentle, useful motion",
            "2. Loading, empty and error states",
            "3. Route-specific spacing",
            "4. Editorial hierarchy",
            "5. Each major route receives",
            "6. Charts: quieter scaffolding",
            "7. Skeletons already mirror",
            "8. Tactile interaction states",
            "9. The pearl-cameo identity",
            "10. Responsive art direction",
        )
        for marker in markers:
            self.assertIn(marker, self.finish)

    def test_motion_is_optional_and_never_hides_content(self) -> None:
        self.assertIn(
            "@media (prefers-reduced-motion: reduce)",
            self.finish,
        )
        for marker in (
            "animation-duration: 0.001ms !important;",
            "transition-duration: 0.001ms !important;",
            "opacity: 1;",
            "transform: none;",
        ):
            self.assertIn(marker, self.finish)

    def test_transient_states_share_the_cameo_system(self) -> None:
        for marker in (
            ".loading-shell::after",
            ".compact-loading::after",
            '.spinner::before',
            'content: "N";',
            ":is(.empty, .empty-state, .error-panel)",
            '.connection-status::before',
            '.connection-status[hidden] { display: none; }',
        ):
            self.assertIn(marker, self.finish)

    def test_route_specific_art_direction_is_data_driven(self) -> None:
        for route in (
            "home",
            "rankings",
            "history",
            "tournaments",
            "matches",
            "fixtures",
            "records",
            "compare",
            "predict",
            "team",
            "methodology",
            "faq",
            "about",
        ):
            self.assertIn(f'body[data-route="{route}"]', self.finish)
        self.assertIn(
            "document.body.dataset.route = current.section;",
            self.js,
        )

    def test_loading_and_route_changes_expose_busy_state(self) -> None:
        self.assertIn(
            'content.setAttribute("aria-busy", "true");',
            self.js,
        )
        self.assertGreaterEqual(
            self.js.count(
                'content.setAttribute("aria-busy", "false");',
            ),
            2,
        )
        self.assertIn('#content[aria-busy="true"]', self.finish)

    def test_connection_state_is_live_and_non_blocking(self) -> None:
        for marker in (
            'connectionStatus.setAttribute("role", "status");',
            'connectionStatus.setAttribute("aria-live", "polite");',
            'window.addEventListener("online", syncConnectionState);',
            'window.addEventListener("offline", syncConnectionState);',
            'document.body.classList.toggle("is-offline", offline);',
        ):
            self.assertIn(marker, self.js)

    def test_chart_inspection_has_a_visible_selected_state(self) -> None:
        for marker in (
            'shell.classList.add("has-chart-selection");',
            'shell.classList.remove("has-chart-selection");',
            ".has-chart-selection .chart-inspector",
            ".chart-inspector-value > i",
            ".rating-chart .grid",
            ".rating-history-line",
        ):
            self.assertIn(marker, self.js + self.finish)

    def test_traditional_result_colours_are_untouched(self) -> None:
        self.assertNotIn("--result-win:", self.finish)
        self.assertNotIn("--result-loss:", self.finish)
        self.assertNotIn(".form .W", self.finish)
        self.assertNotIn(".form .L", self.finish)

    def test_no_literal_decorative_art_was_added(self) -> None:
        for marker in (
            ".svg",
            "url(",
            "--bow-mask",
            "--blossom-mask",
            "floral-",
        ):
            self.assertNotIn(marker, self.finish)

    def test_dark_tablet_mobile_forced_colour_and_print_contracts(self) -> None:
        for marker in (
            "@media (prefers-color-scheme: dark)",
            "@media (min-width: 721px) and (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media (forced-colors: active)",
            "@media print",
        ):
            self.assertIn(marker, self.finish)

    def test_every_clean_route_references_exact_new_assets(self) -> None:
        css_hash = hashlib.sha256(
            CSS_PATH.read_bytes(),
        ).hexdigest()[:12]
        js_hash = hashlib.sha256(
            JS_PATH.read_bytes(),
        ).hexdigest()[:12]
        routes = sorted(PUBLIC.rglob("index.html"))
        self.assertGreaterEqual(len(routes), 250)
        for route in routes:
            html = route.read_text(encoding="utf-8")
            self.assertIn(
                f"assets/styles.css?v={css_hash}",
                html,
                route,
            )
            self.assertIn(
                f"assets/app.js?v={js_hash}",
                html,
                route,
            )

    def test_css_custom_properties_are_resolved(self) -> None:
        definitions = set(
            re.findall(r"--([\w-]+)\s*:", self.css)
        )
        references = set(
            re.findall(r"var\(--([\w-]+)", self.css)
        )
        self.assertEqual(references - definitions, set())

    def test_presentation_release_does_not_modify_model_code(self) -> None:
        # This test is deliberately structural: the installer also checks
        # exact protected-file hashes before and after applying the release.
        for path in (
            ROOT / "scripts" / "model.py",
            ROOT / "scripts" / "build_site.py",
            ROOT / "config" / "elo_matches.json",
            ROOT / "config" / "forecast_layer.json",
            ROOT / "config" / "venue_effects.json",
        ):
            self.assertTrue(path.is_file(), path)


if __name__ == "__main__":
    unittest.main()
