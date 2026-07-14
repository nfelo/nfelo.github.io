#!/usr/bin/env python3
"""Parse the headerless World Football Elo Ratings TSV ledger deterministically."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def read_successors(path: Path) -> dict[str, str]:
    successors: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0] and fields[1]:
            successors[fields[0]] = fields[1]
    return successors


def canonical(code: str, successors: dict[str, str]) -> str:
    seen: set[str] = set()
    while code in successors and code not in seen:
        seen.add(code)
        code = successors[code]
    return code


def read_dictionary(path: Path, *, skip_locations: bool = False) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) < 2 or not fields[0]:
            continue
        if skip_locations and fields[0].endswith("_loc"):
            continue
        values[fields[0]] = fields[1]
    return values


@dataclass(frozen=True, slots=True)
class Match:
    day: int
    year: int
    month: int
    day_of_month: int
    date_text: str
    team1_code: str
    team2_code: str
    team1: str
    team2: str
    score1: int
    score2: int
    tournament: str
    venue: str
    home_sign: int
    official_change: int
    official_post1: int
    official_post2: int

    @property
    def official_pre1(self) -> int:
        return self.official_post1 - self.official_change

    @property
    def official_pre2(self) -> int:
        return self.official_post2 + self.official_change

    @property
    def result(self) -> float:
        if self.score1 > self.score2:
            return 1.0
        if self.score1 < self.score2:
            return 0.0
        return 0.5

    @property
    def margin(self) -> int:
        return abs(self.score1 - self.score2)


def read_matches(pages: Path, successors: dict[str, str]) -> list[Match]:
    """Read, deduplicate and same-day order all team-page rows.

    The first nine fields form the source's stable match identity. Same-day
    double fixtures are ordered by reconstructing the published pre/post state.
    Unknown historical month/day values are deliberately preserved as zero.
    """

    unique: dict[tuple[str, ...], list[str]] = {}
    page_count = 0
    for path in sorted(pages.glob("*.tsv")):
        page_count += 1
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            fields = line.split("\t")
            if len(fields) != 16:
                raise ValueError(
                    f"Expected 16 TSV fields in {path}:{line_number}; got {len(fields)}"
                )
            unique.setdefault(tuple(fields[:9]), fields)
    if page_count == 0:
        raise ValueError(f"No team TSV pages found in {pages}")

    matches: list[Match] = []
    for fields in unique.values():
        year, month, day_of_month = map(int, fields[:3])
        team1_code, team2_code = fields[3], fields[4]
        team1 = canonical(team1_code, successors)
        team2 = canonical(team2_code, successors)
        venue = fields[8]
        # The source's blank venue convention means team 1 is at home.
        venue_team = canonical(venue, successors) if venue else team1
        home_sign = 1 if venue_team == team1 else -1 if venue_team == team2 else 0
        matches.append(
            Match(
                day=year * 400 + month * 32 + day_of_month,
                year=year,
                month=month,
                day_of_month=day_of_month,
                date_text=f"{year:04d}-{month:02d}-{day_of_month:02d}",
                team1_code=team1_code,
                team2_code=team2_code,
                team1=team1,
                team2=team2,
                score1=int(fields[5]),
                score2=int(fields[6]),
                tournament=fields[7],
                venue=venue,
                home_sign=home_sign,
                official_change=int(fields[9]),
                official_post1=int(fields[10]),
                official_post2=int(fields[11]),
            )
        )

    matches.sort(key=lambda m: (m.day, m.team1_code, m.team2_code))
    ordered: list[Match] = []
    official_state: dict[str, int] = {}
    start = 0
    while start < len(matches):
        end = start + 1
        while end < len(matches) and matches[end].day == matches[start].day:
            end += 1
        remaining = matches[start:end]
        while remaining:
            def disagreement(match: Match) -> tuple[int, int, str, str]:
                error = 0
                known = 0
                for team, pre in (
                    (match.team1, match.official_pre1),
                    (match.team2, match.official_pre2),
                ):
                    if team in official_state:
                        known += 1
                        error += abs(official_state[team] - pre)
                return error, -known, match.team1_code, match.team2_code

            chosen = min(remaining, key=disagreement)
            ordered.append(chosen)
            official_state[chosen.team1] = chosen.official_post1
            official_state[chosen.team2] = chosen.official_post2
            remaining.remove(chosen)
        start = end
    return ordered


def source_digest_rows(matches: list[Match]) -> list[tuple[object, ...]]:
    """Return the canonical match identity used by update integrity tests."""

    return [
        (
            match.date_text,
            match.team1_code,
            match.team2_code,
            match.score1,
            match.score2,
            match.tournament,
            match.venue,
        )
        for match in matches
    ]
