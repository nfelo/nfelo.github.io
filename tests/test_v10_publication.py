"""Regressions for the V10 installation's first Pages deployment."""
import unittest

import duckdb

from scripts.v10.publication_checks import ledger_quality_checks, public_club_name


class V10PublicationChecksTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect()
        self.addCleanup(self.db.close)
        self.db.execute("""CREATE TABLE clubs(
            club INTEGER,name VARCHAR,country VARCHAR,country_name VARCHAR,continent VARCHAR
        )""")
        self.db.execute("""INSERT INTO clubs VALUES
            (0,'PSG','france','France','Europe'),
            (1,'Arsenal FC','england','England','Europe')
        """)
        self.db.execute("""CREATE TABLE matches(
            match_id VARCHAR,day DATE,home INTEGER,away INTEGER,
            home_goals INTEGER,away_goals INTEGER,competition VARCHAR,status VARCHAR,neutral BOOLEAN
        )""")
        self.db.execute("""INSERT INTO matches VALUES
            ('reviewed-final',DATE '2026-05-30',0,1,1,1,'UEFA Champions League','P',true)
        """)

    def test_complete_report_measures_all_seven_checks(self):
        rows = ledger_quality_checks(self.db)
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row[3] for row in rows))
        final = next(row for row in rows if row[0] == '2026 Champions League final')
        self.assertEqual(final[1:3], (1, 1))

    def test_invalid_ledger_blocks_export_instead_of_reporting_success(self):
        cases = [
            ("INSERT INTO matches SELECT * FROM matches", "distinct match identities"),
            ("UPDATE matches SET away=home", "club cannot play itself"),
            ("UPDATE matches SET away=99", "association and confederation"),
            ("UPDATE clubs SET continent=NULL WHERE club=0", "association and confederation"),
            ("UPDATE matches SET home_goals=4,away_goals=3", "shootout kicks"),
            ("UPDATE matches SET competition='DDR top division'", "ambiguous DDR"),
            ("DELETE FROM matches", "2026 Champions League final"),
        ]
        for sql, message in cases:
            with self.subTest(sql=sql):
                self.db.execute('BEGIN')
                try:
                    self.db.execute(sql)
                    with self.assertRaisesRegex(ValueError, message):
                        ledger_quality_checks(self.db)
                finally:
                    self.db.execute('ROLLBACK')

    def test_known_legacy_histories_are_explicit_without_renaming_verified_clubs(self):
        self.assertEqual(
            public_club_name('c559fc2b19273', 'Guadalajara'),
            'Guadalajara (unresolved legacy identity)',
        )
        self.assertEqual(
            public_club_name('v10n_ac0ae5975e0101d2acd12d23', 'Guadalajara'),
            'Guadalajara',
        )
        self.assertEqual(
            public_club_name('c9f3f54174479', 'Tigres UANL'),
            'Tigres UANL (unresolved legacy identity)',
        )
        with self.assertRaisesRegex(ValueError, 'changed unexpectedly'):
            public_club_name('c559fc2b19273', 'Different club')
