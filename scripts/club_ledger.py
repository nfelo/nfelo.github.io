#!/usr/bin/env python3
"""Canonical global senior men's club-match ledger.

The ledger is intentionally separate from the national-team source and model.
It combines a broad historical backbone with selected deep-tier/cup sources,
then resolves identities, removes overlap, and annotates explicit two-leg ties
before a rating is ever updated.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any, Iterable, Iterator

import duckdb


INVALID_TEAM = re.compile(r"^\s*(?:\([^)]*\))?\s*$")
CORPORATE_WORDS = {
    "1",
    "1900",
    "1903",
    "1904",
    "1905",
    "1907",
    "1909",
    "1913",
    "1846",
    "1879",
    "ac",
    "ad",
    "afc",
    "ao",
    "as",
    "associacao",
    "asociacion",
    "athletic",
    "atletica",
    "atletico",
    "bk",
    "boldklub",
    "ca",
    "cd",
    "cf",
    "clube",
    "club",
    "de",
    "do",
    "ec",
    "fc",
    "ff",
    "fk",
    "football",
    "forening",
    "fotball",
    "futbol",
    "futebol",
    "if",
    "idrottsforening",
    "klub",
    "klubb",
    "nk",
    "pfk",
    "rc",
    "rcd",
    "saf",
    "sc",
    "sfc",
    "sk",
    "sociedade",
    "sport",
    "sporting",
    "sv",
    "the",
    "uc",
    "us",
}
COUNTRY_ALIASES = {
    "brasil": "brazil",
    "czech republic": "czech-republic",
    "czechia": "czech-republic",
    "eng": "england",
    "ger": "germany",
    "deutschland": "germany",
    "korea south": "korea-republic",
    "south korea": "korea-republic",
    "por": "portugal",
    "sco": "scotland",
    "turkiye": "turkey",
    "türkiye": "turkey",
    "united states": "united-states",
    "usa": "united-states",
}
COUNTRY_CODE_ALIASES = {
    "ALB": "albania", "AUT": "austria", "BEL": "belgium",
    "BGR": "bulgaria", "BLR": "belarus", "BIH": "bosnia-herzegovina",
    "CRO": "croatia", "CYP": "cyprus", "CZE": "czech-republic",
    "DEN": "denmark", "ENG": "england", "ESP": "spain",
    "EST": "estonia", "FIN": "finland", "FRA": "france",
    "GEO": "georgia", "GER": "germany", "GRE": "greece",
    "HUN": "hungary", "IRL": "ireland", "ISL": "iceland",
    "ISR": "israel", "ITA": "italy", "KAZ": "kazakhstan",
    "LUX": "luxembourg", "LVA": "latvia", "MDA": "moldova",
    "MKD": "north-macedonia", "MLT": "malta", "MNE": "montenegro",
    "NED": "netherlands", "NIR": "northern-ireland", "NOR": "norway",
    "POL": "poland", "POR": "portugal", "ROU": "romania",
    "RUS": "russia", "SCO": "scotland", "SRB": "serbia",
    "SUI": "switzerland", "SVK": "slovakia", "SVN": "slovenia",
    "SWE": "sweden", "TUR": "turkey", "UKR": "ukraine",
    "WAL": "wales", "YUG": "serbia",
}
CONTINENT_BY_CONFEDERATION = {
    "afrika": "Africa",
    "africa": "Africa",
    "amerika": "Americas",
    "asia": "Asia",
    "asien": "Asia",
    "europa": "Europe",
    "europe": "Europe",
    "fifa": "World",
    "oceania": "Oceania",
}
SOUTH_AMERICAN_ASSOCIATIONS = {
    "argentina", "bolivia", "brazil", "chile", "colombia", "ecuador",
    "paraguay", "peru", "uruguay", "venezuela",
}
FOOTBALL_CONFEDERATION_OVERRIDES = {
    # Football affiliation is not geographic location.  These overrides are
    # intentionally evaluated after country normalisation.
    "australia": "Asia",
    "guam": "Asia",
    "northern-mariana-islands": "Asia",
    "israel": "Europe",
    "kazakhstan": "Europe",
    "armenia": "Europe",
    "azerbaijan": "Europe",
    "cyprus": "Europe",
    "georgia": "Europe",
    "russia": "Europe",
    "turkey": "Europe",
    "guyana": "North America",
    "surinam": "North America",
    "suriname": "North America",
    "french-guiana": "North America",
}
TRANSFERMARKT_FALLBACK_COMPETITIONS = {
    "CGB": ("EFL Cup", "domestic_cup", "England"),
    "COL1": ("Categoría Primera A", "league", "Colombia"),
    "KLUB": ("FIFA Club World Cup", "global", ""),
    "POCP": ("Taça de Portugal", "domestic_cup", "Portugal"),
    "UKRS": ("Ukrainian Super Cup", "super_cup", "Ukraine"),
}
CROSS_BORDER_JURISDICTIONS = {
    "australia": {"new-zealand"},
    "england": {"wales"},
    "france": {"monaco"},
    "ireland": {"northern-ireland"},
    "scotland": {"england"},
    "switzerland": {"liechtenstein"},
    "united-states": {"canada"},
}
KNOWN_CLUB_ALIAS_PAIRS = {
    ("aalborgbk", "aab"),
    ("aarhusgf", "agf"),
    ("apollonlimassol", "apollon"),
    ("apoelnikosia", "apoel"),
    ("astana64", "fczhenisastana"),
    ("bateborisov", "bate"),
    ("cuiaba", "cuiabaesporteclube"),
    ("fcjazz", "fcjazzpori"),
    ("fkleotar", "leotartrebinje"),
    ("floratallinn", "flora"),
    ("gremio", "gremioportoalegre"),
    ("internazionale", "inter"),
    ("iaakranes", "ia"),
    ("kispestihonved", "budapesthonved"),
    ("krcgenk", "genk"),
    ("krreykjavik", "kr"),
    ("kuopionps", "kups"),
    ("milsamiorhei", "milsami"),
    ("mypa", "mypakouvola"),
    ("ogcnice", "nice"),
    ("olimpijajubljana", "olimpija"),
    ("olympiacos", "olympiakospiraeus"),
    ("parissaintgermain", "psg"),
    ("redbullbragantino", "bragantino"),
    ("servettegeneve", "servette"),
    ("sherifftiraspol", "sheriff"),
    ("slbenfica", "benfica"),
    ("sscnapoli", "napoli"),
    ("stadereims", "reims"),
    ("ujpestidozsasc", "ujpest"),
    ("zimbruchisinau", "zimbru"),
}
# A deliberately tiny set of identities that are split inside the historical
# backbone itself.  These cannot be discovered from overlapping fixtures
# because one label was used for lower divisions/cups and the other for the top
# flight.  Keep this explicit rather than merging all corporate-word variants:
# e.g. AFC Wimbledon and Wimbledon are different clubs.
BACKBONE_IDENTITY_ALIASES = {
    "Sunderland Afc (England)": "Sunderland (England)",
}
# Reviewed cross-source labels whose short and long forms are too dissimilar
# for the general matcher.  Country is part of every key: this is particularly
# important for names such as Sport, Nacional, and Arsenal.
EXPLICIT_SOURCE_ALIASES = {
    ("albania", "dinamotirana"): "dinamocity",
    ("austria", "rapidwien"): "rapid",
    ("bosnia-herzegovina", "zeljeznicarsarajevo"): "zeljeznicar",
    ("brazil", "athleticoparanaense"): "atleticoparanaense",
    ("brazil", "athleticopr"): "atleticoparanaense",
    ("brazil", "atleticogo"): "atleticogoianiense",
    ("brazil", "atleticomg"): "atleticomineiro",
    ("brazil", "brasildepelotas"): "gremioesportivobrasil",
    ("brazil", "coritibafootballclub"): "coritibafc",
    ("brazil", "csa"): "csalagoano",
    ("brazil", "muricial"): "murici",
    ("brazil", "sport"): "sportclubrecife",
    ("brazil", "vasco"): "vascodagama",
    ("brazil", "villanovamg"): "villanovaatleticoclube",
    ("cyprus", "anorthosisfamagusta"): "anorthosis",
    ("finland", "hakavalkeakoski"): "haka",
    ("finland", "hjkhelsinki"): "hjk",
    ("france", "lilleosc"): "lille",
    ("germany", "1fsvmainz05"): "mainz05",
    ("germany", "scwismutkarlmarxstadt"): "erzgebirgeaue",
    ("hungary", "debrecenivsc"): "debrecen",
    ("netherlands", "psveindhoven"): "psv",
    ("norway", "aalesundsfotballklubb"): "aalesundsfk",
    ("norway", "idrettsklubbenstart"): "ikstart",
    ("russia", "zenitstpetersburg"): "zenit",
    ("serbia", "partizanbelgrade"): "partizan",
    ("slovakia", "mskzilina"): "zilina",
    ("spain", "athleticbilbao"): "athleticclub",
    ("saudi-arabia", "alhazemsportclub"): "alhazm",
    ("sweden", "aiksolna"): "aik",
    ("sweden", "vasterassportklubbfk"): "vaesterassk",
    ("switzerland", "grasshopperszurich"): "grasshoppers",
    ("wales", "barrytown"): "barrytownunited",
}
# Brazilian source labels can be short enough to collide across states.  These
# reviewed mappings therefore include the federation code rather than relying
# on a country-wide "Guarani", "Atlético", or "Brasil" rule.
BRAZIL_STATE_SOURCE_ALIASES = {
    ("AL", "cruzeiroarapiraca"): "cruzeiro",
    ("AL", "crb"): "clubederegatasbrasil",
    ("AL", "jacyoba"): "jacioba",
    ("BA", "atleticodealagoinhas"): "atletico",
    ("CE", "atleticoce"): "atletico",
    ("CE", "guaranidejuazeiro"): "guarani",
    ("CE", "icasace"): "icasa",
    ("GO", "atletico"): "atleticogoianiense",
    ("MG", "americamg"): "americamg",
    ("MG", "boaesporte"): "boa",
    ("MG", "democratagv"): "ecdemocrata",
    ("MA", "sejuventude"): "juventude",
    ("PA", "paysandu"): "paysandusc",
    ("PA", "saoraimundopa"): "saoraimundo",
    ("PA", "saofrancisco"): "sfrancisco",
    ("PB", "botafogopb"): "botafogopb",
    ("PR", "riobrancopr"): "riobranco",
    ("PR", "londrina"): "londrinaesporteclube",
    ("RJ", "americarj"): "americarj",
    ("RJ", "audaxrj"): "audaxrio",
    ("RJ", "goytacaz"): "goytacazfc",
    ("RJ", "portuguesarj"): "portuguesa",
    ("RJ", "voltaredonda"): "voltaredondafutebolclube",
    ("RS", "brasil"): "gremioesportivobrasil",
    ("RS", "guaranydebage"): "guarany",
    ("RS", "santacruzrs"): "santacruz",
    ("SE", "confianca"): "associacaodesportivaconfianca",
    ("SC", "ecprospera"): "prospera",
    ("SC", "gremiojuventus"): "juventus",
    ("SP", "botafogo"): "botafogosp",
    ("SP", "botafogosp"): "botafogosp",
    ("SP", "ferroviaria"): "ferroviariafutebolsa",
    ("SP", "guarani"): "guaranifc",
    ("SP", "interdelimeira"): "associacaoatleticainternacionallemeira",
    ("SP", "internacionaldelimeira"): "associacaoatleticainternacionallemeira",
    ("PE", "academicavitoria"): "vitoria",
    ("PE", "afogadosdaingazeira"): "afogados",
    ("PE", "americape"): "america",
    ("PE", "flamengoarcoverde"): "flamengo",
    ("MT", "operariovg"): "operario",
}
INTERNATIONAL_NAMES = {
    "AFC CL": "AFC Champions League",
    "AFC Pokal": "AFC Cup",
    "AFC Pres Cup": "AFC President's Cup",
    "CAF CC": "CAF Confederation Cup",
    "CAF CL": "CAF Champions League",
    "CAF SC": "CAF Super Cup",
    "CFU CC": "Caribbean Club Championship",
    "CONCACAF CC": "CONCACAF Champions Cup",
    "CONCACAF L": "CONCACAF League",
    "Copa Lib": "Copa Libertadores",
    "Copa Sud": "Copa Sudamericana",
    "Fifa Club": "FIFA Club World Cup",
    "OFC CC": "OFC Champions League",
    "Recopa": "Recopa Sudamericana",
    "UEFA CL": "UEFA Champions League",
    "UEFA CONF L": "UEFA Conference League",
    "UEFA EL": "UEFA Europa League",
    "UEFA ITC": "UEFA Intertoto Cup",
    "UEFA SC": "UEFA Super Cup",
}


def clean_country(value: str | None) -> str:
    text = " ".join(str(value or "").strip().split()).casefold()
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = text.replace(",", " ")
    text = " ".join(text.split())
    if text.upper() in COUNTRY_CODE_ALIASES:
        return COUNTRY_CODE_ALIASES[text.upper()]
    return COUNTRY_ALIASES.get(text, text.replace(" ", "-"))


def display_country(value: str) -> str:
    # These are the public labels used by the national NFELO application.
    # Club imports may use historical, ISO or source-specific aliases, but the
    # generated UI must never expose a second naming convention.
    replacements = {
        "bosnia-herzegovina": "Bosnia and Herzegovina",
        "brunei-darussalam": "Brunei",
        "cape-verde": "Cabo Verde",
        "czech-republic": "Czechia",
        "democratic-republic-of-congo": "DR Congo",
        "congo-democratic-republic": "DR Congo",
        "east-timor": "Timor-Leste",
        "england": "England",
        "eswatini": "Eswatini",
        "hong-kong-china": "Hong Kong",
        "iran-islamic-republic": "Iran",
        "ivory-coast": "Ivory Coast",
        "korea-republic": "South Korea",
        "korea-dpr": "North Korea",
        "macao": "Macau",
        "moldova-republic": "Moldova",
        "palestinian-territories": "Palestine",
        "russia": "Russia",
        "syrian-arab-republic": "Syria",
        "taiwan": "Chinese Taipei",
        "tanzania-united-republic": "Tanzania",
        "turkey": "Türkiye",
        "united-states": "United States",
        "united-states-of-america": "United States",
        "northern-ireland": "Northern Ireland",
        "north-macedonia": "North Macedonia",
        "viet-nam": "Vietnam",
    }
    return replacements.get(value, value.replace("-", " ").title())


def football_confederation(country: str, geography: str | None = None) -> str:
    """Resolve current men's football affiliation separately from geography."""
    country = clean_country(country)
    override = FOOTBALL_CONFEDERATION_OVERRIDES.get(country)
    if override:
        return override
    geographic = " ".join(str(geography or "").split()).title()
    if geographic in {"North America", "South America", "Africa", "Asia", "Europe", "Oceania"}:
        return geographic
    if geographic in {"America", "Americas"}:
        return (
            "South America"
            if country in SOUTH_AMERICAN_ASSOCIATIONS
            else "North America"
        )
    return geographic


