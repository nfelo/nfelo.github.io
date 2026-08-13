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
    "cabo verde": "cape-verde",
    "cabo-verde": "cape-verde",
    "cape verde": "cape-verde",
    "cape-verde": "cape-verde",
    "cape verde islands": "cape-verde",
    "cape-verde-islands": "cape-verde",
    "czech republic": "czech-republic",
    "czechia": "czech-republic",
    "eng": "england",
    "ger": "germany",
    "deutschland": "germany",
    "korea south": "korea-republic",
    "ireland republic": "ireland",
    "ireland-republic": "ireland",
    "south korea": "korea-republic",
    "por": "portugal",
    "sco": "scotland",
    "turkiye": "turkey",
    "türkiye": "turkey",
    "united states": "united-states",
    "usa": "united-states",
}
COUNTRY_CODE_ALIASES = {
    "ALB": "albania", "AND": "andorra", "ARM": "armenia",
    "AUT": "austria", "AZE": "azerbaijan", "BEL": "belgium",
    "BGR": "bulgaria", "BUL": "bulgaria", "BLR": "belarus",
    "BIH": "bosnia-herzegovina",
    "CRO": "croatia", "CYP": "cyprus", "CZE": "czech-republic",
    "DEN": "denmark", "ENG": "england", "ESP": "spain",
    "EST": "estonia", "FIN": "finland", "FRA": "france",
    "FRO": "faroe-islands", "GIB": "gibraltar",
    "GEO": "georgia", "GER": "germany", "GRE": "greece",
    "HUN": "hungary", "IRL": "ireland", "ISL": "iceland",
    "ISR": "israel", "ITA": "italy", "KAZ": "kazakhstan",
    "LTU": "lithuania", "LUX": "luxembourg", "LVA": "latvia",
    "MDA": "moldova",
    "MKD": "north-macedonia", "MLT": "malta", "MNE": "montenegro",
    "NED": "netherlands", "NIR": "northern-ireland", "NOR": "norway",
    "POL": "poland", "POR": "portugal", "ROU": "romania",
    "RUS": "russia", "SCO": "scotland", "SRB": "serbia",
    "SMR": "san-marino", "SUI": "switzerland", "SVK": "slovakia",
    "SVN": "slovenia",
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
FOOTBALL_CONFEDERATION_FALLBACKS = {
    # Some continental-only feeds omit geography even though the association
    # itself is unambiguous.  These are affiliation fallbacks, not strength
    # assumptions; source geography still takes precedence when present.
    "afghanistan": "Asia",
    "andorra": "Europe",
    "bulgaria": "Europe",
    "cape-verde": "Africa",
    "central-african-republic": "Africa",
    "chad": "Africa",
    "colombia": "South America",
    "comoros": "Africa",
    "faroe-islands": "Europe",
    "ireland": "Europe",
    "lithuania": "Europe",
    "romania": "Europe",
    "san-marino": "Europe",
    "south-sudan": "Africa",
    "vanuatu": "Oceania",
    "zanzibar": "Africa",
}
REVIEWED_UNASSIGNED_ASSOCIATIONS = {
    # Exact labels whose source row omitted an association.  Every mapping is
    # limited to an otherwise empty/unknown identity; a name can never move a
    # club that already has source-backed association metadata.
    "alizefort": "comoros",
    "aspsi": "chad",
    "attackenergy": "afghanistan",
    "b36torshavn": "faroe-islands",
    "b68toftir": "faroe-islands",
    "banants": "armenia",
    "cdnasofia": "bulgaria",
    "centralafricanrepublicredstarfc": "central-african-republic",
    "classic": "vanuatu",
    "corvinul": "romania",
    "fkzalgirisvilnius": "lithuania",
    "gigota": "faroe-islands",
    "interbakupik": "azerbaijan",
    "jamus": "south-sudan",
    "kiklaksvik": "faroe-islands",
    "neftchipfcbaku": "azerbaijan",
    "pfcberoe": "bulgaria",
    "pfclokomotivplovdiv": "bulgaria",
    "pfcludogoretsrazgrad": "bulgaria",
    "pfcslaviasofia": "bulgaria",
    "rangers": "andorra",
    "ssfolgorefalcianocalcio": "san-marino",
    "trakiaplovdiv": "bulgaria",
    "uhamiaji": "zanzibar",
    "vagur": "faroe-islands",
    "vitoshasofia": "bulgaria",
}
PLACEHOLDER_CLUB_IDENTIFIERS = {"na", "none", "null", "tbd", "unknown", "bye"}
TRANSFERMARKT_FALLBACK_COMPETITIONS = {
    "CGB": ("EFL Cup", "domestic_cup", "England"),
    "COL1": ("Categoría Primera A", "league", "Colombia"),
    "KLUB": ("FIFA Club World Cup", "global", ""),
    "POCP": ("Taça de Portugal", "domestic_cup", "Portugal"),
    "UKRS": ("Ukrainian Super Cup", "super_cup", "Ukraine"),
}
# Transfermarkt's current-club catalog omits some historic or non-covered
# participants even though its game feed still uses their stable club IDs.
# These reviewed identities cover every such participant in the expanded 2025
# Club World Cup; deterministic global-name matching handles other omissions.
TRANSFERMARKT_GAME_ONLY_CLUB_FALLBACKS = {
    7: ("Al Ahly", "egypt"),
    2150: ("Al Ain", "united-arab-emirates"),
    3342: ("ES Tunis", "tunisia"),
    6356: ("Mamelodi Sundowns FC", "south-africa"),
    6603: ("Wydad Casablanca", "morocco"),
    11391: ("Auckland City", "new-zealand"),
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
    # The backbone used two English labels for Cape Verde in different
    # seasons.  They describe the same association and the same clubs, so the
    # histories must be joined before any rating is calculated.
    "Academica Do Mindelo (Cabo Verde)": "Academica Do Mindelo (Cape Verde Islands)",
    "Associacao Academica Do Porto Novo (Cabo Verde)": "Associacao Academica Do Porto Novo (Cape Verde Islands)",
    "Associacao Academica E Operaria (Cabo Verde)": "Associacao Academica E Operaria (Cape Verde Islands)",
    "Barreirense (Cabo Verde)": "Barreirense (Cape Verde Islands)",
    "Cs Mindelense (Cabo Verde)": "CS Mindelense (Cape Verde Islands)",
    "Fc Ultramarina (Cabo Verde)": "FC Ultramarina (Cape Verde Islands)",
    "Gd Varandinha (Cabo Verde)": "Gd Varandinha (Cape Verde Islands)",
    "Palmeira (Cabo Verde)": "Palmeira (Cape Verde Islands)",
    "Rosariense Desportivo Clube (Cabo Verde)": "Rosariense Desportivo Clube (Cape Verde Islands)",
    "Sc Morabeza (Cabo Verde)": "SC Morabeza (Cape Verde Islands)",
    "Sporting Clube Da Praia (Cabo Verde)": "Sporting Clube Da Praia (Cape Verde Islands)",
    # A few continental backbone rows omitted the association even though a
    # separate, association-labelled history exists for the exact same club.
    "As Psi (Unknown)": "As Psi (Chad)",
    "Jamus (Unknown)": "Jamus (South Sudan)",
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
    ("belgium", "kaagent"): "gent",
    ("belgium", "kvcwesterlo"): "westerlo",
    ("belgium", "royalantwerpfc"): "antwerp",
    ("belgium", "sinttruidensevv"): "sinttruiden",
    ("croatia", "hnkrijeka"): "rijeka",
    ("france", "lilleosc"): "lille",
    ("france", "racingclubdelens"): "lens",
    ("france", "rcstrasbourgalsace"): "strasbourg",
    ("france", "stadebrestois29"): "brest",
    ("germany", "1fsvmainz05"): "mainz05",
    ("germany", "fcstpauli1910"): "stpauli",
    ("germany", "scwismutkarlmarxstadt"): "erzgebirgeaue",
    ("germany", "sv07elversberg"): "svelversberg",
    ("germany", "tsg1899hoffenheim"): "hoffenheim",
    ("germany", "tsghoffenheim"): "hoffenheim",
    ("germany", "vflbochum"): "bochum",
    ("greece", "paoksaloniki"): "paok",
    ("hungary", "debrecenivsc"): "debrecen",
    ("italy", "cagliaricalcio"): "cagliari",
    ("italy", "fcinternazionalemilano"): "inter",
    ("italy", "genoacfc"): "genoa",
    ("italy", "parmacalcio1913"): "parma",
    ("italy", "sslazio"): "lazio",
    ("italy", "udinesecalcio"): "udinese",
    ("italy", "veneziafc"): "venezia",
    ("netherlands", "azalkmaar"): "az",
    ("netherlands", "feyenoordrotterdam"): "feyenoord",
    ("netherlands", "nec"): "necnijmegen",
    ("netherlands", "psveindhoven"): "psv",
    ("netherlands", "telstar1963"): "sctelstar",
    ("norway", "aalesundsfotballklubb"): "aalesundsfk",
    ("norway", "idrettsklubbenstart"): "ikstart",
    ("russia", "zenitstpetersburg"): "zenit",
    ("serbia", "partizanbelgrade"): "partizan",
    ("slovakia", "mskzilina"): "zilina",
    ("spain", "athleticbilbao"): "athleticclub",
    ("spain", "rayovallecanodemadrid"): "rayovallecano",
    ("spain", "rcdespanyoldebarcelona"): "espanyol",
    ("spain", "realbetisbalompie"): "realbetis",
    ("spain", "udlaspalmas"): "laspalmas",
    ("portugal", "gdestorilpraia"): "estoril",
    ("portugal", "sportingclubedeportugal"): "sportingcp",
    ("portugal", "sportlisboaebenfica"): "benfica",
    ("saudi-arabia", "alhazemsportclub"): "alhazm",
    ("sweden", "aiksolna"): "aik",
    ("sweden", "vasterassportklubbfk"): "vaesterassk",
    ("switzerland", "grasshopperszurich"): "grasshoppers",
    ("wales", "barrytown"): "barrytownunited",
}

# Reviewed public labels.  These are presentation corrections, not identity
# merges: the source identity and stable public code remain unchanged.
PUBLIC_CLUB_NAME_CORRECTIONS = {
    ("brazil", "sepalmeiras"): "Palmeiras",
    ("congo-dr", "tpmazembe"): "TP Mazembe",
}

CLUB_ACRONYMS = {
    "ac": "AC", "afc": "AFC", "as": "AS", "ca": "CA", "cd": "CD",
    "cf": "CF", "cr": "CR", "cs": "CS", "ec": "EC", "fc": "FC",
    "fk": "FK", "if": "IF", "nk": "NK", "sc": "SC", "sk": "SK",
    "sv": "SV", "tp": "TP", "us": "US",
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

OPENFOOTBALL_2025_26 = {
    "at.1.json": ("austria", 1, "Austrian Bundesliga"),
    "at.2.json": ("austria", 2, "Austrian 2. Liga"),
    "be.1.json": ("belgium", 1, "Belgian Pro League"),
    "de.1.json": ("germany", 1, "Bundesliga"),
    "de.2.json": ("germany", 2, "2. Bundesliga"),
    "en.1.json": ("england", 1, "Premier League"),
    "en.2.json": ("england", 2, "EFL Championship"),
    "en.3.json": ("england", 3, "EFL League One"),
    "en.4.json": ("england", 4, "EFL League Two"),
    "es.1.json": ("spain", 1, "La Liga"),
    "es.2.json": ("spain", 2, "Segunda División"),
    "fr.1.json": ("france", 1, "Ligue 1"),
    "fr.2.json": ("france", 2, "Ligue 2"),
    "gr.1.json": ("greece", 1, "Super League Greece"),
    "it.1.json": ("italy", 1, "Serie A"),
    "it.2.json": ("italy", 2, "Serie B"),
    "nl.1.json": ("netherlands", 1, "Eredivisie"),
    "pt.1.json": ("portugal", 1, "Primeira Liga"),
    "sco.1.json": ("scotland", 1, "Scottish Premiership"),
    "tr.1.json": ("turkey", 1, "Süper Lig"),
}

FORMER_SOVIET_ASSOCIATIONS = {
    "armenia", "azerbaijan", "belarus", "estonia", "georgia", "kazakhstan",
    "kyrgyzstan", "latvia", "lithuania", "moldova", "russia", "tajikistan",
    "turkmenistan", "ukraine", "uzbekistan",
}
FORMER_YUGOSLAV_ASSOCIATIONS = {
    "bosnia-herzegovina", "croatia", "kosovo", "montenegro",
    "north-macedonia", "serbia", "slovenia",
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
        "antigua-and-barbuda": "Antigua and Barbuda",
        "bosnia-herzegovina": "Bosnia and Herzegovina",
        "brunei-darussalam": "Brunei",
        "american-samoa": "Eastern Samoa",
        "cabo-verde": "Cape Verde",
        "cape-verde": "Cape Verde",
        "cape-verde-islands": "Cape Verde",
        "china-pr": "China",
        "chinese-taipei": "Taiwan",
        "congo-dr": "DR Congo",
        "cote-divoire": "Ivory Coast",
        "czech-republic": "Czechia",
        "democratic-republic-of-congo": "DR Congo",
        "congo-democratic-republic": "DR Congo",
        "curacao": "Curaçao",
        "east-timor": "East Timor",
        "england": "England",
        "eswatini": "Eswatini",
        "french-guyana": "French Guiana",
        "guinea-bissau": "Guinea-Bissau",
        "hong-kong-china": "Hong Kong",
        "iran-islamic-republic": "Iran",
        "ireland-republic": "Ireland",
        "ivory-coast": "Ivory Coast",
        "korea-republic": "South Korea",
        "korea-dpr": "North Korea",
        "macao": "Macao",
        "macau": "Macao",
        "moldova-republic": "Moldova",
        "palestinian-territories": "Palestine",
        "russia": "Russia",
        "sao-tome-e-principe": "Sao Tome and Principe",
        "st-kitts-and-nevis": "Saint Kitts and Nevis",
        "st-lucia": "Saint Lucia",
        "st-vincent-and-the-grenadines": "Saint Vincent and the Grenadines",
        "syrian-arab-republic": "Syria",
        "taiwan": "Taiwan",
        "tanzania-united-republic": "Tanzania",
        "timor-leste": "East Timor",
        "turkey": "Turkey",
        "trinidad-and-tobago": "Trinidad and Tobago",
        "turks-and-caicos-islands": "Turks and Caicos Islands",
        "united-states": "United States",
        "united-states-of-america": "United States",
        "us-virgin-islands": "US Virgin Islands",
        "northern-ireland": "Northern Ireland",
        "north-macedonia": "North Macedonia",
        "viet-nam": "Vietnam",
    }
    return replacements.get(value, value.replace("-", " ").title())


def canonical_club_name(country: str, value: str) -> str:
    """Return a reviewed display label without changing club identity."""
    clean = " ".join(str(value or "").split()).strip()
    corrected = PUBLIC_CLUB_NAME_CORRECTIONS.get(
        (clean_country(country), normalise_name(clean))
    )
    if corrected:
        return corrected
    tokens = clean.split(" ")
    if tokens and tokens[0].casefold() in CLUB_ACRONYMS:
        tokens[0] = CLUB_ACRONYMS[tokens[0].casefold()]
    return " ".join(tokens)


def canonical_competition_name(value: str) -> str:
    """Use one polished public label without changing competition identity."""
    text = " ".join(str(value or "").split()).strip()
    lower = text.casefold()
    suffix = " top division"
    if lower.endswith(suffix) and lower == text:
        country = clean_country(text[:-len(suffix)])
        text = f"{display_country(country)} top division"
    exact = {
        "laliga": "La Liga",
        "fa cup": "FA Cup",
        "efl cup": "EFL Cup",
    }
    text = exact.get(text.casefold(), text)
    for source, public in (
        ("uefa", "UEFA"), ("fifa", "FIFA"), ("afc", "AFC"),
        ("caf", "CAF"), ("concacaf", "CONCACAF"), ("efl", "EFL"),
        ("ofc", "OFC"),
    ):
        text = re.sub(rf"\b{source}\b", public, text, flags=re.IGNORECASE)
    return text


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
    return FOOTBALL_CONFEDERATION_FALLBACKS.get(country, geographic)


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

    def finalise_metadata(self, nfelo_country_codes: dict[str, str]) -> None:
        """Backfill metadata after every source has populated the country map.

        A club can first appear on a row whose geographic fields are blank and
        only later share its association with a fully described club.  Doing
        this once, immediately before publication, makes import order
        irrelevant and prevents valid clubs from leaking into "Unassigned".
        """
        for club in self.clubs:
            if club.country in {"", "unknown"}:
                reviewed_country = REVIEWED_UNASSIGNED_ASSOCIATIONS.get(
                    normalise_name(club.name)
                )
                if reviewed_country:
                    club.country = reviewed_country
                    club.resolution += " · reviewed association repair"
            metadata = self.country_metadata.get(club.country, ("", ""))
            geography = club.continent or metadata[1]
            club.continent = football_confederation(club.country, geography)
            public_country = display_country(club.country)
            club.country_code = (
                nfelo_country_codes.get(public_country.casefold())
                or club.country_code
                or metadata[0]
            )
            club.name = canonical_club_name(club.country, club.name)

        # Brazil has many unrelated clubs with the same short public name.
        # Keep the nationally famous backbone label clean, but append the
        # federation code to state-scoped identities so a club list never
        # presents several indistinguishable "Flamengo" or "Nacional" rows.
        live_counts = Counter(
            (club.country, club.name)
            for club in self.clubs
            if self.identity_to_index.get(club.identity) == club.index
        )
        for club in self.clubs:
            if live_counts[(club.country, club.name)] < 2:
                continue
            state = re.match(r"^brazil(?:-state)?:([A-Z]{2}):", club.identity)
            if state:
                club.name = f"{club.name} ({state.group(1)})"


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
        self.nfelo_country_codes = self._load_nfelo_country_codes(source)
        self.tiers: dict[tuple[int, int], int] = {}
        self.tiers_by_club: dict[int, dict[int, int]] = defaultdict(dict)
        self.quality_counts: Counter[str] = Counter()

    @staticmethod
    def _load_nfelo_country_codes(source: Path) -> dict[str, str]:
        """Read the national site's canonical public name/code pairs."""
        path = source / "en.teams.tsv"
        if not path.is_file():
            return {}
        result: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = [field.strip() for field in line.split("\t")]
            if len(fields) < 2 or not fields[0] or fields[0].endswith("_loc"):
                continue
            result.setdefault(fields[1].casefold(), fields[0])
        return result

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
            SELECT ident, arg_max(display,date) display, country,
                   arg_max(country_code,date) country_code, arg_max(continent,date) continent
            FROM sides
            WHERE ident IS NOT NULL AND NOT regexp_matches(ident, '^\\s*(\\([^)]*\\))?\\s*$')
            GROUP BY ident,country ORDER BY ident,country
            """,
            [str(path), str(path)],
        ).fetchall()
        countries_by_identity: defaultdict[str, set[str]] = defaultdict(set)
        for identity, _, country, _, _ in sides:
            countries_by_identity[str(identity)].add(clean_country(str(country or "")))

        mapping: dict[tuple[str, str], int] = {}
        for identity, fallback, country, country_code, continent in sides:
            canonical_identity = BACKBONE_IDENTITY_ALIASES.get(
                str(identity), str(identity)
            )
            clean = clean_country(str(country or ""))
            registry_identity = f"backbone:{canonical_identity}"
            if len(countries_by_identity[str(identity)]) > 1:
                registry_identity += f"@{clean or 'unknown'}"
            index = self.registry.add(
                registry_identity,
                self._base_name(canonical_identity, str(fallback or "")),
                clean,
                str(country_code or ""),
                str(continent or "").title(),
                "historical backbone identity",
            )
            mapping[(str(identity), clean)] = index

        # A handful of upstream rows carry the right domestic competition and
        # display name but the country/identity of a same-named foreign club.
        # Resolve those rows against the league country only when an exact,
        # unique club already exists there.  Legitimate cross-jurisdiction
        # leagues (Welsh clubs in England, Canadian clubs in MLS, etc.) remain
        # explicitly allowed.
        exact_by_country: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
        for club in self.registry.clubs:
            exact_by_country[(club.country, normalise_name(club.name))].add(club.index)
        observed_sides = self.connection.execute(
            """
            WITH sides AS (
                SELECT home_ident ident,coalesce(home_country,'') country,
                       coalesce(competition,'') competition,level,home display
                FROM read_parquet(?)
                UNION ALL
                SELECT away_ident,coalesce(away_country,''),coalesce(competition,''),
                       level,away FROM read_parquet(?)
            )
            SELECT ident,country,competition,level,arg_max(display,display)
            FROM sides
            WHERE ident IS NOT NULL AND NOT regexp_matches(ident, '^\\s*(\\([^)]*\\))?\\s*$')
            GROUP BY ident,country,competition,level
            """,
            [str(path), str(path)],
        ).fetchall()
        side_mapping: dict[tuple[str, str, str, str], int] = {}
        for identity, raw_country, competition, level, display in observed_sides:
            source_country = clean_country(str(raw_country or ""))
            club = mapping.get((str(identity), source_country))
            if club is None:
                continue
            target_country = clean_country(str(competition or ""))
            allowed = (
                source_country == target_country
                or source_country in CROSS_BORDER_JURISDICTIONS.get(target_country, set())
                or target_country in CROSS_BORDER_JURISDICTIONS.get(source_country, set())
            )
            if (
                str(level) == "national"
                and str(competition).casefold() != "ddr"
                and target_country
                and not allowed
            ):
                candidates = exact_by_country.get(
                    (target_country, normalise_name(str(display or ""))), set()
                )
                if len(candidates) == 1:
                    corrected = next(iter(candidates))
                    if corrected != club:
                        club = corrected
                        self.quality_counts["competition_country_identity_corrections"] += 1
            side_mapping[(
                str(identity), str(raw_country or ""), str(competition or ""), str(level or "")
            )] = club
        self.connection.execute(
            """CREATE TEMP TABLE backbone_sides(
                ident VARCHAR,source_country VARCHAR,competition VARCHAR,
                level VARCHAR,club INTEGER
            )"""
        )
        self.connection.executemany(
            "INSERT INTO backbone_sides VALUES (?,?,?,?,?)",
            [(*key, club) for key, club in side_mapping.items()],
        )

        soviet = ",".join(f"'{value}'" for value in sorted(FORMER_SOVIET_ASSOCIATIONS))
        yugoslav = ",".join(f"'{value}'" for value in sorted(FORMER_YUGOSLAV_ASSOCIATIONS))
        self.connection.execute(
            f"""
            INSERT INTO raw_matches
            SELECT
                g.date,
                year(g.date),
                h.club,
                a.club,
                CAST(CASE WHEN g.full_time='P' AND g.gh<>g.ga THEN 0 ELSE g.gh END AS SMALLINT),
                CAST(CASE WHEN g.full_time='P' AND g.gh<>g.ga THEN 0 ELSE g.ga END AS SMALLINT),
                CASE
                    WHEN g.competition='Fifa Club' AND g.date >= DATE '2024-01-01'
                        THEN 'FIFA Intercontinental Cup'
                    WHEN g.level='international' THEN coalesce(n.display, g.competition)
                    WHEN lower(coalesce(g.competition,''))='ddr'
                         AND (lower(g.home_country) IN ({soviet}) OR lower(g.away_country) IN ({soviet}))
                        THEN 'Soviet Union top division'
                    WHEN lower(coalesce(g.competition,''))='ddr'
                         AND (lower(g.home_country) IN ({yugoslav}) OR lower(g.away_country) IN ({yugoslav}))
                        THEN 'Yugoslavia top division'
                    WHEN lower(coalesce(g.competition,''))='ddr'
                        THEN 'East Germany top division'
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
                        WHEN g.competition='Fifa Club' AND g.date >= DATE '2024-01-01'
                            THEN 'Fifa Intercontinental'
                        WHEN lower(coalesce(g.competition,''))='ddr'
                             AND (lower(g.home_country) IN ({soviet}) OR lower(g.away_country) IN ({soviet}))
                            THEN 'soviet-union'
                        WHEN lower(coalesce(g.competition,''))='ddr'
                             AND (lower(g.home_country) IN ({yugoslav}) OR lower(g.away_country) IN ({yugoslav}))
                            THEN 'yugoslavia'
                        WHEN lower(coalesce(g.competition,''))='ddr'
                            THEN 'east-germany'
                        ELSE g.competition
                    END
                ),
                CASE
                    WHEN g.level='national' THEN 'league'
                    WHEN g.competition='Fifa Club' AND g.date >= DATE '2024-01-01'
                        THEN 'intercontinental'
                    WHEN g.competition='Fifa Club' THEN 'global'
                    WHEN g.competition IN ('UEFA SC','CAF SC','Recopa') THEN 'super_cup'
                    ELSE 'continental'
                END,
                1,1,coalesce(g.competition='Fifa Club',false),g.level='international',
                CASE WHEN g.full_time='P' AND g.gh<>g.ga THEN 'P?' ELSE coalesce(g.full_time,'F') END,
                0,NULL,
                CASE WHEN g.full_time='P' AND g.gh<>g.ga
                     THEN 'Football score unavailable; source total included shootout kicks'
                     ELSE '' END,
                'schochastics',concat('games.parquet:',cast(g.date as varchar)),10
            FROM read_parquet(?) g
            JOIN backbone_sides h
              ON h.ident=g.home_ident AND h.source_country=coalesce(g.home_country,'')
             AND h.competition=coalesce(g.competition,'') AND h.level=g.level
            JOIN backbone_sides a
              ON a.ident=g.away_ident AND a.source_country=coalesce(g.away_country,'')
             AND a.competition=coalesce(g.competition,'') AND a.level=g.level
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
        self.quality_counts["shootout_totals_removed"] += int(
            self.connection.execute(
                "SELECT count(*) FROM raw_matches WHERE source='schochastics' AND status='P?'"
            ).fetchone()[0]
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

    @staticmethod
    def _openfootball_score(value: Any) -> tuple[int, int] | None:
        score = value
        if isinstance(score, dict):
            score = score.get("ft") or score.get("et")
        if not isinstance(score, list) or len(score) != 2:
            return None
        home, away = integer(score[0]), integer(score[1])
        if home is None or away is None:
            return None
        return home, away

    def load_openfootball(self) -> int:
        """Load the complete 2025/26 league files that repair current tiers."""
        directory = self.cache / "openfootball" / "2025-26"
        prepared: list[tuple[Any, ...]] = []
        for filename, (country, tier, competition) in OPENFOOTBALL_2025_26.items():
            path = directory / filename
            payload = json.loads(path.read_text(encoding="utf-8"))
            matches = payload.get("matches")
            if not isinstance(matches, list):
                raise ValueError(f"OpenFootball {filename} has no match list")
            for item in matches:
                if not isinstance(item, dict):
                    continue
                day = safe_date(item.get("date"))
                score = self._openfootball_score(item.get("score"))
                home_name = str(item.get("team1") or "").strip()
                away_name = str(item.get("team2") or "").strip()
                if day is None or score is None or not home_name or not away_name:
                    continue
                home = self.registry.resolve(
                    home_name,
                    country,
                    create_identity=f"openfootball:{country}:{normalise_name(home_name)}",
                    resolution="OpenFootball current-season identity",
                )
                away = self.registry.resolve(
                    away_name,
                    country,
                    create_identity=f"openfootball:{country}:{normalise_name(away_name)}",
                    resolution="OpenFootball current-season identity",
                )
                assert home is not None and away is not None
                self._remember_tier(home, 2025, tier)
                self._remember_tier(away, 2025, tier)
                prepared.append((
                    day, 2025, home, away, score[0], score[1], competition,
                    f"openfootball:2025-26:{filename[:-5]}", "league", tier, tier,
                    False, False, "F", 0, None, str(item.get("round") or ""),
                    "openfootball", f"football.json:2025-26/{filename}", 30,
                ))
        return self._insert(prepared)

    def load_reviewed_matches(self) -> int:
        """Load small, source-linked corrections that bridge feed cut-off gaps."""
        path = self.source / "club_reviewed_matches.json"
        if not path.is_file():
            return 0
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("club_reviewed_matches.json must contain a list")
        prepared: list[tuple[Any, ...]] = []
        for position, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"reviewed match {position} is not an object")
            day = safe_date(item.get("date"))
            home_goals = integer(item.get("home_goals"))
            away_goals = integer(item.get("away_goals"))
            if day is None or home_goals is None or away_goals is None:
                raise ValueError(f"reviewed match {position} has an invalid date or score")
            home_country = clean_country(str(item.get("home_country") or ""))
            away_country = clean_country(str(item.get("away_country") or ""))
            home_name = str(item.get("home") or "").strip()
            away_name = str(item.get("away") or "").strip()
            home = self.registry.resolve(home_name, home_country, allow_fuzzy=False)
            away = self.registry.resolve(away_name, away_country, allow_fuzzy=False)
            if home is None or away is None:
                raise ValueError(
                    f"reviewed match {position} cannot resolve {home_name} v {away_name}"
                )
            home_tier = int(item.get("home_tier", self.infer_tier(home, int(day[:4]), 1)))
            away_tier = int(item.get("away_tier", self.infer_tier(away, int(day[:4]), 1)))
            prepared.append((
                day, int(item.get("season", int(day[:4]))), home, away,
                home_goals, away_goals, str(item["competition"]),
                str(item["competition_key"]), str(item["kind"]),
                home_tier, away_tier, bool(item.get("neutral", False)),
                bool(item.get("cross_border", True)), str(item.get("status", "F")),
                int(item.get("leg", 0)), item.get("tie_key"),
                str(item.get("round") or ""), "nfelo-reviewed",
                str(item["source_ref"]), 100,
            ))
        return self._insert(prepared)

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
        raw_leg = str(row.get("leg") or row.get("tie") or "")
        leg = integer(raw_leg, 0) or 0
        if leg not in {1, 2}:
            leg_match = re.search(r"\bleg\s*([12])\b", raw_leg.casefold())
            leg = int(leg_match.group(1)) if leg_match else 0
        if leg not in {1, 2}:
            leg = 0
        penalties_text = str(row.get("pens") or "").strip()
        penalties_declared = self._yes(row.get("pen")) or bool(
            re.search(r"\d+\s*[-–:]\s*\d+", penalties_text)
        )
        extra_time_text = str(row.get("aet") or "").strip()
        extra_time_declared = self._yes(extra_time_text) or bool(
            re.fullmatch(r"\d+\s*[-–:]\s*\d+", extra_time_text)
        )
        if penalties_declared and home_goals == away_goals:
            status = "P"
        elif penalties_declared and leg == 2:
            # The shootout decided the aggregate tie, not this individual
            # match.  Preserve its football score as an extra-time/full-time
            # result instead of falsely learning it as a match draw.
            status = "E" if extra_time_declared else "F"
            self.quality_counts["aggregate_shootouts_reclassified"] += 1
        elif penalties_declared:
            # A one-off shootout requires a level football score.  If a source
            # exposes only an unequal total, do not publish those kicks as
            # goals and do not invent the missing score.
            home_goals = away_goals = 0
            status = "P?"
            self.quality_counts["shootout_totals_removed"] += 1
        else:
            status = "E" if extra_time_declared else "F"
        round_name = str(row.get("round") or row.get("division") or "")
        if penalties_declared and leg == 2:
            round_name = f"{round_name} · aggregate tie decided on penalties".strip()
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
                "OpenFootball current-season identity",
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
        game_side_names: dict[int, str] = {}
        for row in games:
            for id_field, name_field in (
                ("home_club_id", "home_club_name"),
                ("away_club_id", "away_club_name"),
            ):
                tm_id = integer(row.get(id_field))
                name = str(row.get(name_field) or "").strip()
                if tm_id is not None and name:
                    game_side_names.setdefault(tm_id, name)

        # Transfermarkt's published game total sometimes adds successful
        # shootout kicks to the football score (for example, Liverpool 1-1
        # Manchester City in the 2019 Community Shield appears as 5-6).  The
        # event feed identifies shootout kicks separately, so rebuild the
        # regulation/extra-time score from ordinary goal events and mark the
        # decision as penalties before identity matching or modelling.
        events_path = directory / "game_events.csv.gz"
        shootout_games: set[int] = set()
        with gzip.open(events_path, "rt", encoding="utf-8-sig", newline="") as handle:
            for event in csv.DictReader(handle):
                if str(event.get("type") or "") == "Shootout":
                    game_id = integer(event.get("game_id"))
                    if game_id is not None:
                        shootout_games.add(game_id)
        shootout_goals: defaultdict[int, Counter[int]] = defaultdict(Counter)
        with gzip.open(events_path, "rt", encoding="utf-8-sig", newline="") as handle:
            for event in csv.DictReader(handle):
                game_id = integer(event.get("game_id"))
                if game_id not in shootout_games or str(event.get("type") or "") != "Goals":
                    continue
                club_id = integer(event.get("club_id"))
                if club_id is not None:
                    shootout_goals[int(game_id)][club_id] += 1
        corrected_shootouts = 0
        for row in games:
            game_id = integer(row.get("game_id"))
            row["_nfelo_status"] = "F"
            if game_id not in shootout_games:
                continue
            home_id = integer(row.get("home_club_id"))
            away_id = integer(row.get("away_club_id"))
            if home_id is None or away_id is None:
                continue
            row["home_club_goals"] = str(shootout_goals[int(game_id)][home_id])
            row["away_club_goals"] = str(shootout_goals[int(game_id)][away_id])
            row["_nfelo_status"] = "P"
            corrected_shootouts += 1

        def transfermarkt_country(
            competition_id: str,
            competition: dict[str, str],
        ) -> str:
            fallback = TRANSFERMARKT_FALLBACK_COMPETITIONS.get(competition_id)
            return clean_country(
                competition.get("country_name")
                or (fallback[2] if fallback else "")
            )

        mapping: dict[int, int] = {}
        unresolved: set[int] = set()
        for tm_id, row in club_rows.items():
            competition_id = str(row.get("domestic_competition_id") or "")
            competition = competitions.get(competition_id, {})
            country = transfermarkt_country(competition_id, competition)
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
            competition = competitions.get(
                str(club_rows[tm_id].get("domestic_competition_id") or ""), {}
            )
            competition_id = str(
                club_rows[tm_id].get("domestic_competition_id") or ""
            )
            expected_country = transfermarkt_country(
                competition_id, competition
            )
            # A score/date fingerprint is only identifying inside the same
            # association.  Without this guard, a sparse international-only
            # side can be mistaken for its opponent after sharing fixtures.
            same_association = bool(expected_country) and (
                self.registry.clubs[best_club].country == expected_country
            )
            if (
                same_association
                and best >= 4
                and best >= runner + 3
                and best >= totals[tm_id] * 0.04
            ):
                mapping[tm_id] = best_club
                unresolved.remove(tm_id)
                fingerprint_matches += 1

        for tm_id in sorted(unresolved):
            row = club_rows[tm_id]
            competition_id = str(row.get("domestic_competition_id") or "")
            competition = competitions.get(competition_id, {})
            country = transfermarkt_country(competition_id, competition)
            resolved = self.registry.resolve(
                str(row.get("name") or f"Club {tm_id}"), country,
                create_identity=f"transfermarkt:{tm_id}",
                resolution="Transfermarkt source identity",
            )
            assert resolved is not None
            mapping[tm_id] = resolved

        game_only_matches = 0
        for tm_id, source_name in sorted(game_side_names.items()):
            if tm_id in mapping:
                continue
            fallback = TRANSFERMARKT_GAME_ONLY_CLUB_FALLBACKS.get(tm_id)
            if fallback:
                canonical_name, country = fallback
                resolved = self.registry.resolve(
                    canonical_name,
                    country,
                    allow_fuzzy=False,
                    create_identity=f"transfermarkt:{tm_id}",
                    resolution="reviewed Transfermarkt game-only identity",
                )
            else:
                # Country-free matching is accepted only when the complete or
                # football-search label identifies one existing club globally.
                resolved = self.registry.resolve(
                    source_name, "", allow_fuzzy=False
                )
            if resolved is not None:
                mapping[tm_id] = resolved
                game_only_matches += 1

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
            # Several game IDs are published before their catalog rows.  The
            # reviewed fallback is authoritative for those known gaps; KLUB in
            # particular must reach the inter-confederation bridge.
            override = TRANSFERMARKT_FALLBACK_COMPETITIONS.get(comp_id)
            if override:
                kind = override[1]
            elif comp_type == "domestic_league":
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
            display = (
                override[0]
                if override
                else str(comp.get("name") or comp.get("competition_code") or comp_id)
            )
            if not override:
                display = " ".join(display.replace("-", " ").split()).title()
            neutral = kind == "global" or (
                leg == 0
                and round_name.strip().casefold() == "final"
                and kind in {"domestic_cup", "continental", "intercontinental"}
            )
            cross_border = not bool(comp.get("country_name")) and kind in {
                "continental", "intercontinental", "global", "super_cup"
            }
            status = str(row.get("_nfelo_status") or "F")
            if status.startswith("P") and home_goals != away_goals:
                if leg == 2:
                    # The event feed gives the match's football score; the
                    # subsequent shootout decided only the aggregate tie.
                    status = "E"
                    round_name += " · aggregate tie decided on penalties"
                    self.quality_counts["aggregate_shootouts_reclassified"] += 1
                else:
                    home_goals = away_goals = 0
                    status = "P?"
                    self.quality_counts["shootout_totals_removed"] += 1
            prepared.append((
                day, season, home, away, home_goals, away_goals, display,
                f"tm:{comp_id}", kind, home_tier, away_tier, neutral,
                cross_border, status, leg,
                tie_key, round_name, "transfermarkt",
                f"games.csv.gz:{row.get('game_id','')}", 20,
            ))
        print(
            f"Transfermarkt identity resolution: {len(mapping) - len(unresolved)} linked; "
            f"{fingerprint_matches} by fixture fingerprint; {len(unresolved)} source identities; "
            f"{game_only_matches} game-only identities; "
            f"{corrected_shootouts} shootout scores separated"
        )
        return self._insert(prepared)

    def finalise(self) -> dict[str, Any]:
        self.registry.finalise_metadata(self.nfelo_country_codes)
        placeholder_clubs = [
            club.index for club in self.registry.clubs
            if normalise_name(club.name) in PLACEHOLDER_CLUB_IDENTIFIERS
        ]
        if placeholder_clubs:
            self.connection.execute(
                "CREATE TEMP TABLE placeholder_clubs(club INTEGER PRIMARY KEY)"
            )
            self.connection.executemany(
                "INSERT INTO placeholder_clubs VALUES (?)",
                [(club,) for club in placeholder_clubs],
            )
            placeholder_rows = int(self.connection.execute(
                """SELECT count(*) FROM raw_matches
                   WHERE home IN (SELECT club FROM placeholder_clubs)
                      OR away IN (SELECT club FROM placeholder_clubs)"""
            ).fetchone()[0])
            self.connection.execute(
                """DELETE FROM raw_matches
                   WHERE home IN (SELECT club FROM placeholder_clubs)
                      OR away IN (SELECT club FROM placeholder_clubs)"""
            )
            self.quality_counts["placeholder_rows_removed"] += placeholder_rows
        collapsed_self_matches = int(
            self.connection.execute(
                "SELECT count(*) FROM raw_matches WHERE home=away"
            ).fetchone()[0]
        )
        if collapsed_self_matches:
            # Redirects are deliberately conservative, but a same-name source
            # collision can still collapse both sides after import.  Such a
            # row contains no usable sporting signal and is withheld rather
            # than allowed to update one club against itself.
            self.connection.execute("DELETE FROM raw_matches WHERE home=away")
            self.quality_counts[
                "collapsed_self_matches_removed"
            ] += collapsed_self_matches
        competition_labels = [
            (str(raw), canonical_competition_name(str(raw)))
            for (raw,) in self.connection.execute(
                "SELECT DISTINCT competition FROM raw_matches"
            ).fetchall()
        ]
        changed_labels = [row for row in competition_labels if row[0] != row[1]]
        if changed_labels:
            self.connection.execute(
                "CREATE TEMP TABLE public_competition_names(raw VARCHAR,display VARCHAR)"
            )
            self.connection.executemany(
                "INSERT INTO public_competition_names VALUES (?,?)", changed_labels
            )
            changed_rows = int(
                self.connection.execute(
                    "SELECT count(*) FROM raw_matches r "
                    "JOIN public_competition_names n ON n.raw=r.competition"
                ).fetchone()[0]
            )
            self.connection.execute(
                "UPDATE raw_matches SET competition=n.display "
                "FROM public_competition_names n "
                "WHERE raw_matches.competition=n.raw"
            )
            self.quality_counts["competition_labels_standardised"] += changed_rows
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
        checks = [
            (
                "distinct match identities",
                int(self.connection.execute(
                    "SELECT count(*)-count(distinct match_id) FROM matches"
                ).fetchone()[0]),
                0,
                "No retained match ID may repeat.",
            ),
            (
                "club cannot play itself",
                int(self.connection.execute(
                    "SELECT count(*) FROM matches WHERE home=away"
                ).fetchone()[0]),
                0,
                "Identity reconciliation must not collapse opponents.",
            ),
            (
                "retained clubs have association and confederation",
                int(self.connection.execute(
                    """SELECT count(DISTINCT club) FROM (
                           SELECT home club FROM matches
                           UNION ALL SELECT away FROM matches
                       ) sides JOIN clubs USING(club)
                       WHERE country IN ('','unknown')
                          OR country_name IN ('Unassigned','Unknown')
                          OR continent=''"""
                ).fetchone()[0]),
                0,
                "Every retained club side must have a reviewed association and football confederation.",
            ),
            (
                "shootout kicks excluded from football score",
                int(self.connection.execute(
                    "SELECT count(*) FROM matches WHERE status LIKE 'P%' AND home_goals<>away_goals"
                ).fetchone()[0]),
                0,
                "A penalty decision must enter the model as a draw.",
            ),
            (
                "Santa Clara association collision",
                int(self.connection.execute(
                    """SELECT count(*) FROM matches m
                       JOIN clubs h ON h.club=m.home JOIN clubs a ON a.club=m.away
                       WHERE lower(m.competition) LIKE 'portugal%'
                         AND ((h.name='Santa Clara' AND h.country='el-salvador')
                           OR (a.name='Santa Clara' AND a.country='el-salvador'))"""
                ).fetchone()[0]),
                0,
                "Portugal fixtures must resolve to Portugal's Santa Clara.",
            ),
            (
                "ambiguous DDR competition label",
                int(self.connection.execute(
                    "SELECT count(*) FROM matches WHERE lower(competition)='ddr top division'"
                ).fetchone()[0]),
                0,
                "East Germany, the Soviet Union and Yugoslavia are separate competitions.",
            ),
            (
                "2026 Champions League final",
                int(self.connection.execute(
                    """SELECT count(*) FROM matches
                       WHERE day=DATE '2026-05-30'
                         AND competition='UEFA Champions League'
                         AND home_goals=1 AND away_goals=1
                         AND status='P' AND neutral"""
                ).fetchone()[0]),
                1,
                "Paris Saint-Germain 1-1 Arsenal, Paris 4-3 on penalties.",
            ),
        ]
        failed = [name for name, actual, expected, _ in checks if actual != expected]
        if failed:
            raise RuntimeError("club ledger quality checks failed: " + ", ".join(failed))
        self.connection.execute(
            """CREATE TABLE data_quality_checks(
                check_name VARCHAR,actual BIGINT,expected BIGINT,passed BOOLEAN,note VARCHAR
            )"""
        )
        self.connection.executemany(
            "INSERT INTO data_quality_checks VALUES (?,?,?,?,?)",
            [(name, actual, expected, actual == expected, note)
             for name, actual, expected, note in checks],
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
            "quality": dict(self.quality_counts),
        }

    def build(self) -> dict[str, Any]:
        inserted: dict[str, int] = {}
        inserted["schochastics"] = self.load_backbone()
        print(f"club ledger: loaded {inserted['schochastics']:,} schochastics candidate matches")
        inserted["engsoccerdata"] = self.load_deep_sources()
        print(f"club ledger: loaded {inserted['engsoccerdata']:,} engsoccerdata candidate matches")
        self.reconcile_source_identities("engsoccerdata")
        inserted["openfootball"] = self.load_openfootball()
        print(f"club ledger: loaded {inserted['openfootball']:,} OpenFootball candidate matches")
        self.reconcile_source_identities("openfootball")
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
        inserted["nfelo-reviewed"] = self.load_reviewed_matches()
        print(f"club ledger: loaded {inserted['nfelo-reviewed']:,} reviewed candidate matches")
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
        required = {
            "raw_matches", "matches", "clubs", "competition_coverage",
            "data_quality_checks",
        }
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
