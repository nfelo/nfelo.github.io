"""Measured publication checks and explicit labels for inherited identity holds."""

# These two retained V7 histories contain the 259 documented mixed-identity
# matches. Keep their codes and ratings intact; do not present them as the
# source-backed V10 identities or silently merge their uncertain matches.
LEGACY_IDENTITY_HOLDS = {
    "c559fc2b19273": "Guadalajara",
    "c9f3f54174479": "Tigres UANL",
}


def public_club_name(code, name):
    expected = LEGACY_IDENTITY_HOLDS.get(code)
    if expected is None:
        return name
    label = expected + " (unresolved legacy identity)"
    if name not in (expected, label):
        raise ValueError("Legacy identity label changed unexpectedly: " + code)
    return label


def ledger_quality_checks(connection):
    """Recompute the original seven ledger guardrails on every full export."""
    checks = [
        ("distinct match identities", "SELECT count(*)-count(distinct match_id) FROM matches", 0,
         "No retained match ID may repeat."),
        ("club cannot play itself", "SELECT count(*) FROM matches WHERE home=away", 0,
         "Identity reconciliation must not collapse opponents."),
        ("retained clubs have association and confederation", """
            SELECT count(*) FROM (
                SELECT home club FROM matches UNION SELECT away FROM matches
            ) sides LEFT JOIN clubs USING(club)
            WHERE clubs.club IS NULL
               OR coalesce(country,'') IN ('','unknown')
               OR coalesce(country_name,'') IN ('','Unassigned','Unknown')
               OR coalesce(continent,'') IN ('','Unassigned','Unknown')
         """, 0, "Every retained club side has association and confederation metadata."),
        ("shootout kicks excluded from football score", """
            SELECT count(*) FROM matches
            WHERE status LIKE 'P%' AND home_goals<>away_goals
         """, 0, "A penalty decision enters the model as a draw."),
        ("Santa Clara association collision", """
            SELECT count(*) FROM matches m
            JOIN clubs h ON h.club=m.home JOIN clubs a ON a.club=m.away
            WHERE lower(m.competition) LIKE 'portugal%'
              AND ((h.name='Santa Clara' AND h.country='el-salvador')
                OR (a.name='Santa Clara' AND a.country='el-salvador'))
         """, 0, "Portugal fixtures must resolve to Portugal's Santa Clara."),
        ("ambiguous DDR competition label", """
            SELECT count(*) FROM matches WHERE lower(competition)='ddr top division'
         """, 0, "East Germany, the Soviet Union and Yugoslavia are separate competitions."),
        ("2026 Champions League final", """
            SELECT count(*) FROM matches WHERE day=DATE '2026-05-30'
              AND competition='UEFA Champions League'
              AND home_goals=1 AND away_goals=1 AND status='P' AND neutral
         """, 1, "Paris Saint-Germain 1-1 Arsenal, Paris 4-3 on penalties."),
    ]
    rows = []
    for name, query, expected, note in checks:
        actual = int(connection.execute(query).fetchone()[0])
        rows.append((name, actual, expected, actual == expected, note))
    failed = [row[0] for row in rows if not row[3]]
    if failed:
        raise ValueError("Club ledger quality checks failed: " + ", ".join(failed))
    return sorted(rows)
