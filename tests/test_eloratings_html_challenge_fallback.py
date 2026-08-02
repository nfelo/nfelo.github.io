from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_sources import (  # noqa: E402
    PublicTsvClient,
    UpstreamHtmlChallengeError,
    fetch_world_table,
    is_html_challenge,
    validate_world,
)
from open_results import retain_stored_upcoming_fixtures  # noqa: E402


def world_row(code: str = "AA") -> str:
    return "\t".join(["1", "1", code, "100"] + ["value"] * 27)


def challenge_page() -> str:
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        "<script>window.location.reload();</script>",
        "<title>One moment, please...</title>",
        "</head>",
        "<body>",
        *["<span>Checking your browser</span>"] * 140,
        "</body>",
        "</html>",
    ]
    assert len(lines) == 149
    return "\n".join(lines)


class _Response:
    status_code = 200

    def __init__(self, text: str) -> None:
        self.text = text


class _Session:
    def __init__(self, text: str) -> None:
        self.text = text
        self.urls: list[str] = []

    def get(self, url: str, **_: object) -> _Response:
        self.urls.append(url)
        return _Response(self.text)


class EloratingsHtmlChallengeFallbackTests(unittest.TestCase):
    def test_149_line_html_response_is_not_mistaken_for_tsv(self) -> None:
        html = challenge_page()
        self.assertEqual(len(html.splitlines()), 149)
        self.assertTrue(is_html_challenge(html))
        with self.assertRaises(UpstreamHtmlChallengeError):
            validate_world(html)

    def test_challenge_reuses_and_revalidates_stored_snapshot(self) -> None:
        with TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            stored_world = "\n".join([world_row()] * 244)
            (source / "World.tsv").write_text(stored_world, encoding="utf-8")
            (source / "teams.tsv").write_text("AA\tAA\n", encoding="utf-8")

            session = _Session(challenge_page())
            client = PublicTsvClient(0, stored_source=source)
            client.session = session
            with patch("fetch_sources.time.sleep"):
                text = client.get("https://www.eloratings.net/World.tsv")

            self.assertEqual(text, stored_world)
            self.assertEqual(len(validate_world(text)), 244)
            self.assertTrue(client.challenge_fallback_active)
            self.assertEqual(len(session.urls), 4)
            self.assertEqual(client.stored_fallback_files, 1)

            teams = client.get("https://www.eloratings.net/teams.tsv")
            self.assertEqual(teams, "AA\tAA\n")
            self.assertEqual(len(session.urls), 4)
            self.assertEqual(client.stored_fallback_files, 2)

    def test_challenge_without_a_snapshot_still_fails_closed(self) -> None:
        with TemporaryDirectory() as temp_name:
            client = PublicTsvClient(0, stored_source=Path(temp_name))
            client.session = _Session(challenge_page())
            with patch("fetch_sources.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "stored fallback is unavailable"):
                    client.get("https://www.eloratings.net/World.tsv")

    def test_short_but_well_formed_tsv_is_still_rejected(self) -> None:
        short = "\n".join([world_row()] * 149)

        class Client:
            def get(self, _: str) -> str:
                return short

        with patch("fetch_sources.time.sleep"):
            with self.assertRaisesRegex(ValueError, "only 149 rows"):
                fetch_world_table(Client(), "https://example.test/World.tsv")

    def test_challenged_fixture_feed_retains_validated_stored_rows(self) -> None:
        stored = {
            "date": "2026-08-09",
            "date_precision": "day",
            "team1_code": "AA",
            "team2_code": "BB",
            "team1_name": "Alpha",
            "team2_name": "Beta",
            "tournament_code": "F",
            "tournament_name": "Friendly",
            "city": "",
            "country": "",
            "neutral": True,
            "home_sign": 0,
        }
        with TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "upcoming_fixtures.json"
            path.write_text(
                json.dumps({"fixtures": [stored]}),
                encoding="utf-8",
            )
            fixture_map: dict = {}
            tournament_names: dict[str, str] = {}
            retained = retain_stored_upcoming_fixtures(
                path,
                fixture_map,
                {},
                tournament_names,
                {"AA": "Alpha", "BB": "Beta"},
                date(2026, 8, 2),
                date(2027, 8, 7),
            )

        self.assertEqual(retained, 1)
        self.assertEqual(len(fixture_map), 1)
        self.assertEqual(tournament_names, {"F": "Friendly"})

    def test_status_contract_records_fallback_provenance(self) -> None:
        script = (ROOT / "scripts" / "fetch_sources.py").read_text(encoding="utf-8")
        for value in (
            '"first_party_source"',
            '"first_party_challenge_url"',
            '"stored_fallback_files"',
            "stored first-party snapshot revalidated",
            '"wfe_fixture_source"',
            '"retained_stored_fixture_rows"',
        ):
            target = (
                script
                if "wfe_" not in value and "retained_" not in value
                else (ROOT / "scripts" / "open_results.py").read_text(encoding="utf-8")
            )
            self.assertIn(value, target)


if __name__ == "__main__":
    unittest.main()