def normalise_name(value: str) -> str:
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(character)
    ).casefold()
    text = re.sub(r"\([^)]*(?:19|20)\d{2}[^)]*\)", " ", text)
    text = text.replace("&", " and ").replace("ß", "ss")
    return "".join(re.findall(r"[a-z0-9]+", text))


def search_name(value: str) -> str:
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(character)
    ).casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    kept = [token for token in tokens if token not in CORPORATE_WORDS]
    return "".join(kept) or "".join(tokens)


def name_acronym(value: str) -> str:
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(character)
    ).casefold()
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", text)
        if token not in CORPORATE_WORDS
    ]
    if len(tokens) == 1 and len(tokens[0]) <= 5:
        return tokens[0]
    return "".join(token[0] for token in tokens if token)


def safe_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip('"')
    if not text or text.casefold() in {"na", "nan", "none"}:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def integer(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or str(value).strip().casefold() in {"", "na", "nan"}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def stable_code(identity: str) -> str:
    return "c" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


@dataclass
class Club:
    index: int
    code: str
    name: str
    country: str
    country_code: str
    continent: str
    identity: str
    resolution: str


class ClubRegistry:
    def __init__(self) -> None:
        self.clubs: list[Club] = []
        self.identity_to_index: dict[str, int] = {}
        self.full_keys: dict[tuple[str, str], set[int]] = defaultdict(set)
        self.search_keys: dict[tuple[str, str], set[int]] = defaultdict(set)
        self.global_full: dict[str, set[int]] = defaultdict(set)
        self.global_search: dict[str, set[int]] = defaultdict(set)
        self.country_metadata: dict[str, tuple[str, str]] = {}
        self.resolved_aliases: dict[tuple[str, str], int] = {}

    def _index_names(self, club: Club) -> None:
        full = normalise_name(club.name)
        search = search_name(club.name)
        self.full_keys[(club.country, full)].add(club.index)
        self.search_keys[(club.country, search)].add(club.index)
        self.global_full[full].add(club.index)
        self.global_search[search].add(club.index)

    def add(
        self,
        identity: str,
        name: str,
        country: str,
        country_code: str = "",
        continent: str = "",
        resolution: str = "source identity",
    ) -> int:
        if identity in self.identity_to_index:
            return self.identity_to_index[identity]
        country = clean_country(country)
        if country and (country_code or continent):
            previous = self.country_metadata.get(country, ("", ""))
            self.country_metadata[country] = (
                country_code or previous[0], continent or previous[1]
            )
        if country:
            metadata = self.country_metadata.get(country, ("", ""))
            country_code = country_code or metadata[0]
            continent = continent or metadata[1]
        index = len(self.clubs)
        club = Club(
            index=index,
            code=stable_code(identity),
            name=" ".join(name.split()).strip(),
            country=country,
            country_code=country_code,
            continent=continent,
            identity=identity,
            resolution=resolution,
        )
        self.clubs.append(club)
        self.identity_to_index[identity] = index
        self._index_names(club)
        return index

    @staticmethod
    def _unique(values: set[int] | None) -> int | None:
        return next(iter(values)) if values and len(values) == 1 else None

    def resolve(
        self,
        name: str,
        country: str = "",
        *,
        create_identity: str | None = None,
        resolution: str = "deterministic alias",
        allow_fuzzy: bool = True,
    ) -> int | None:
        country = clean_country(country)
        full = normalise_name(name)
        search = search_name(name)
        cached = self.resolved_aliases.get((country, full))
        if cached is not None:
            return cached
        candidates = self._unique(self.full_keys.get((country, full))) if country else None
        explicit_target = EXPLICIT_SOURCE_ALIASES.get((country, full))
        if candidates is None and explicit_target:
            candidates = self._unique(self.full_keys.get((country, explicit_target)))
        if candidates is None and search and country:
            candidates = self._unique(self.search_keys.get((country, search)))
        if candidates is None:
            global_candidate = self._unique(self.global_full.get(full))
            if global_candidate is None and search:
                global_candidate = self._unique(self.global_search.get(search))
            if global_candidate is not None and (
                not country
                or self.clubs[global_candidate].country in CROSS_BORDER_JURISDICTIONS.get(country, set())
            ):
                candidates = global_candidate
        if candidates is not None:
            self.resolved_aliases[(country, full)] = candidates
            return candidates

        if allow_fuzzy and len(search) >= 5:
            pool = [club for club in self.clubs if not country or club.country == country]
            scored = sorted(
                (
                    (SequenceMatcher(None, search, search_name(club.name)).ratio(), club.index)
                    for club in pool
                    if search_name(club.name)
                ),
                reverse=True,
            )[:2]
            if scored and scored[0][0] >= 0.925 and (
                len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.035
            ):
                self.resolved_aliases[(country, full)] = scored[0][1]
                return scored[0][1]

        if create_identity is None:
            return None
        created = self.add(
            create_identity,
            name,
            country,
            resolution=resolution,
        )
        self.resolved_aliases[(country, full)] = created
        return created

    def resolve_brazil_team(
        self,
        name: str,
        state: str,
        *,
        create_identity: str,
        resolution: str,
        state_strict: bool,
    ) -> int:
        """Resolve a Brazilian label without joining same-name interstate clubs.

        CBF rows begin state-scoped and are later joined to the historical
        backbone by fixture fingerprints.  State-championship rows first
        consult that CBF identity and, if it is absent, create their own.
        """
        state = str(state or "").strip().upper()
        full = normalise_name(name)
        search = search_name(name)
        existing = self.identity_to_index.get(create_identity)
        if existing is not None:
            return existing

        target = BRAZIL_STATE_SOURCE_ALIASES.get((state, full))
        if target is None:
            target = EXPLICIT_SOURCE_ALIASES.get(("brazil", full))
        if target:
            candidate = self._unique(self.full_keys.get(("brazil", target)))
            if candidate is None:
                candidate = self.identity_to_index.get(f"brazil:{state}:{target}")
            if candidate is not None:
                self.identity_to_index[create_identity] = candidate
                return candidate

        cbf_identity = f"brazil:{state}:{search}"
        if state_strict:
            candidate = self.identity_to_index.get(cbf_identity)
            if candidate is not None:
                self.identity_to_index[create_identity] = candidate
                return candidate
            return self.add(
                create_identity,
                name,
                "brazil",
                resolution=resolution,
            )

        candidate = self.resolve(
            name,
            "brazil",
            create_identity=create_identity,
            resolution=resolution,
        )
        assert candidate is not None
        self.identity_to_index[create_identity] = candidate
        return candidate

    def redirect(self, old: int, new: int) -> None:
        """Make every known alias for ``old`` resolve to canonical ``new``."""
        if old == new:
            return
        old_club = self.clubs[old]
        for mapping in (
            self.full_keys,
            self.search_keys,
            self.global_full,
            self.global_search,
        ):
            for values in mapping.values():
                if old in values:
                    values.discard(old)
                    values.add(new)
        for key, value in list(self.resolved_aliases.items()):
            if value == old:
                self.resolved_aliases[key] = new
        self.resolved_aliases[(old_club.country, normalise_name(old_club.name))] = new
        self.identity_to_index[old_club.identity] = new
        old_club.resolution = f"redirected to {self.clubs[new].identity} by fixture fingerprint"


RAW_SCHEMA = """
CREATE TABLE raw_matches (
    day DATE NOT NULL,
    season INTEGER NOT NULL,
    home INTEGER NOT NULL,
    away INTEGER NOT NULL,
    home_goals SMALLINT NOT NULL,
    away_goals SMALLINT NOT NULL,
    competition VARCHAR NOT NULL,
    competition_key VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    home_tier SMALLINT NOT NULL,
    away_tier SMALLINT NOT NULL,
    neutral BOOLEAN NOT NULL,
    cross_border BOOLEAN NOT NULL,
    status VARCHAR NOT NULL,
    leg SMALLINT NOT NULL,
    tie_key VARCHAR,
    round_name VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    source_ref VARCHAR NOT NULL,
    priority SMALLINT NOT NULL
)
"""
RAW_FIELDS = (
    "day", "season", "home", "away", "home_goals", "away_goals",
    "competition", "competition_key", "kind", "home_tier", "away_tier",
    "neutral", "cross_border", "status", "leg", "tie_key", "round_name",
    "source", "source_ref", "priority",
)


class ClubLedgerBuilder:
    def __init__(self, database: Path, cache: Path, source: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        database.unlink(missing_ok=True)
        self.database = database
        self.cache = cache
        self.source = source
        self.connection = duckdb.connect(str(database))
        self.connection.execute("PRAGMA threads=4")
        self.connection.execute(RAW_SCHEMA)
        self.registry = ClubRegistry()
        self.tiers: dict[tuple[int, int], int] = {}
        self.tiers_by_club: dict[int, dict[int, int]] = defaultdict(dict)

    def close(self) -> None:
        self.connection.close()

    def _insert(self, rows: Iterable[tuple[Any, ...]], batch_size: int = 20_000) -> int:
        # DuckDB's DB-API ``executemany`` performs one Python boundary crossing
        # per row.  A temporary tab-separated stream keeps the normaliser
        # dependency-light while making 300k-row deep-tier imports seconds,
        # not minutes.  CSV quoting protects competition and round labels.
        del batch_size  # retained for call-site compatibility
        count = 0
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=self.database.parent,
            prefix=".club-rows-",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            for row in rows:
                if row[2] == row[3]:
                    continue
                writer.writerow([r"\N" if value is None else value for value in row])
                count += 1
        try:
            self.connection.execute(
                "COPY raw_matches FROM ? "
                "(FORMAT CSV, DELIM '\\t', HEADER false, NULLSTR '\\N')",
                [str(temporary)],
            )
        finally:
            temporary.unlink(missing_ok=True)
        return count

    @staticmethod
    def _base_name(identity: str, fallback: str) -> str:
        stripped = re.sub(r"\s+\([^()]*(?:Country|[A-Za-z .'-]+)\)\s*$", "", identity).strip()
        return stripped or fallback.strip() or identity.strip()

    def load_backbone(self) -> int:
        path = self.cache / "schochastics-games.parquet"
        sides = self.connection.execute(
            """
            WITH sides AS (
                SELECT home_ident ident, home display, home_country country,
                       home_code country_code, home_continent continent, date
                FROM read_parquet(?)
                UNION ALL
                SELECT away_ident, away, away_country, away_code, away_continent, date
                FROM read_parquet(?)
            )
            SELECT ident, arg_max(display,date) display, arg_max(country,date) country,
                   arg_max(country_code,date) country_code, arg_max(continent,date) continent
            FROM sides
            WHERE ident IS NOT NULL AND NOT regexp_matches(ident, '^\\s*(\\([^)]*\\))?\\s*$')
            GROUP BY ident ORDER BY ident
            """,
            [str(path), str(path)],
        ).fetchall()
        mapping = []
        for identity, fallback, country, country_code, continent in sides:
            canonical_identity = BACKBONE_IDENTITY_ALIASES.get(
                str(identity), str(identity)
            )
            index = self.registry.add(
                f"backbone:{canonical_identity}",
                self._base_name(canonical_identity, str(fallback or "")),
                str(country or ""),
                str(country_code or ""),
                str(continent or "").title(),
                "historical backbone identity",
            )
            mapping.append((identity, index))
        self.connection.execute("CREATE TEMP TABLE backbone_clubs(ident VARCHAR, club INTEGER)")
        self.connection.executemany("INSERT INTO backbone_clubs VALUES (?,?)", mapping)
        self.connection.execute(
            """
            INSERT INTO raw_matches
            SELECT
                g.date,
                year(g.date),
                h.club,
                a.club,
                CAST(g.gh AS SMALLINT),
                CAST(g.ga AS SMALLINT),
                CASE
                    WHEN g.level='international' THEN coalesce(n.display, g.competition)
                    ELSE concat(
                        replace(
                            CASE
                                WHEN coalesce(g.competition,'')='' THEN g.home_country
                                WHEN g.competition='Copa Sud' THEN 'chile'
                                ELSE g.competition
                            END,
                            '-', ' '
                        ),
                        ' top division'
                    )
                END,
                concat(
                    'backbone:',g.level,':',
                    CASE
                        WHEN g.level='national' AND coalesce(g.competition,'')=''
                            THEN g.home_country
                        WHEN g.level='national' AND g.competition='Copa Sud'
                            THEN 'chile'
                        ELSE g.competition
                    END
                ),
                CASE
                    WHEN g.level='national' THEN 'league'
                    WHEN g.competition='Fifa Club' THEN 'global'
                    WHEN g.competition IN ('UEFA SC','CAF SC','Recopa') THEN 'super_cup'
                    ELSE 'continental'
                END,
                1,1,false,g.level='international',coalesce(g.full_time,'F'),0,NULL,'',
                'schochastics',concat('games.parquet:',cast(g.date as varchar)),10
            FROM read_parquet(?) g
            JOIN backbone_clubs h ON h.ident=g.home_ident
            JOIN backbone_clubs a ON a.ident=g.away_ident
            LEFT JOIN (VALUES
                ('AFC CL','AFC Champions League'),('AFC Pokal','AFC Cup'),
                ('AFC Pres Cup','AFC President''s Cup'),('CAF CC','CAF Confederation Cup'),
                ('CAF CL','CAF Champions League'),('CAF SC','CAF Super Cup'),
                ('CFU CC','Caribbean Club Championship'),
                ('CONCACAF CC','CONCACAF Champions Cup'),
                ('CONCACAF L','CONCACAF League'),('Copa Lib','Copa Libertadores'),
                ('Copa Sud','Copa Sudamericana'),('Fifa Club','FIFA Club World Cup'),
                ('OFC CC','OFC Champions League'),('Recopa','Recopa Sudamericana'),
                ('UEFA CL','UEFA Champions League'),
                ('UEFA CONF L','UEFA Conference League'),
                ('UEFA EL','UEFA Europa League'),('UEFA ITC','UEFA Intertoto Cup'),
                ('UEFA SC','UEFA Super Cup')
            ) n(code,display) ON n.code=g.competition
            WHERE g.gh IS NOT NULL AND g.ga IS NOT NULL
            """,
            [str(path)],
        )
        count = self.connection.execute(
            "SELECT count(*) FROM raw_matches WHERE source='schochastics'"
        ).fetchone()[0]
        for club, year_value in self.connection.execute(
            """
            SELECT club, year(day) FROM (
                SELECT home club, day FROM raw_matches WHERE source='schochastics' AND kind='league'
                UNION ALL SELECT away, day FROM raw_matches WHERE source='schochastics' AND kind='league'
            ) GROUP BY ALL
            """
        ).fetchall():
            self._remember_tier(int(club), int(year_value), 1)
        return int(count)

    def _remember_tier(self, club: int, season: int, tier: int) -> None:
        key = (club, season)
        resolved = min(tier, self.tiers.get(key, tier))
        self.tiers[key] = resolved
        self.tiers_by_club[club][season] = resolved

    def infer_tier(self, club: int, season: int, default: int) -> int:
        if (club, season) in self.tiers:
            return self.tiers[(club, season)]
        candidates = [
            (abs(known_year - season), tier)
            for known_year, tier in self.tiers_by_club.get(club, {}).items()
            if abs(known_year - season) <= 2
        ]
        return min(candidates)[1] if candidates else default

    def _deep_league_rows(
        self,
        filename: str,
        country: str,
        minimum_tier: int,
        *,
        exclude_tiers: set[int] | None = None,
    ) -> Iterator[tuple[Any, ...]]:
        path = self.cache / "engsoccerdata" / filename
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for number, row in enumerate(csv.DictReader(handle), start=2):
                day = safe_date(row.get("Date") or row.get("date"))
                tier = integer(row.get("tier"))
                home_goals = integer(row.get("hgoal"))
                away_goals = integer(row.get("vgoal"))
                if (
                    day is None or tier is None or tier < minimum_tier
                    or (exclude_tiers and tier in exclude_tiers)
                    or home_goals is None or away_goals is None
                ):
                    continue
                season = integer(row.get("Season") or row.get("season"), int(day[:4])) or int(day[:4])
                home_name = str(row.get("home") or "").strip()
                away_name = str(row.get("visitor") or row.get("away") or "").strip()
                if not home_name or not away_name:
                    continue
                home = self.registry.resolve(
                    home_name, country,
                    create_identity=f"engsoccer:{country}:{search_name(home_name)}",
                    resolution="engsoccerdata identity",
                )
                away = self.registry.resolve(
                    away_name, country,
                    create_identity=f"engsoccer:{country}:{search_name(away_name)}",
                    resolution="engsoccerdata identity",
                )
                assert home is not None and away is not None
                self._remember_tier(home, season, tier)
                self._remember_tier(away, season, tier)
                display = f"{display_country(clean_country(country))} tier {tier}"
                yield (
                    day, season, home, away, home_goals, away_goals, display,
                    f"deep:league:{clean_country(country)}:{tier}", "league", tier, tier,
                    False, False, "F", 0, None, str(row.get("division") or ""),
                    "engsoccerdata", f"{filename}:{number}", 30,
                )

    @staticmethod
    def _yes(value: Any) -> bool:
        return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}

    def _cup_row(
        self,
        row: dict[str, str],
        number: int,
        filename: str,
        competition: str,
        default_tier: int,
        *,
        kind: str = "domestic_cup",
        country: str = "england",
    ) -> tuple[Any, ...] | None:
        day = safe_date(row.get("Date") or row.get("date"))
        home_goals = integer(row.get("hgoal"))
        away_goals = integer(row.get("vgoal"))
        if day is None or home_goals is None or away_goals is None:
            return None
        if str(row.get("nonmatch") or "").strip().casefold() not in {"", "na", "none"}:
            return None
        season = integer(row.get("Season") or row.get("season"), int(day[:4])) or int(day[:4])
        home_name = str(row.get("home") or "").strip()
        away_name = str(row.get("visitor") or row.get("away") or "").strip()
        if not home_name or not away_name:
            return None
        home_country = country
        away_country = country
        if filename == "champs.csv":
            home_country = COUNTRY_CODE_ALIASES.get(str(row.get("hcountry") or "").upper(), "")
            away_country = COUNTRY_CODE_ALIASES.get(str(row.get("vcountry") or "").upper(), "")
        home = self.registry.resolve(
            home_name, home_country,
            create_identity=f"engsoccer:{home_country}:{search_name(home_name)}",
            resolution="engsoccerdata cup identity",
        )
        away = self.registry.resolve(
            away_name, away_country,
            create_identity=f"engsoccer:{away_country}:{search_name(away_name)}",
            resolution="engsoccerdata cup identity",
        )
        assert home is not None and away is not None
        home_tier = self.infer_tier(home, season, default_tier)
        away_tier = self.infer_tier(away, season, default_tier)
        status = "P" if self._yes(row.get("pen")) or str(row.get("pens") or "").strip().casefold() not in {"", "na"} else (
            "E" if self._yes(row.get("aet")) else "F"
        )
        leg = integer(row.get("leg"), 0) or 0
        if leg not in {1, 2}:
            leg = 0
        round_name = str(row.get("round") or row.get("division") or "")
        tie_key = None
        if leg:
            first, second = sorted((home, away))
            tie_key = f"eng:{filename}:{season}:{round_name}:{first}:{second}"
        neutral = self._yes(row.get("neutral"))
        return (
            day, season, home, away, home_goals, away_goals, competition,
            f"deep:cup:{filename}:{competition}", kind, home_tier, away_tier,
            neutral, kind == "continental", status, leg, tie_key, round_name,
            "engsoccerdata", f"{filename}:{number}", 30,
        )

    def load_deep_sources(self) -> int:
        total = 0
        total += self._insert(self._deep_league_rows("england.csv", "england", 2))
        total += self._insert(self._deep_league_rows("england5.csv", "england", 5))
        total += self._insert(
            self._deep_league_rows("england_nonleague.csv", "england", 6)
        )
        total += self._insert(self._deep_league_rows("scotland.csv", "scotland", 2))
        total += self._insert(self._deep_league_rows("germany.csv", "germany", 2))
        cup_specs = (
            ("facup.csv", "FA Cup", 5, "domestic_cup", "england"),
            ("leaguecup.csv", "English League Cup", 4, "domestic_cup", "england"),
            ("englandplayoffs.csv", "English promotion playoffs", 4, "playoff", "england"),
            ("champs.csv", "UEFA Champions League", 1, "continental", ""),
        )
        for filename, competition, default_tier, kind, country in cup_specs:
            path = self.cache / "engsoccerdata" / filename
            rows = []
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for number, row in enumerate(csv.DictReader(handle), start=2):
                    parsed = self._cup_row(
                        row, number, filename, competition, default_tier,
                        kind=kind, country=country,
                    )
                    if parsed is not None:
                        rows.append(parsed)
            total += self._insert(rows)
        return total

    def reconcile_source_identities(self, source_name: str) -> int:
        """Merge supplemental aliases into backbone clubs using match fingerprints.

        A date + goals-for + goals-against signature across several fixtures is
        far safer than increasingly aggressive text normalisation.  Candidate
        pairs must also share a country, clear the same margin safeguards used
        for the current feed, and beat the runner-up.
        """
        supplemental = [
            club.index
            for club in self.registry.clubs
            if club.resolution in {
                "engsoccerdata identity",
                "engsoccerdata cup identity",
                "CBF match-report identity",
            }
            and self.registry.identity_to_index.get(club.identity) == club.index
        ]
        if not supplemental:
            return 0
        backbone = [
            club.index
            for club in self.registry.clubs
            if club.identity.startswith("backbone:")
        ]
        self.connection.execute("DROP TABLE IF EXISTS reconcile_source_clubs")
        self.connection.execute("DROP TABLE IF EXISTS reconcile_backbone_clubs")
        self.connection.execute(
            "CREATE TEMP TABLE reconcile_source_clubs(club INTEGER,country VARCHAR)"
        )
        self.connection.execute(
            "CREATE TEMP TABLE reconcile_backbone_clubs(club INTEGER,country VARCHAR)"
        )
        self.connection.executemany(
            "INSERT INTO reconcile_source_clubs VALUES (?,?)",
            [(club, self.registry.clubs[club].country) for club in supplemental],
        )
        self.connection.executemany(
            "INSERT INTO reconcile_backbone_clubs VALUES (?,?)",
            [(club, self.registry.clubs[club].country) for club in backbone],
        )
        candidates = self.connection.execute(
            """
            WITH supplemental_sides AS (
                SELECT home club,day,home_goals gf,away_goals ga
                FROM raw_matches WHERE source=?
                UNION ALL
                SELECT away,day,away_goals,home_goals
                FROM raw_matches WHERE source=?
            ), backbone_sides AS (
                SELECT home club,day,home_goals gf,away_goals ga
                FROM raw_matches WHERE source='schochastics'
                UNION ALL
                SELECT away,day,away_goals,home_goals
                FROM raw_matches WHERE source='schochastics'
            )
            SELECT s.club old_club,b.club canonical_club,count(*) score
            FROM supplemental_sides s
            JOIN reconcile_source_clubs sm ON sm.club=s.club
            JOIN backbone_sides b USING(day,gf,ga)
            JOIN reconcile_backbone_clubs bm
              ON bm.club=b.club AND bm.country=sm.country
            GROUP BY ALL ORDER BY old_club,score DESC,canonical_club
            """,
            [source_name, source_name],
        ).fetchall()
        totals = dict(
            self.connection.execute(
                """
                SELECT club,count(*) FROM (
                    SELECT home club FROM raw_matches WHERE source=?
                    UNION ALL SELECT away FROM raw_matches WHERE source=?
                ) GROUP BY club
                """,
                [source_name, source_name],
            ).fetchall()
        )
        grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for old, canonical, score in candidates:
            if len(grouped[int(old)]) < 2:
                grouped[int(old)].append((int(canonical), int(score)))
        redirects: list[tuple[int, int]] = []
        for old, options in grouped.items():
            best, score = options[0]
            runner = options[1][1] if len(options) > 1 else 0
            text_similarity = SequenceMatcher(
                None,
                search_name(self.registry.clubs[old].name),
                search_name(self.registry.clubs[best].name),
            ).ratio()
            acronym_match = (
                name_acronym(self.registry.clubs[old].name)
                == name_acronym(self.registry.clubs[best].name)
                and len(name_acronym(self.registry.clubs[old].name)) >= 2
            )
            alias_pair = (
                normalise_name(self.registry.clubs[old].name),
                normalise_name(self.registry.clubs[best].name),
            )
            if (
                text_similarity < 0.85
                and not acronym_match
                and alias_pair not in KNOWN_CLUB_ALIAS_PAIRS
            ):
                continue
            threshold = 2 if text_similarity >= 0.88 else 4
            margin = 1 if text_similarity >= 0.88 else 3
            if (
                score >= threshold
                and score >= runner + margin
                and score >= int(totals.get(old, 0)) * 0.035
            ):
                redirects.append((old, best))
        if not redirects:
            return 0
        self.connection.execute("DROP TABLE IF EXISTS club_redirects")
        self.connection.execute(
            "CREATE TEMP TABLE club_redirects(old_club INTEGER,new_club INTEGER)"
        )
        self.connection.executemany("INSERT INTO club_redirects VALUES (?,?)", redirects)
        self.connection.execute(
            """
            UPDATE raw_matches SET home=r.new_club FROM club_redirects r
            WHERE raw_matches.home=r.old_club
            """
        )
        self.connection.execute(
            """
            UPDATE raw_matches SET away=r.new_club FROM club_redirects r
            WHERE raw_matches.away=r.old_club
            """
        )
        for old, new in redirects:
            self.registry.redirect(old, new)
            years = self.tiers_by_club.pop(old, {})
            for season, tier in years.items():
                self._remember_tier(new, season, tier)
        print(f"club identity reconciliation: {len(redirects)} {source_name} aliases merged")
        return len(redirects)

    def load_brazil(self) -> int:
        path = self.source / "club_brazil.csv.gz"
        if not path.is_file():
            return 0
        prepared: list[list[Any]] = []
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for number, row in enumerate(csv.DictReader(handle), start=2):
                day = safe_date(row.get("date"))
                home_goals = integer(row.get("home_goals"))
                away_goals = integer(row.get("away_goals"))
                if day is None or home_goals is None or away_goals is None:
                    continue
                season = integer(row.get("season"), int(day[:4])) or int(day[:4])
                tier = integer(row.get("tier"), 1) or 1
                home_name = str(row.get("home") or "").strip()
                away_name = str(row.get("away") or "").strip()
                home = self.registry.resolve_brazil_team(
                    home_name, str(row.get("home_state") or ""),
                    create_identity=f"brazil:{row.get('home_state','')}:{search_name(home_name)}",
                    resolution="CBF match-report identity",
                    state_strict=True,
                )
                away = self.registry.resolve_brazil_team(
                    away_name, str(row.get("away_state") or ""),
                    create_identity=f"brazil:{row.get('away_state','')}:{search_name(away_name)}",
                    resolution="CBF match-report identity",
                    state_strict=True,
                )
                assert home is not None and away is not None
                kind = str(row.get("kind") or "league")
                if kind == "league":
                    self._remember_tier(home, season, tier)
                    self._remember_tier(away, season, tier)
                    home_tier = away_tier = tier
                else:
                    home_tier = self.infer_tier(home, season, 4)
                    away_tier = self.infer_tier(away, season, 4)
                prepared.append([
                    day, season, home, away, home_goals, away_goals,
                    str(row.get("competition") or "Brazil club competition"),
                    f"brazil:{row.get('competition','')}", kind, home_tier, away_tier,
                    False, False, "F", 0, None, "", "brazilianfootball-data",
                    f"{row.get('source_file','')}:{row.get('source_id',number)}", 35,
                ])

        cups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        for index, row in enumerate(prepared):
            if row[8] == "domestic_cup":
                cups[(row[1], min(row[2], row[3]), max(row[2], row[3]))].append(index)
        for (season, first, second), indexes in cups.items():
            indexes.sort(key=lambda item: prepared[item][0])
            if len(indexes) != 2:
                continue
            one, two = (prepared[indexes[0]], prepared[indexes[1]])
            distance = (date.fromisoformat(two[0]) - date.fromisoformat(one[0])).days
            if 1 <= distance <= 75 and one[2] == two[3] and one[3] == two[2]:
                tie_key = f"brazil-cup:{season}:{first}:{second}"
                one[14], one[15] = 1, tie_key
                two[14], two[15] = 2, tie_key
        return self._insert(tuple(row) for row in prepared)

    def load_brazil_states(self) -> int:
        path = self.source / "club_brazil_states.csv.gz"
        if not path.is_file():
            return 0
        prepared: list[list[Any]] = []
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for number, row in enumerate(csv.DictReader(handle), start=2):
                day = safe_date(row.get("date"))
                home_goals = integer(row.get("home_goals"))
                away_goals = integer(row.get("away_goals"))
                if day is None or home_goals is None or away_goals is None:
                    continue
                season = integer(row.get("season"), int(day[:4])) or int(day[:4])
                state = str(row.get("state") or "").upper()
                home_name = str(row.get("home") or "").strip()
                away_name = str(row.get("away") or "").strip()
                if not home_name or not away_name or home_name == away_name:
                    continue
                home = self.registry.resolve_brazil_team(
                    home_name,
                    state,
                    create_identity=f"brazil-state:{state}:{search_name(home_name)}",
                    resolution="Brazil state championship identity",
                    state_strict=True,
                )
                away = self.registry.resolve_brazil_team(
                    away_name,
                    state,
                    create_identity=f"brazil-state:{state}:{search_name(away_name)}",
                    resolution="Brazil state championship identity",
                    state_strict=True,
                )
                assert home is not None and away is not None
                home_tier = self.infer_tier(home, season, 4)
                away_tier = self.infer_tier(away, season, 4)
                competition = str(row.get("competition") or "Brazil state championship")
                prepared.append(
                    [
                        day, season, home, away, home_goals, away_goals,
                        competition, f"state:brazil:{state}:{normalise_name(competition)}",
                        "state", home_tier, away_tier, False, False, "F", 0,
                        None, str(row.get("round") or ""),
                        "ferreras-footballdata",
                        f"{row.get('source_file','')}:{row.get('source_id',number)}",
                        34,
                    ]
                )

        knockout: dict[tuple[int, str, str, int, int], list[int]] = defaultdict(list)
        for index, row in enumerate(prepared):
            round_key = normalise_name(row[16])
            if not any(
                label in round_key
                for label in ("oitavas", "quartas", "semifinal", "final", "playoff")
            ):
                continue
            knockout[
                (row[1], row[7], round_key, min(row[2], row[3]), max(row[2], row[3]))
            ].append(index)
        for key, indexes in knockout.items():
            indexes.sort(key=lambda item: prepared[item][0])
            if len(indexes) != 2:
                continue
            one, two = prepared[indexes[0]], prepared[indexes[1]]
            distance = (date.fromisoformat(two[0]) - date.fromisoformat(one[0])).days
            if 1 <= distance <= 75 and one[2] == two[3] and one[3] == two[2]:
                tie_key = "state:" + ":".join(map(str, key))
                one[14], one[15] = 1, tie_key
                two[14], two[15] = 2, tie_key
        return self._insert(tuple(row) for row in prepared)

    @staticmethod
    def _tm_leg(round_name: str) -> tuple[int, str]:
        text = round_name.casefold()
        first = re.search(r"(?:1st|first)\s*leg|hinspiel", text)
        second = re.search(r"(?:2nd|second)\s*leg|r[üu]ckspiel", text)
        leg = 1 if first else (2 if second else 0)
        base = re.sub(
            r"(?:1st|first|2nd|second)\s*leg|hinspiel|r[üu]ckspiel",
            " ", text,
        )
        return leg, " ".join(base.split())

    def load_transfermarkt(self) -> int:
        directory = self.cache / "transfermarkt"
        competitions: dict[str, dict[str, str]] = {}
        with gzip.open(directory / "competitions.csv.gz", "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                competitions[str(row["competition_id"])] = row
        club_rows: dict[int, dict[str, str]] = {}
        with gzip.open(directory / "clubs.csv.gz", "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                club_rows[int(row["club_id"])] = row
        games: list[dict[str, str]] = []
        with gzip.open(directory / "games.csv.gz", "rt", encoding="utf-8-sig", newline="") as handle:
            games.extend(csv.DictReader(handle))

        mapping: dict[int, int] = {}
        unresolved: set[int] = set()
        for tm_id, row in club_rows.items():
            competition = competitions.get(str(row.get("domestic_competition_id") or ""), {})
            country = clean_country(competition.get("country_name"))
            resolved = self.registry.resolve(str(row.get("name") or ""), country, allow_fuzzy=False)
            if resolved is None:
                unresolved.add(tm_id)
            else:
                mapping[tm_id] = resolved

        self.connection.execute(
            "CREATE TEMP TABLE tm_sides(tm_id INTEGER, day DATE, gf SMALLINT, ga SMALLINT)"
        )
        sides: list[tuple[int, str, int, int]] = []
        totals: Counter[int] = Counter()
        for row in games:
            day = safe_date(row.get("date"))
            home = integer(row.get("home_club_id"))
            away = integer(row.get("away_club_id"))
            home_goals = integer(row.get("home_club_goals"))
            away_goals = integer(row.get("away_club_goals"))
            if None in {day, home, away, home_goals, away_goals}:
                continue
            assert day is not None and home is not None and away is not None
            assert home_goals is not None and away_goals is not None
            sides.append((home, day, home_goals, away_goals))
            sides.append((away, day, away_goals, home_goals))
            totals[home] += 1
            totals[away] += 1
        self.connection.executemany("INSERT INTO tm_sides VALUES (?,?,?,?)", sides)
        candidates = self.connection.execute(
            """
            WITH known AS (
                SELECT home club, day, home_goals gf, away_goals ga
                FROM raw_matches WHERE day >= DATE '2006-01-01'
                UNION ALL
                SELECT away, day, away_goals, home_goals
                FROM raw_matches WHERE day >= DATE '2006-01-01'
            )
            SELECT t.tm_id,k.club,count(*) score
            FROM tm_sides t JOIN known k USING(day,gf,ga)
            GROUP BY ALL ORDER BY t.tm_id,score DESC,k.club
            """
        ).fetchall()
        by_tm: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for tm_id, club, score in candidates:
            if len(by_tm[int(tm_id)]) < 2:
                by_tm[int(tm_id)].append((int(club), int(score)))
        fingerprint_matches = 0
        for tm_id in list(unresolved):
            options = by_tm.get(tm_id, [])
            if not options:
                continue
            best_club, best = options[0]
            runner = options[1][1] if len(options) > 1 else 0
            if best >= 4 and best >= runner + 3 and best >= totals[tm_id] * 0.04:
                mapping[tm_id] = best_club
                unresolved.remove(tm_id)
                fingerprint_matches += 1

        for tm_id in sorted(unresolved):
            row = club_rows[tm_id]
            competition = competitions.get(str(row.get("domestic_competition_id") or ""), {})
            country = clean_country(competition.get("country_name"))
            resolved = self.registry.resolve(
                str(row.get("name") or f"Club {tm_id}"), country,
                create_identity=f"transfermarkt:{tm_id}",
                resolution="Transfermarkt source identity",
            )
            assert resolved is not None
            mapping[tm_id] = resolved

        tier_by_tm_season: dict[tuple[int, int], int] = {}
        for row in games:
            comp = competitions.get(str(row.get("competition_id") or ""), {})
            subtype = str(comp.get("sub_type") or "")
            match = re.search(r"(first|second|third|fourth)_tier", subtype)
            if not match:
                continue
            tier = {"first": 1, "second": 2, "third": 3, "fourth": 4}[match.group(1)]
            season = integer(row.get("season"), 0) or 0
            for field in ("home_club_id", "away_club_id"):
                tm_id = integer(row.get(field))
                if tm_id is not None:
                    tier_by_tm_season[(tm_id, season)] = tier

        prepared: list[tuple[Any, ...]] = []
        for row in games:
            comp_id = str(row.get("competition_id") or "")
            comp = competitions.get(comp_id, {})
            comp_type = str(comp.get("type") or row.get("competition_type") or "")
            if comp_type == "national_team_competition":
                continue
            day = safe_date(row.get("date"))
            home_id = integer(row.get("home_club_id"))
            away_id = integer(row.get("away_club_id"))
            home_goals = integer(row.get("home_club_goals"))
            away_goals = integer(row.get("away_club_goals"))
            if None in {day, home_id, away_id, home_goals, away_goals}:
                continue
            assert day is not None and home_id is not None and away_id is not None
            assert home_goals is not None and away_goals is not None
            if home_id not in mapping or away_id not in mapping:
                continue
            season = integer(row.get("season"), int(day[:4])) or int(day[:4])
            subtype = str(comp.get("sub_type") or "")
            if comp_type == "domestic_league":
                kind = "league"
            elif comp_type == "domestic_cup":
                kind = "domestic_cup"
            elif "super_cup" in subtype:
                kind = "super_cup"
            elif comp_id in {"CL", "CLQ", "EL", "ELQ", "UCOL", "ECLQ"}:
                kind = "continental"
            elif comp_type == "international_cup":
                kind = "continental"
            elif subtype == "play_off":
                kind = "playoff"
            else:
                kind = "domestic_cup" if comp.get("country_name") else "continental"
            home = mapping[home_id]
            away = mapping[away_id]
            home_tier = tier_by_tm_season.get(
                (home_id, season), self.infer_tier(home, season, 1 if kind == "league" else 3)
            )
            away_tier = tier_by_tm_season.get(
                (away_id, season), self.infer_tier(away, season, 1 if kind == "league" else 3)
            )
            if kind == "league":
                self._remember_tier(home, season, home_tier)
                self._remember_tier(away, season, away_tier)
            round_name = str(row.get("round") or "")
            leg, round_base = self._tm_leg(round_name)
            tie_key = None
            if leg:
                first, second = sorted((home, away))
                tie_key = f"tm:{comp_id}:{season}:{round_base}:{first}:{second}"
            display = str(comp.get("name") or comp.get("competition_code") or comp_id)
            display = " ".join(display.replace("-", " ").split()).title()
            neutral = leg == 0 and round_name.strip().casefold() == "final" and kind in {
                "domestic_cup", "continental", "global"
            }
            cross_border = not bool(comp.get("country_name")) and kind in {
                "continental", "intercontinental", "global", "super_cup"
            }
            prepared.append((
                day, season, home, away, home_goals, away_goals, display,
                f"tm:{comp_id}", kind, home_tier, away_tier, neutral,
                cross_border, "F", leg, tie_key, round_name, "transfermarkt",
                f"games.csv.gz:{row.get('game_id','')}", 20,
            ))
        print(
            f"Transfermarkt identity resolution: {len(mapping) - len(unresolved)} linked; "
            f"{fingerprint_matches} by fixture fingerprint; {len(unresolved)} source identities"
        )
        return self._insert(prepared)

    def finalise(self) -> dict[str, Any]:
        self.connection.execute(
            """
            CREATE TABLE matches AS
            WITH chosen AS (
                SELECT *, row_number() OVER (
                    PARTITION BY day,home,away
                    ORDER BY priority DESC,
                             CASE WHEN leg IN (1,2) THEN 1 ELSE 0 END DESC,
                             source_ref
                ) choice
                FROM raw_matches
            ), deduped AS (
                SELECT * EXCLUDE(choice,priority) FROM chosen WHERE choice=1
            ), unique_first AS (
                SELECT tie_key,min(home) home,min(away) away,
                       min(home_goals) home_goals,min(away_goals) away_goals
                FROM deduped
                WHERE leg=1 AND tie_key IS NOT NULL
                GROUP BY tie_key HAVING count(*)=1
            ), paired AS (
                SELECT d.*,
                       CASE WHEN d.leg=2 THEN
                           CASE WHEN first.home=d.home
                                THEN first.home_goals-first.away_goals
                                ELSE first.away_goals-first.home_goals END
                       END aggregate_before_home
                FROM deduped d
                LEFT JOIN unique_first first
                  ON d.leg=2 AND d.tie_key=first.tie_key
            )
            SELECT
                md5(concat(cast(day as varchar),'|',home,'|',away,'|',
                           home_goals,'|',away_goals,'|',competition_key)) match_id,
                *,
                CASE WHEN aggregate_before_home IS NOT NULL
                     THEN aggregate_before_home+home_goals-away_goals END aggregate_after_home
            FROM paired
            ORDER BY day,match_id
            """
        )
        self.connection.execute(
            """
            CREATE TABLE clubs(
                club INTEGER, code VARCHAR, name VARCHAR, country VARCHAR,
                country_name VARCHAR, country_code VARCHAR, continent VARCHAR,
                identity VARCHAR, resolution VARCHAR
            )
            """
        )
        rows = [
            (
                club.index, club.code, club.name, club.country,
                display_country(club.country) if club.country else "Unassigned",
                club.country_code, club.continent, club.identity, club.resolution,
            )
            for club in self.registry.clubs
        ]
        self.connection.executemany("INSERT INTO clubs VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self.connection.execute(
            """
            CREATE TABLE competition_coverage AS
            SELECT competition_key,competition,kind,count(*) matches,min(day) first_date,
                   max(day) last_date,count(distinct home)+count(distinct away) club_sides,
                   list_sort(list_distinct(list(source))) sources
            FROM matches GROUP BY ALL ORDER BY matches DESC,competition
            """
        )
        counts = self.connection.execute(
            """
            SELECT count(*) matches,count(distinct home)+count(distinct away) club_sides,
                   min(day) first_date,max(day) last_date,
                   sum(leg=2 AND aggregate_before_home IS NOT NULL) second_legs
            FROM matches
            """
        ).fetchone()
        source_counts = dict(
            self.connection.execute(
                "SELECT source,count(*) FROM matches GROUP BY source ORDER BY source"
            ).fetchall()
        )
        raw = self.connection.execute("SELECT count(*) FROM raw_matches").fetchone()[0]
        return {
            "raw_matches": int(raw),
            "matches": int(counts[0]),
            "clubs": len(self.registry.clubs),
            "club_sides": int(counts[1]),
            "first": str(counts[2]),
            "last": str(counts[3]),
            "explicit_second_legs": int(counts[4]),
            "deduplicated": int(raw - counts[0]),
            "sources": {str(key): int(value) for key, value in source_counts.items()},
        }

    def build(self) -> dict[str, Any]:
        inserted: dict[str, int] = {}
        inserted["schochastics"] = self.load_backbone()
        print(f"club ledger: loaded {inserted['schochastics']:,} schochastics candidate matches")
        inserted["engsoccerdata"] = self.load_deep_sources()
        print(f"club ledger: loaded {inserted['engsoccerdata']:,} engsoccerdata candidate matches")
        self.reconcile_source_identities("engsoccerdata")
        inserted["brazilianfootball-data"] = self.load_brazil()
        print(
            "club ledger: loaded "
            f"{inserted['brazilianfootball-data']:,} brazilianfootball-data candidate matches"
        )
        self.reconcile_source_identities("brazilianfootball-data")
        inserted["ferreras-footballdata"] = self.load_brazil_states()
        print(
            "club ledger: loaded "
            f"{inserted['ferreras-footballdata']:,} Brazilian state candidate matches"
        )
        inserted["transfermarkt"] = self.load_transfermarkt()
        print(f"club ledger: loaded {inserted['transfermarkt']:,} transfermarkt candidate matches")
        # Keep the three publication tables atomic.  DuckDB normally commits
        # DDL automatically, but an explicit boundary also makes persistence
        # unambiguous after the DB-API ``executemany`` used for the club table.
        self.connection.execute("BEGIN TRANSACTION")
        try:
            summary = self.finalise()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        summary["inserted"] = inserted
        self.connection.execute("CHECKPOINT")
        return summary


def build_club_ledger(database: Path, cache: Path, source: Path) -> dict[str, Any]:
    builder = ClubLedgerBuilder(database, cache, source)
    try:
        summary = builder.build()
    finally:
        builder.close()
    # A ledger is only complete when a fresh connection can see the canonical
    # tables.  Fail here rather than discovering an incomplete cache during a
    # later multi-hour model run.
    verifier = duckdb.connect(str(database), read_only=True)
    try:
        tables = {str(row[0]) for row in verifier.execute("SHOW TABLES").fetchall()}
        required = {"raw_matches", "matches", "clubs", "competition_coverage"}
        if not required.issubset(tables):
            raise RuntimeError(
                "club ledger persistence check failed; missing "
                + ", ".join(sorted(required - tables))
            )
        persisted = int(verifier.execute("SELECT count(*) FROM matches").fetchone()[0])
        if persisted != summary["matches"]:
            raise RuntimeError(
                f"club ledger persistence check expected {summary['matches']:,} "
                f"matches but reopened {persisted:,}"
            )
        distinct_ids = int(
            verifier.execute("SELECT count(distinct match_id) FROM matches").fetchone()[0]
        )
        if distinct_ids != persisted:
            raise RuntimeError(
                f"club ledger contains {persisted - distinct_ids:,} duplicate match ids"
            )
    finally:
        verifier.close()
    return summary


__all__ = [
    "ClubLedgerBuilder",
    "ClubRegistry",
    "build_club_ledger",
    "clean_country",
    "normalise_name",
    "search_name",
]
