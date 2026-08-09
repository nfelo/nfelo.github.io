#!/usr/bin/env python3
"""Revision-pinned tournament-format facts for causal title simulations.

The public site never downloads or interprets Wikipedia in a browser.  This
importer runs in CI, pins the last safely pre-opening revision, reduces the
published format to a small validated rule graph, and writes only those facts
and their provenance to ``source/tournament_odds/manifest.json``.

The model and result ledger remain immutable inputs.  A format that cannot be
proved from a pre-opening revision fails closed: the public title chance is an
em dash rather than a hindsight-contaminated estimate.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import re
from pathlib import Path
import random
import sys
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from ledger import Match, read_dictionary, read_matches, read_successors


SCHEMA = 1
FACTS_VERSION = 4
LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"


class FormatUnavailable(RuntimeError):
    """A tournament format cannot be established without hindsight."""


INFERRED_PROFILE = "universal-structural-inference-v3"
INFERRED_TRIALS = 10_000


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json_if_changed(path: Path, value: Any) -> bool:
    text = canonical_json(value) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def load_configuration(path: Path) -> dict[str, Any]:
    configuration = json.loads(path.read_text(encoding="utf-8"))
    if int(configuration.get("schema", -1)) != SCHEMA:
        raise ValueError("Unsupported tournament-odds configuration schema")
    if int(configuration.get("trials", 0)) < 10_000:
        raise ValueError("Tournament simulations require at least 10,000 trials")
    profile_ids: set[str] = set()
    source_codes: set[str] = set()
    for profile in configuration.get("profiles", []):
        profile_id = str(profile["id"])
        if profile_id in profile_ids:
            raise ValueError(f"Duplicate tournament profile: {profile_id}")
        profile_ids.add(profile_id)
        overlap = source_codes.intersection(profile["source_codes"])
        if overlap:
            raise ValueError(f"Tournament source codes assigned twice: {sorted(overlap)}")
        source_codes.update(str(code).upper() for code in profile["source_codes"])
        group_matches = int(profile["group_matches"])
        teams = int(profile["teams"])
        groups = int(profile["group_count"])
        if teams < 4 or groups < 1 or group_matches < teams:
            raise ValueError(f"Invalid group format in {profile_id}")
        advancing = groups * int(profile["advance_per_group"]) + int(profile["best_third"])
        if advancing != int(profile["knockout_teams"]):
            raise ValueError(f"Knockout field does not match group advancement in {profile_id}")
        if str(profile["knockout"]) not in {
            "revision_graph",
            "two_leg_graph",
            "standard-neutral",
            "two-leg-standard",
        }:
            raise ValueError(f"Unsupported knockout format in {profile_id}")
    return configuration


def strip_comments_positioned(text: str) -> str:
    """Remove comments without changing offsets or Unicode string length."""
    return re.sub(
        r"<!--[\s\S]*?-->",
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)),
        text,
    )


def folded(value: str) -> str:
    value = html.unescape(value).replace("&nbsp;", " ")
    value = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\{\{[^{}]*\}\}", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", value).strip()


def split_top_level(value: str, separator: str = "|") -> list[str]:
    parts: list[str] = []
    start = 0
    braces = brackets = 0
    index = 0
    while index < len(value):
        pair = value[index:index + 2]
        if pair == "{{":
            braces += 1
            index += 2
            continue
        if pair == "}}" and braces:
            braces -= 1
            index += 2
            continue
        if pair == "[[":
            brackets += 1
            index += 2
            continue
        if pair == "]]" and brackets:
            brackets -= 1
            index += 2
            continue
        if value[index] == separator and braces == 0 and brackets == 0:
            parts.append(value[start:index])
            start = index + 1
        index += 1
    parts.append(value[start:])
    return parts


def balanced_templates(text: str) -> Iterable[tuple[int, str]]:
    """Yield outer templates while respecting nested templates."""
    clean = strip_comments_positioned(text)
    stack: list[int] = []
    index = 0
    while index + 1 < len(clean):
        pair = clean[index:index + 2]
        if pair == "{{":
            stack.append(index)
            index += 2
            continue
        if pair == "}}" and stack:
            start = stack.pop()
            if not stack:
                yield start, clean[start:index + 2]
            index += 2
            continue
        index += 1


def nested_templates(text: str) -> Iterable[tuple[int, str]]:
    """Yield every balanced template, including nested football boxes."""
    clean = strip_comments_positioned(text)
    stack: list[int] = []
    index = 0
    while index + 1 < len(clean):
        pair = clean[index:index + 2]
        if pair == "{{":
            stack.append(index)
            index += 2
            continue
        if pair == "}}" and stack:
            start = stack.pop()
            yield start, clean[start:index + 2]
            index += 2
            continue
        index += 1


def template_fields(block: str) -> tuple[str, dict[str, str]]:
    body = block[2:-2]
    parts = split_top_level(body)
    name = re.sub(r"\s+", " ", parts[0]).strip().casefold()
    fields: dict[str, str] = {}
    positional = 1
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            fields[re.sub(r"\s+", " ", key).strip().casefold()] = value.strip()
        else:
            fields[str(positional)] = part.strip()
            positional += 1
    return name, fields


def parse_date(value: str) -> str | None:
    match = re.search(
        r"(?i)\{\{\s*(?:start date|dts|date)\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})",
        value,
    )
    if not match:
        match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", value)
    if not match:
        return None
    year, month, day = (int(item) for item in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def normalise_entrant(value: str) -> str:
    value = strip_comments_positioned(value)
    value = re.sub(r"(?is)<ref\b.*?</ref\s*>", " ", value)
    value = re.sub(r"(?is)<ref\b[^>]*/\s*>", " ", value)
    previous = None
    while previous != value:
        previous = value
        value = re.sub(
            r"(?is)\{\{(?:flagicon|fb|fb-rt|flag|nowrap|small)\b[^{}]*\}\}",
            " ",
            value,
        )
    return folded(value)


def parse_match_id(score: str, prefix: str) -> int | None:
    # A score-link anchor can contain both entrants ("Winner Match 73")
    # before its own label ("Match 90"). The final occurrence is the box's
    # match number; taking the first silently folds later rounds onto R32 IDs.
    score_matches = re.findall(r"(?i)\bmatch\s*(\d{1,3})\b", score)
    if score_matches:
        return int(score_matches[-1])
    prefix_matches = re.findall(r"(?i)\bmatch\s*(\d{1,3})\b", prefix)
    if prefix_matches:
        return int(prefix_matches[-1])
    return None


def parse_football_boxes(title: str, text: str) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    clean = strip_comments_positioned(text)
    page_final_date: str | None = None
    if "final" in title.casefold():
        for match in re.finditer(r"(?im)^\|\s*date\s*=\s*(.+)$", clean):
            page_final_date = parse_date(match.group(1))
            if page_final_date:
                break
    for offset, block in nested_templates(clean):
        name, fields = template_fields(block)
        if not (
            name == "football box"
            or name.startswith("#invoke:football box|")
            or (name == "#invoke:football box" and fields.get("1", "").casefold() == "main")
        ):
            continue
        team1 = normalise_entrant(fields.get("team1", ""))
        team2 = normalise_entrant(fields.get("team2", ""))
        if not team1 or not team2:
            continue
        prefix = clean[max(0, offset - 160):offset]
        match_id = parse_match_id(fields.get("score", ""), prefix)
        section_matches = re.findall(
            r"(?i)<section\s+begin\s*=\s*[\"']?([^\s/>\"']+)",
            prefix,
        )
        boxes.append({
            "match": match_id,
            "section_id": section_matches[-1] if section_matches else None,
            "date": parse_date(fields.get("date", "")) or page_final_date,
            "team1": team1,
            "team2": team2,
            "box_id": normalise_entrant(fields.get("id", "")),
            "venue_text": folded(
                fields.get("stadium", "")
                or fields.get("venue", "")
                or fields.get("city", "")
            ),
            "title": title,
            "section": folded(prefix[-120:]),
        })
    # Nested scanner also yields the complete outer invocation around a box on
    # a few pages. Identity-deduplicate without collapsing legitimate fixtures.
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for box in boxes:
        key = (
            box["match"], box["section_id"], box["date"],
            box["team1"], box["team2"], box["section"],
        )
        if key not in unique:
            unique[key] = box
        elif not unique[key].get("venue_text") and box.get("venue_text"):
            unique[key]["venue_text"] = box["venue_text"]
    return list(unique.values())


def referenced_titles(text: str) -> set[str]:
    titles: set[str] = set()
    clean = strip_comments_positioned(text)
    patterns = (
        r"(?is)\{\{\s*#lst\s*:\s*([^|{}]+)",
        r"(?is)\{\{\s*(?:main|main article)\s*\|\s*([^|{}]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, clean):
            title = folded(match.group(1)).replace("_", " ").strip()
            if title:
                titles.add(title)
    for match in re.finditer(r"(?is)\{\{\s*([^|{}]*third-place table[^|{}]*)", clean):
        title = "Template:" + folded(match.group(1)).strip()
        if title != "Template:":
            titles.add(title)
    return titles


def parse_third_place_tables(texts: Iterable[str], group_count: int) -> dict[str, dict[str, str]]:
    """Parse UEFA/FIFA third-place allocation tables from pinned wikitext."""
    result: dict[str, dict[str, str]] = {}
    for text in texts:
        for table_match in re.finditer(r"(?is)\{\|.*?\n\|\}", text):
            table = table_match.group(0)
            if "third" not in table.casefold() or not re.search(r"\b3[A-Z]\b", table):
                continue
            headers = re.findall(
                r"(?i)!.*?\b1([A-Z])\b\s*<br\s*/?>\s*vs",
                table,
            )
            if not headers:
                continue
            for row in re.split(r"(?m)^\|-[^\n]*$", table)[1:]:
                cells: list[str] = []
                for line in row.splitlines():
                    if not line.startswith("|") or line.startswith(("|-", "|}")):
                        continue
                    body = line[1:]
                    cells.extend(body.split("||"))
                qualified = re.findall(r"'''\s*([A-Z])\s*'''", " ".join(cells[:group_count + 2]))
                mappings = [
                    match.group(1)
                    for cell in cells[-len(headers):]
                    if (match := re.search(r"\b3([A-Z])\b", cell))
                ]
                qualified = list(dict.fromkeys(qualified))
                if len(mappings) != len(headers):
                    continue
                key = "".join(sorted(set(qualified)))
                if not key:
                    # Some tables omit bold markup; the twelve/six inclusion
                    # columns still contain lone group letters.
                    inclusion = cells[:group_count]
                    key = "".join(sorted({
                        match.group(1)
                        for cell in inclusion
                        if (match := re.fullmatch(r"\s*(?:'''\s*)?([A-Z])(?:\s*''')?\s*", cell))
                    }))
                if key and len(key) == len(headers):
                    result[key] = dict(zip(headers, mappings))
    return result


def entrant_kind(value: str) -> tuple[str, str] | None:
    compact = re.sub(r"\s+", " ", value).strip()
    patterns = (
        (r"(?i)^winner(?:\s+of)?\s+group\s+([A-Z])$", "group1"),
        (r"(?i)^(?:runner-up|second(?:-placed)?)(?:\s+of)?\s+group\s+([A-Z])$", "group2"),
        (r"(?i)^(?:third(?:-placed)?|3rd)(?:\s+of)?\s+group\s+([A-Z])$", "group3"),
        (r"(?i)^winner(?:\s+of)?\s+match\s+(\d+)$", "winner"),
        (r"(?i)^loser(?:\s+of)?\s+match\s+(\d+)$", "loser"),
        (r"(?i)^winner(?:\s+of)?\s+semi[- ]final\s+(\d+)$", "winner"),
        (r"(?i)^loser(?:\s+of)?\s+semi[- ]final\s+(\d+)$", "loser"),
        (r"(?i)^winner(?:\s+of)?\s+([A-Z][A-Z0-9-]*)$", "winner"),
        (r"(?i)^loser(?:\s+of)?\s+([A-Z][A-Z0-9-]*)$", "loser"),
    )
    for pattern, kind in patterns:
        match = re.match(pattern, compact)
        if match:
            value = match.group(1).upper()
            if "semi" in pattern:
                value = f"SF{value}"
            return kind, value
    third = re.match(
        r"(?i)^(?:third(?:-place(?:d)?)?|3rd)\s+group\s+([A-Z](?:/[A-Z])+)\b",
        compact,
    )
    if third:
        return "third-options", third.group(1).upper()
    return None


def normalise_knockout_graph(
    boxes: list[dict[str, Any]],
    group_matches: int,
    knockout_teams: int,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    inferred_round = inferred_quarter = inferred_semi = 0
    for offset, box in enumerate(boxes):
        match_id = box.get("match")
        first = entrant_kind(str(box.get("team1", "")))
        second = entrant_kind(str(box.get("team2", "")))
        if first is None or second is None:
            continue
        if match_id is not None and match_id <= group_matches:
            continue
        section_id = str(box.get("section_id") or "")
        if section_id.upper() in {"R16", "QF", "SF"}:
            section_id = ""
        node_id = str(match_id) if match_id is not None else section_id
        if not node_id:
            if first[0] == second[0] == "loser":
                node_id = "THIRD"
            elif first[0] == second[0] == "winner" and all(
                re.fullmatch(r"(?i)SF\d+", value) for _, value in (first, second)
            ):
                node_id = "FINAL"
            elif first[0] == second[0] == "winner" and all(
                re.fullmatch(r"(?i)QF\d+", value) for _, value in (first, second)
            ):
                inferred_semi += 1
                node_id = f"SF{inferred_semi}"
            elif first[0] == second[0] == "winner" and all(
                re.fullmatch(r"(?i)R\d+", value) for _, value in (first, second)
            ):
                inferred_quarter += 1
                node_id = f"QF{inferred_quarter}"
            elif first[0].startswith("group") or second[0].startswith("group") or "third-options" in {first[0], second[0]}:
                inferred_round += 1
                node_id = (
                    f"SF{inferred_round}"
                    if knockout_teams == 4
                    else f"R{inferred_round}"
                )
            else:
                node_id = f"AUTO-{offset + 1}"
        nodes.append({
            "id": node_id,
            "match": None if match_id is None else int(match_id),
            "date": box.get("date"),
            "team1": [first[0], first[1]],
            "team2": [second[0], second[1]],
            "venue_text": str(box.get("venue_text") or ""),
        })
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        old = by_id.get(node["id"])
        if old and (old["team1"], old["team2"]) != (node["team1"], node["team2"]):
            same_pair = {
                tuple(old["team1"]), tuple(old["team2"]),
            } == {
                tuple(node["team1"]), tuple(node["team2"]),
            }
            if not same_pair:
                raise FormatUnavailable(f"Conflicting pinned knockout node {node['id']}")
        if old is None:
            by_id[node["id"]] = node
        else:
            if not old.get("date") and node.get("date"):
                old["date"] = node["date"]
            if not old.get("venue_text") and node.get("venue_text"):
                old["venue_text"] = node["venue_text"]
    nodes = list(by_id.values())
    aliases: dict[str, str] = {}
    for node in nodes:
        node_id = str(node["id"])
        round_match = re.fullmatch(r"R16-M(\d+)", node_id, flags=re.IGNORECASE)
        if round_match:
            aliases[f"R{round_match.group(1)}"] = node_id
        quarter = re.fullmatch(r"QF([A-Z])", node_id, flags=re.IGNORECASE)
        if quarter:
            aliases[f"QF{ord(quarter.group(1).upper()) - ord('A') + 1}"] = node_id
    for node in nodes:
        for side in ("team1", "team2"):
            kind, value = node[side]
            if kind in {"winner", "loser"} and str(value) in aliases:
                node[side][1] = aliases[str(value)]
    title_nodes = [
        node for node in nodes
        if node["team1"][0] != "loser" and node["team2"][0] != "loser"
    ]
    expected = knockout_teams - 1
    if len(title_nodes) != expected:
        raise FormatUnavailable(
            f"Pinned knockout graph has {len(title_nodes)} title-path matches; expected {expected}"
        )
    known_ids = {str(node["id"]) for node in nodes}
    for node in nodes:
        for kind, value in (node["team1"], node["team2"]):
            if kind in {"winner", "loser"}:
                dependency = str(value)
                if dependency not in known_ids or dependency == str(node["id"]):
                    raise FormatUnavailable(f"Invalid knockout dependency {dependency} → {node['id']}")

    # A topological order is authoritative; numeric match labels are not
    # available in every federation's pre-opening page (notably AFCON).
    pending = {str(node["id"]): node for node in nodes}
    ordered: list[dict[str, Any]] = []
    resolved: set[str] = set()
    while pending:
        ready = [
            node for node in pending.values()
            if all(
                kind not in {"winner", "loser"} or str(value) in resolved
                for kind, value in (node["team1"], node["team2"])
            )
        ]
        if not ready:
            raise FormatUnavailable("Pinned knockout graph contains a dependency cycle")
        ready.sort(key=lambda node: (
            node.get("date") or "9999-99-99",
            node.get("match") is None,
            node.get("match") or 10_000,
            str(node["id"]),
        ))
        for node in ready:
            ordered.append(node)
            resolved.add(str(node["id"]))
            pending.pop(str(node["id"]))

    used_as_title_dependency = {
        str(value)
        for node in title_nodes
        for kind, value in (node["team1"], node["team2"])
        if kind == "winner"
    }
    champions = [
        str(node["id"])
        for node in title_nodes
        if str(node["id"]) not in used_as_title_dependency
    ]
    if len(champions) != 1:
        raise FormatUnavailable(f"Pinned knockout graph has {len(champions)} possible final nodes")
    for node in ordered:
        node["championship"] = str(node["id"]) == champions[0]
    return ordered


def normalise_two_leg_graph(
    boxes: list[dict[str, Any]],
    knockout_teams: int,
) -> list[dict[str, Any]]:
    """Reduce pinned first/second-leg boxes to a causal tie graph."""
    ties: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for box in boxes:
        first = entrant_kind(str(box.get("team1", "")))
        second = entrant_kind(str(box.get("team2", "")))
        if first is None or second is None:
            continue
        raw_section = str(box.get("section_id") or "").casefold()
        section = re.sub(r"[^a-z0-9]", "", raw_section)
        semi = re.search(
            r"(?:^|\b)sf[-_ ]?(\d+)[-_ ]?(?:1st|2nd|first|second)",
            raw_section,
        )
        if semi:
            tie_id = f"SF{semi.group(1)}"
        elif section.startswith("f") or "final" in str(box.get("title", "")).casefold():
            tie_id = "FINAL"
        else:
            continue
        if "1stleg" in section or "firstleg" in section:
            leg = 1
        elif "2ndleg" in section or "secondleg" in section:
            leg = 2
        else:
            continue
        row = {
            "date": box.get("date"),
            "home": [first[0], first[1]],
            "away": [second[0], second[1]],
        }
        if leg in ties[tie_id] and ties[tie_id][leg] != row:
            raise FormatUnavailable(f"Conflicting pinned {tie_id} leg {leg}")
        ties[tie_id][leg] = row

    if len(ties) != knockout_teams - 1:
        raise FormatUnavailable(
            f"Pinned two-leg graph has {len(ties)} ties; expected {knockout_teams - 1}"
        )
    known_ids = set(ties)
    nodes: dict[str, dict[str, Any]] = {}
    for tie_id, legs in ties.items():
        if set(legs) != {1, 2}:
            raise FormatUnavailable(f"Pinned {tie_id} does not contain exactly two legs")
        first_pair = {tuple(legs[1]["home"]), tuple(legs[1]["away"])}
        second_pair = {tuple(legs[2]["home"]), tuple(legs[2]["away"])}
        if first_pair != second_pair:
            raise FormatUnavailable(f"Pinned {tie_id} legs do not contain the same entrants")
        for leg in legs.values():
            if not leg.get("date"):
                raise FormatUnavailable(f"Pinned {tie_id} leg has no date")
            for kind, value in (leg["home"], leg["away"]):
                if kind in {"winner", "loser"} and str(value) not in known_ids:
                    raise FormatUnavailable(f"Invalid two-leg dependency {value} → {tie_id}")
        nodes[tie_id] = {
            "id": tie_id,
            "legs": [legs[1], legs[2]],
        }

    pending = dict(nodes)
    ordered: list[dict[str, Any]] = []
    resolved: set[str] = set()
    while pending:
        ready = [
            node for node in pending.values()
            if all(
                kind not in {"winner", "loser"} or str(value) in resolved
                for leg in node["legs"]
                for kind, value in (leg["home"], leg["away"])
            )
        ]
        if not ready:
            raise FormatUnavailable("Pinned two-leg graph contains a dependency cycle")
        ready.sort(key=lambda node: (node["legs"][0]["date"], str(node["id"])))
        for node in ready:
            ordered.append(node)
            resolved.add(str(node["id"]))
            pending.pop(str(node["id"]))

    used = {
        str(value)
        for node in ordered
        for leg in node["legs"]
        for kind, value in (leg["home"], leg["away"])
        if kind == "winner"
    }
    champions = [str(node["id"]) for node in ordered if str(node["id"]) not in used]
    if len(champions) != 1:
        raise FormatUnavailable(f"Pinned two-leg graph has {len(champions)} final ties")
    for node in ordered:
        node["championship"] = str(node["id"]) == champions[0]
    return ordered


def attach_knockout_venue_hosts(
    nodes: list[dict[str, Any]],
    hosts: list[str],
    profile: dict[str, Any],
    start: str,
) -> None:
    """Attach only the pre-published venue country, never a realised opponent."""
    known = dict(profile.get("known_editions", {}).get(start, {}))
    patterns = list(
        known.get("knockout_venue_patterns", profile.get("knockout_venue_patterns", []))
    )
    host_set = set(hosts)
    for node in nodes:
        venue_text = str(node.pop("venue_text", ""))
        venue_host: str | None = None
        if len(hosts) == 1:
            venue_host = hosts[0]
        elif len(hosts) > 1:
            for row in patterns:
                code = str(row["code"])
                if code not in host_set:
                    raise FormatUnavailable(f"Venue pattern refers to non-host {code}")
                if re.search(str(row["pattern"]), venue_text, flags=re.IGNORECASE):
                    venue_host = code
                    break
            if venue_host is None:
                raise FormatUnavailable(
                    f"Pinned knockout venue cannot be assigned causally: {venue_text or 'missing'}"
                )
        node["venue_host"] = venue_host


def validate_third_place_allocation(
    allocation: dict[str, dict[str, str]],
    group_count: int,
    best_third: int,
) -> None:
    expected = math.comb(group_count, best_third)
    if len(allocation) != expected:
        raise FormatUnavailable(
            f"Pinned revisions contain {len(allocation)} third-place allocations; expected {expected}"
        )
    valid_groups = {chr(ord("A") + index) for index in range(group_count)}
    for combination, mapping in allocation.items():
        if len(combination) != best_third or set(combination) - valid_groups:
            raise FormatUnavailable(f"Invalid qualifying third-place set {combination}")
        if len(mapping) != best_third or set(mapping.values()) != set(combination):
            raise FormatUnavailable(f"Incomplete third-place mapping for {combination}")


@dataclass(slots=True)
class WikiRevision:
    language: str
    title: str
    revision: int
    timestamp: str
    content: str

    def provenance(self) -> dict[str, Any]:
        encoded = quote(self.title.replace(" ", "_"), safe=":()/")
        return {
            "language": self.language,
            "title": self.title,
            "revision": self.revision,
            "timestamp": self.timestamp,
            "sha256": hashlib.sha256(self.content.encode("utf-8")).hexdigest(),
            "url": f"https://{self.language}.wikipedia.org/w/index.php?title={encoded}&oldid={self.revision}",
            "license": LICENSE,
            "license_url": LICENSE_URL,
        }


class MediaWikiClient:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.user_agent = str(settings["user_agent"])
        self.languages = [str(item) for item in settings["languages"]]
        self.timeout = int(settings["request_timeout_seconds"])
        self.attempts = int(settings["attempts"])
        self.pause = float(settings["minimum_pause_seconds"])
        self.maximum_pages = int(settings["maximum_pages"])
        self.last_request = 0.0

    def request_json(self, url: str) -> dict[str, Any]:
        """Fetch one API URL with shared throttling and bounded backoff."""
        for attempt in range(self.attempts):
            delay = self.pause - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    self.last_request = time.monotonic()
                    return json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
                self.last_request = time.monotonic()
                status = getattr(error, "code", None)
                if attempt + 1 >= self.attempts or status not in {None, 429, 500, 502, 503, 504}:
                    raise FormatUnavailable(f"Wikipedia request failed: {type(error).__name__}: {error}") from error
                time.sleep(min(12.0, (2.0 ** attempt) + random.random()))
        raise AssertionError("unreachable")

    def api(self, language: str, parameters: dict[str, Any]) -> dict[str, Any]:
        query = dict(parameters)
        query.update({"format": "json", "formatversion": "2"})
        url = f"https://{language}.wikipedia.org/w/api.php?{urlencode(query)}"
        return self.request_json(url)

    def wikidata(self, parameters: dict[str, Any]) -> dict[str, Any]:
        query = dict(parameters)
        query.update({"format": "json", "formatversion": "2"})
        return self.request_json(
            f"https://www.wikidata.org/w/api.php?{urlencode(query)}"
        )

    def revision_by_id(self, revision: int) -> WikiRevision:
        payload = self.api("en", {
            "action": "query",
            "prop": "revisions",
            "revids": str(revision),
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
        })
        pages = payload.get("query", {}).get("pages", [])
        if not pages or "revisions" not in pages[0]:
            raise FormatUnavailable(f"Pinned Wikipedia revision {revision} is unavailable")
        row = pages[0]["revisions"][0]
        return WikiRevision(
            "en",
            str(pages[0]["title"]),
            int(row["revid"]),
            str(row["timestamp"]),
            str(row["slots"]["main"]["content"]),
        )

    def revision_before(self, language: str, title: str, cutoff: str) -> WikiRevision:
        payload = self.api(language, {
            "action": "query",
            "redirects": "1",
            "titles": title,
            "prop": "revisions",
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "rvlimit": "1",
            "rvstart": cutoff,
            "rvdir": "older",
        })
        pages = payload.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") or "revisions" not in pages[0]:
            raise FormatUnavailable(f"No pre-opening revision for {language}:{title}")
        row = pages[0]["revisions"][0]
        return WikiRevision(
            language,
            str(pages[0]["title"]),
            int(row["revid"]),
            str(row["timestamp"]),
            str(row["slots"]["main"]["content"]),
        )

    def find_main(self, candidates: list[str], cutoff: str) -> WikiRevision:
        # English is authoritative when it exists.
        for title in candidates:
            try:
                return self.revision_before("en", title, cutoff)
            except FormatUnavailable:
                continue
        search = self.api("en", {
            "action": "query",
            "list": "search",
            "srsearch": candidates[0],
            "srnamespace": "0",
            "srlimit": "5",
        })
        for row in search.get("query", {}).get("search", []):
            try:
                return self.revision_before("en", str(row["title"]), cutoff)
            except FormatUnavailable:
                continue

        # Only after English fails do we ask Wikidata for the corresponding
        # item and follow its exact sitelinks. Reusing an English phrase as an
        # ad-hoc search on every language wiki can select a different event.
        entities = self.wikidata({
            "action": "wbsearchentities",
            "search": candidates[0],
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": "5",
        }).get("search", [])
        for candidate in entities:
            entity_id = str(candidate.get("id", ""))
            if not entity_id:
                continue
            entity_payload = self.wikidata({
                "action": "wbgetentities",
                "ids": entity_id,
                "props": "sitelinks",
            })
            sitelinks = entity_payload.get("entities", {}).get(entity_id, {}).get("sitelinks", {})
            for language in self.languages:
                if language == "en":
                    continue
                link = sitelinks.get(f"{language}wiki")
                if not link or not link.get("title"):
                    continue
                try:
                    return self.revision_before(language, str(link["title"]), cutoff)
                except FormatUnavailable:
                    continue
        raise FormatUnavailable(f"No Wikipedia page found for {candidates[0]}")


def edition_clusters(matches: list[Match], source_codes: set[str]) -> list[list[Match]]:
    rows = [match for match in matches if match.tournament.upper() in source_codes]
    rows.sort(key=lambda match: (match.day, match.team1_code, match.team2_code))
    clusters: list[list[Match]] = []
    for match in rows:
        if not clusters or match.day - clusters[-1][-1].day > 120 * 400 / 365.25:
            clusters.append([match])
        else:
            clusters[-1].append(match)
    return clusters


def connected_groups(fixtures: list[Match], expected: int) -> list[list[str]]:
    neighbours: dict[str, set[str]] = defaultdict(set)
    first_seen: dict[str, int] = {}
    for index, match in enumerate(fixtures):
        first_seen.setdefault(match.team1, index)
        first_seen.setdefault(match.team2, index)
        neighbours[match.team1].add(match.team2)
        neighbours[match.team2].add(match.team1)
    groups: list[list[str]] = []
    remaining = set(neighbours)
    while remaining:
        seed = min(remaining, key=lambda code: (first_seen[code], code))
        component: set[str] = set()
        queue = deque([seed])
        while queue:
            code = queue.popleft()
            if code in component:
                continue
            component.add(code)
            queue.extend(neighbours[code] - component)
        remaining -= component
        groups.append(sorted(component, key=lambda code: (first_seen[code], code)))
    groups.sort(key=lambda group: min(first_seen[code] for code in group))
    if len(groups) != expected:
        raise FormatUnavailable(f"Group schedule produced {len(groups)} groups; expected {expected}")
    return groups


def source_rules(profile: dict[str, Any], cluster: list[Match]) -> dict[str, Any]:
    count = int(profile["group_matches"])
    if len(cluster) < count:
        raise FormatUnavailable(f"Only {len(cluster)} source matches; {count} group fixtures are required")
    group_rows = cluster[:count]
    participants = sorted({row.team1 for row in group_rows} | {row.team2 for row in group_rows})
    if len(participants) != int(profile["teams"]):
        raise FormatUnavailable(
            f"Group schedule contains {len(participants)} teams; expected {profile['teams']}"
        )
    groups = connected_groups(group_rows, int(profile["group_count"]))
    group_for = {
        code: chr(ord("A") + index)
        for index, members in enumerate(groups)
        for code in members
    }
    fixtures = []
    hosts: set[str] = set()
    for row in group_rows:
        if group_for[row.team1] != group_for[row.team2]:
            raise FormatUnavailable("A group fixture connects two inferred groups")
        fixtures.append({
            "date": row.date_text,
            "group": group_for[row.team1],
            "team1": row.team1,
            "team2": row.team2,
            "home": int(row.home_sign),
            "venue": row.venue,
        })
        if row.home_sign == 1:
            hosts.add(row.team1)
        elif row.home_sign == -1:
            hosts.add(row.team2)
    return {
        "participants": participants,
        "hosts": sorted(hosts),
        "groups": [
            {"name": chr(ord("A") + index), "teams": members}
            for index, members in enumerate(groups)
        ],
        "fixtures": fixtures,
    }


def title_candidates(profile: dict[str, Any], start: str) -> list[str]:
    year = int(start[:4])
    values = {
        "year": year,
        "previous_year": year - 1,
        "next_year": year + 1,
    }
    return [str(pattern).format(**values) for pattern in profile["page_patterns"]]


def fetch_format_pages(
    client: MediaWikiClient,
    profile: dict[str, Any],
    start: str,
) -> tuple[list[WikiRevision], str]:
    known = dict(profile.get("known_editions", {}).get(start, {}))
    cutoff = f"{start}T00:00:00Z"
    if known.get("revision"):
        main = client.revision_by_id(int(known["revision"]))
        if main.timestamp >= cutoff:
            raise FormatUnavailable("Pinned main revision is not safely pre-opening")
    else:
        candidates = [str(known["title"])] if known.get("title") else title_candidates(profile, start)
        main = client.find_main(candidates, cutoff)
    pages: dict[tuple[str, str], WikiRevision] = {(main.language, main.title): main}
    pending: deque[str] = deque(str(item) for item in known.get("extra_pages", []))
    pending.extend(sorted(referenced_titles(main.content)))
    while pending and len(pages) < client.maximum_pages:
        requested = pending.popleft().strip()
        if not requested:
            continue
        # Group membership and the round-robin schedule come from NFElo's own
        # immutable ledger. Fetching twelve transcluded group articles adds no
        # format fact but makes a bootstrap needlessly slow and rate-limit
        # prone. Knockout/final/allocation pages remain revision-pinned.
        if re.search(r"(?i)\s+group\s+[A-Z]$", requested):
            continue
        if not re.search(
            r"(?i)(knockout|\bfinal\b|third[- ]place(?:d)?\s+table)",
            requested,
        ):
            continue
        key = (main.language, requested)
        if key in pages:
            continue
        # Keep recursion within the tournament and directly referenced format
        # templates. Generic utility templates are neither facts nor needed.
        root_words = {word.casefold() for word in re.findall(r"[A-Za-z]{4,}", main.title)}
        candidate_words = {word.casefold() for word in re.findall(r"[A-Za-z]{4,}", requested)}
        if not root_words.intersection(candidate_words) and "third-place" not in requested.casefold():
            continue
        try:
            revision = client.revision_before(main.language, requested, cutoff)
        except FormatUnavailable:
            continue
        pages[(revision.language, revision.title)] = revision
        pending.extend(sorted(referenced_titles(revision.content)))
    if pending:
        raise FormatUnavailable("Wikipedia format page graph exceeded the safety limit")
    return sorted(pages.values(), key=lambda page: (page.language, page.title)), cutoff


def make_entry(
    client: MediaWikiClient,
    profile: dict[str, Any],
    cluster: list[Match],
) -> dict[str, Any]:
    start = cluster[0].date_text
    end = cluster[-1].date_text
    source = source_rules(profile, cluster)
    known = dict(profile.get("known_editions", {}).get(start, {}))
    fail_closed = known.get("fail_closed", profile.get("fail_closed"))
    base = {
        "facts_version": FACTS_VERSION,
        "profile": profile["id"],
        "family": profile["family"],
        "source_codes": sorted(str(code).upper() for code in profile["source_codes"]),
        "start": start,
        "source_end": end,
        "participants": source["participants"],
    }
    if fail_closed:
        base.update({
            "status": "unsupported",
            "reason": str(fail_closed),
            "facts_sha256": digest({"base": base, "reason": fail_closed}),
        })
        return base

    pages, cutoff = fetch_format_pages(client, profile, start)
    all_boxes = [
        box
        for page in pages
        for box in parse_football_boxes(page.title, page.content)
    ]
    third = parse_third_place_tables(
        (page.content for page in pages),
        int(profile["group_count"]),
    )
    rules: dict[str, Any] = {
        "groups": source["groups"],
        "group_fixtures": source["fixtures"],
        "hosts": source["hosts"],
        "advance_per_group": int(profile["advance_per_group"]),
        "best_third": int(profile["best_third"]),
        "tie_break": str(profile["tie_break"]),
        "knockout_teams": int(profile["knockout_teams"]),
        "knockout_kind": str(profile["knockout"]),
        "away_goals": bool(profile.get("away_goals", False)),
    }
    if profile["knockout"] == "revision_graph":
        knockout_matches = normalise_knockout_graph(
            all_boxes,
            int(profile["group_matches"]),
            int(profile["knockout_teams"]),
        )
        attach_knockout_venue_hosts(
            knockout_matches,
            source["hosts"],
            profile,
            start,
        )
        rules["knockout_matches"] = knockout_matches
        if int(profile["best_third"]):
            if not third:
                raise FormatUnavailable("Pinned revisions contain no complete third-place allocation table")
            validate_third_place_allocation(
                third,
                int(profile["group_count"]),
                int(profile["best_third"]),
            )
            rules["third_place_allocation"] = third
    elif profile["knockout"] == "two_leg_graph":
        rules["knockout_ties"] = normalise_two_leg_graph(
            all_boxes,
            int(profile["knockout_teams"]),
        )

    format_evidence = {
        "football_boxes": len(all_boxes),
        "third_place_allocations": len(third),
        "page_count": len(pages),
    }
    entry = {
        **base,
        "status": "ready",
        "cutoff": cutoff,
        "rules": rules,
        "evidence": format_evidence,
        "provenance": [page.provenance() for page in pages],
    }
    entry["facts_sha256"] = digest({
        "profile": entry["profile"],
        "start": start,
        "participants": entry["participants"],
        "rules": rules,
        "provenance": entry["provenance"],
    })
    return entry


def discover(
    source: Path,
    configuration: dict[str, Any],
) -> list[tuple[dict[str, Any], list[Match]]]:
    successors = read_successors(source / "teams.tsv")
    matches = read_matches(
        source / "elo_pages",
        successors,
        source / "supplemental_results.csv",
    )
    found: list[tuple[dict[str, Any], list[Match]]] = []
    for profile in configuration["profiles"]:
        codes = {str(code).upper() for code in profile["source_codes"]}
        for cluster in edition_clusters(matches, codes):
            if cluster[0].date_text < str(profile["minimum_start"]):
                continue
            # A profile is activated only once the full published group
            # schedule is represented in NFElo's own source. This prevents a
            # partial or qualification-stage cluster from being mislabelled.
            if len(cluster) < int(profile["group_matches"]):
                continue
            found.append((profile, cluster))
    found.sort(key=lambda item: (item[1][0].date_text, item[0]["id"]))
    return found


def _pair(row: dict[str, Any]) -> tuple[str, str]:
    return tuple(sorted((str(row["a"]), str(row["b"]))))


def _complete_components(
    rows: list[dict[str, Any]],
) -> tuple[list[set[str]], dict[tuple[str, str], int]] | None:
    """Return balanced round-robin components represented by ``rows``.

    A two-team component is deliberately valid: in knockout competitions it
    represents an opening tie whose winner feeds the next causal stage.  This
    lets the same evidence engine describe leagues, groups, and old knockout
    pathways without maintaining a hand-written registry for every edition.
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    pairs: Counter[tuple[str, str]] = Counter()
    for row in rows:
        first, second = str(row["a"]), str(row["b"])
        if first == second:
            return None
        adjacency[first].add(second)
        adjacency[second].add(first)
        pairs[_pair(row)] += 1
    unseen = set(adjacency)
    components: list[set[str]] = []
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        pending = [seed]
        component = {seed}
        while pending:
            first = pending.pop()
            for second in adjacency[first]:
                if second not in component:
                    component.add(second)
                    unseen.discard(second)
                    pending.append(second)
        components.append(component)
    for component in components:
        ordered = sorted(component)
        counts = [
            pairs[(first, second)]
            for offset, first in enumerate(ordered)
            for second in ordered[offset + 1:]
        ]
        if not counts or min(counts) <= 0 or min(counts) != max(counts):
            return None
    components.sort(key=lambda values: tuple(sorted(values)))
    return components, dict(pairs)


def _standings(
    component: set[str],
    rows: list[dict[str, Any]],
    win_points: int,
) -> list[str]:
    table = {
        code: {"points": 0, "gd": 0, "gf": 0, "wins": 0}
        for code in component
    }
    for row in rows:
        first, second = str(row["a"]), str(row["b"])
        if first not in component or second not in component:
            continue
        goals1, goals2 = int(row["sa"]), int(row["sb"])
        if goals1 > goals2:
            table[first]["points"] += win_points
            table[first]["wins"] += 1
        elif goals2 > goals1:
            table[second]["points"] += win_points
            table[second]["wins"] += 1
        else:
            table[first]["points"] += 1
            table[second]["points"] += 1
        table[first]["gd"] += goals1 - goals2
        table[second]["gd"] += goals2 - goals1
        table[first]["gf"] += goals1
        table[second]["gf"] += goals2
    return sorted(
        component,
        key=lambda code: (
            -table[code]["points"],
            -table[code]["gd"],
            -table[code]["gf"],
            -table[code]["wins"],
            code,
        ),
    )


def _points_for_win(
    evidence: dict[str, Any],
    rows: list[dict[str, Any]],
) -> int:
    year = int(str(rows[0]["date"])[:4])
    family = str(evidence.get("family", "")).casefold()
    if "fifa world cup" in family and year >= 1994:
        return 3
    return 2 if year < 1995 else 3


def _opening_pathway_entrants(rows: list[dict[str, Any]]) -> set[str]:
    """Find the first non-overlapping tie layer after a group-stage prefix."""
    entrants: set[str] = set()
    assigned_pair: dict[str, tuple[str, str]] = {}
    for row in rows:
        pair = _pair(row)
        first, second = pair
        conflict = any(
            code in assigned_pair and assigned_pair[code] != pair
            for code in pair
        )
        if conflict:
            break
        assigned_pair[first] = pair
        assigned_pair[second] = pair
        entrants.update(pair)
    return entrants


def _fixture(row: dict[str, Any], group: str) -> dict[str, Any]:
    return {
        "date": str(row["date"]),
        "group": group,
        "team1": str(row["a"]),
        "team2": str(row["b"]),
        "home": int(row.get("home", 0)),
        "venue": str(row.get("venue", "")),
    }


def _knockout_schedule(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    schedule = []
    for row in rows:
        home = int(row.get("home", 0))
        schedule.append({
            "date": str(row["date"]),
            "home": home,
            "venue_host": (
                str(row["a"]) if home == 1
                else str(row["b"]) if home == -1
                else None
            ),
        })
    return schedule


def _knockout_home_mode(rows: list[dict[str, Any]], *, direct: bool = False) -> str:
    if direct:
        return "fixed-team"
    non_neutral = sum(int(row.get("home", 0)) != 0 for row in rows)
    return "alternating" if non_neutral * 2 > len(rows) else "fixed-team"


def _inferred_rules(evidence: dict[str, Any]) -> tuple[dict[str, Any], str]:
    rows = sorted(
        evidence["rows"],
        key=lambda row: (str(row["date"]), int(row["id"])),
    )
    participants = sorted({
        str(code)
        for row in rows
        for code in (row["a"], row["b"])
    })
    if len(participants) < 2 or not rows:
        raise FormatUnavailable("fewer than two participants or no tournament matches")

    win_points = _points_for_win(evidence, rows)
    common = {
        "tie_break": "overall_then_head_to_head",
        "points_for_win": win_points,
        "away_goals": False,
        "hosts": [],
    }
    if len(participants) == 2:
        return ({
            **common,
            "groups": [],
            "group_fixtures": [],
            "active_groups": [],
            "advance_per_group": 0,
            "best_next": 0,
            "bye_entrants": participants,
            "knockout_kind": "inferred-field",
            "knockout_schedule": _knockout_schedule(rows),
            "knockout_home_mode": _knockout_home_mode(rows, direct=True),
        }, "direct-title-tie")

    complete = _complete_components(rows)
    if complete is not None and len(complete[0]) == 1:
        group = {"name": "A", "teams": participants}
        return ({
            **common,
            "groups": [group],
            "group_fixtures": [_fixture(row, "A") for row in rows],
            "active_groups": ["A"],
            "advance_per_group": 1,
            "best_next": 0,
            "bye_entrants": [],
            "knockout_kind": "league",
            "knockout_schedule": [],
            "knockout_home_mode": "fixed-team",
        }, "complete-league")
    if complete is not None and len(complete[0]) > 1:
        components, _ = complete
        names = {index: f"G{index + 1:02d}" for index in range(len(components))}
        team_group = {
            code: index
            for index, component in enumerate(components)
            for code in component
        }
        groups = [
            {"name": names[index], "teams": sorted(component)}
            for index, component in enumerate(components)
        ]
        return ({
            **common,
            "groups": groups,
            "group_fixtures": [
                _fixture(row, names[team_group[str(row["a"])]])
                for row in rows
            ],
            "active_groups": [names[index] for index in range(len(components))],
            "advance_per_group": 1,
            "best_next": 0,
            "bye_entrants": [],
            "knockout_kind": "inferred-field",
            "knockout_schedule": [],
            "knockout_home_mode": "fixed-team",
        }, "top-1-from-observed-pools")

    candidates: list[tuple[int, dict[str, Any], str]] = []
    for cut in range(1, len(rows)):
        # Same-day matches form one frozen scheduling layer.  Imprecise old
        # dates remain together rather than being split by arbitrary row order.
        if str(rows[cut - 1]["date"]) == str(rows[cut]["date"]):
            continue
        represented = _complete_components(rows[:cut])
        if represented is None:
            continue
        components, _ = represented
        team_group = {
            code: index
            for index, component in enumerate(components)
            for code in component
        }
        names = {index: f"G{index + 1:02d}" for index in range(len(components))}
        groups = [
            {"name": names[index], "teams": sorted(component)}
            for index, component in enumerate(components)
        ]
        fixtures = [
            _fixture(row, names[team_group[str(row["a"])]])
            for row in rows[:cut]
        ]

        if "nations league" in str(evidence.get("family", "")).casefold():
            for pathway_start in range(cut, len(rows)):
                if (
                    pathway_start > cut
                    and str(rows[pathway_start - 1]["date"])
                    == str(rows[pathway_start]["date"])
                ):
                    continue
                title_four = _opening_pathway_entrants(rows[pathway_start:])
                if len(title_four) != 4 or any(code not in team_group for code in title_four):
                    continue
                title_groups: dict[int, set[str]] = defaultdict(set)
                for code in title_four:
                    title_groups[team_group[code]].add(code)
                if len(title_groups) != 4 or any(len(values) != 1 for values in title_groups.values()):
                    continue
                if any(
                    next(iter(selected))
                    not in set(
                        _standings(
                            components[index],
                            rows[:cut],
                            win_points,
                        )[:2]
                    )
                    for index, selected in title_groups.items()
                ):
                    continue
                candidates.append((cut, {
                    **common,
                    "groups": groups,
                    "group_fixtures": fixtures,
                    "active_groups": [names[index] for index in sorted(title_groups)],
                    "advance_per_group": 1,
                    "best_next": 0,
                    "bye_entrants": [],
                    "knockout_kind": "inferred-field",
                    "knockout_schedule": _knockout_schedule(rows[pathway_start:]),
                    "knockout_home_mode": _knockout_home_mode(rows[pathway_start:]),
                }, "top-1-from-four-title-groups"))

        opening = _opening_pathway_entrants(rows[cut:])
        if len(opening) < 2:
            continue
        contributors: dict[int, set[str]] = defaultdict(set)
        byes: set[str] = set()
        for code in opening:
            if code in team_group:
                contributors[team_group[code]].add(code)
            else:
                byes.add(code)
        if not contributors:
            continue

        counts = [len(values) for values in contributors.values()]
        direct = min(counts)
        best_next = sum(value - direct for value in counts)
        if direct < 1 or max(counts) - direct > 1:
            continue
        clear = True
        for index, selected in contributors.items():
            ranking = _standings(
                components[index],
                rows[:cut],
                win_points,
            )
            expected_count = len(selected)
            # Realised advancement is used only to settle a tied or otherwise
            # clear top-k pathway; it never fixes a simulated later opponent.
            if not selected.issubset(set(ranking[:expected_count])):
                boundary = expected_count
                if boundary >= len(ranking):
                    clear = False
                    break
                selected_keys = {
                    code: ranking.index(code)
                    for code in selected
                }
                if max(selected_keys.values(), default=0) > boundary:
                    clear = False
                    break
        if not clear:
            continue

        active = [names[index] for index in sorted(contributors)]
        rules = {
            **common,
            "groups": groups,
            "group_fixtures": fixtures,
            "active_groups": active,
            "advance_per_group": direct,
            "best_next": best_next,
            "bye_entrants": sorted(byes),
            "knockout_kind": "inferred-field",
            "knockout_schedule": _knockout_schedule(rows[cut:]),
            "knockout_home_mode": _knockout_home_mode(rows[cut:]),
        }
        label = (
            f"top-{direct}-per-group"
            + (f"-plus-{best_next}" if best_next else "")
            + (f"-and-{len(byes)}-byes" if byes else "")
        )
        candidates.append((cut, rules, label))

    if not candidates:
        raise FormatUnavailable(
            "the match record does not establish a coherent league, group pathway, or title tie"
        )
    def candidate_key(item: tuple[int, dict[str, Any], str]) -> tuple[Any, ...]:
        cut, candidate, _ = item
        active_count = len(candidate["active_groups"])
        group_count = len(candidate["groups"])
        field_size = (
            active_count * int(candidate["advance_per_group"])
            + int(candidate["best_next"])
            + len(candidate["bye_entrants"])
        )
        power_of_two = field_size > 1 and field_size & (field_size - 1) == 0
        family = str(evidence.get("family", "")).casefold()
        if "nations league" in family:
            # Multi-division Nations Leagues include teams that cannot win the
            # overall title.  Prefer the clear final-four pathway rather than
            # treating lower-league group winners as title entrants.
            return (
                power_of_two,
                -abs(field_size - 4),
                -len(candidate["bye_entrants"]),
                sum(
                    len(group["teams"])
                    for group in candidate["groups"]
                    if group["name"] in candidate["active_groups"]
                ),
                cut,
            )
        # Elsewhere every balanced opening group normally belongs to the title
        # pathway.  This prevents a later realised phase from silently giving
        # zero pre-tournament chance to a team eliminated in an earlier group.
        return (
            active_count == group_count,
            -(group_count - active_count),
            power_of_two,
            -len(candidate["bye_entrants"]),
            cut,
        )

    _, rules, label = max(candidates, key=candidate_key)
    return rules, label


def infer_universal_manifest(
    evidence_editions: list[dict[str, Any]],
    configuration: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Infer every site tournament and retain stronger pinned evidence.

    Completed results may identify that a side was the winner or runner-up of
    a group.  They are used only to reconstruct that reusable slot topology;
    later opponents are resampled in every trial.  This is the deliberately
    narrow hindsight allowance requested for historical coverage.
    """
    previous = previous or {"editions": {}}
    precise = {
        (str(entry.get("family")), str(entry.get("start"))): dict(entry)
        for entry in previous.get("editions", {}).values()
        if entry.get("status") == "ready"
        and entry.get("profile") != INFERRED_PROFILE
    }
    editions: dict[str, Any] = {}
    for evidence in sorted(
        evidence_editions,
        key=lambda row: (str(row["start"]), str(row["family"]), str(row["id"])),
    ):
        participants = sorted(str(code) for code in evidence["participants"])
        source_signature = digest([
            (
                str(row["date"]), str(row["a"]), str(row["b"]),
                int(row["sa"]), int(row["sb"]), str(row.get("tc", "")),
                int(row.get("home", 0)),
            )
            for row in evidence["rows"]
        ])
        exact = precise.get((str(evidence["family"]), str(evidence["start"])))
        if exact is not None and set(exact.get("participants", [])) == set(participants):
            key = f"pinned:{evidence['id']}"
            exact["trials"] = int(configuration["trials"])
            editions[key] = exact
            continue

        base = {
            "facts_version": FACTS_VERSION,
            "profile": INFERRED_PROFILE,
            "family": str(evidence["family"]),
            "category": str(evidence["category"]),
            "source_codes": sorted(str(code) for code in evidence["source_codes"]),
            "start": str(evidence["start"]),
            "state_date": str(evidence.get("state_date", evidence["start"])),
            "source_end": str(evidence["end"]),
            "participants": participants,
            "source_signature": source_signature,
            "trials": INFERRED_TRIALS,
            "evidence_mode": "structural-hindsight",
        }
        key = f"inferred:{evidence['id']}"
        try:
            rules, pathway = _inferred_rules(evidence)
            provenance = [{
                "source": "NFElo match ledger",
                "sha256": source_signature,
                "scope": "participants, opening schedule, locations, and reusable advancement topology",
            }]
            entry = {
                **base,
                "status": "ready",
                "confidence": "observed-structure",
                "pathway": pathway,
                "rules": rules,
                "provenance": provenance,
            }
            entry["facts_sha256"] = digest({
                "profile": entry["profile"],
                "start": entry["start"],
                "participants": entry["participants"],
                "rules": entry["rules"],
                "provenance": entry["provenance"],
            })
        except FormatUnavailable as error:
            entry = {
                **base,
                "status": "unsupported",
                "confidence": "truly-inconclusive",
                "reason": str(error),
                "retryable": False,
            }
            entry["facts_sha256"] = digest(entry)
        editions[key] = entry

    ready = sum(entry["status"] == "ready" for entry in editions.values())
    manifest = {
        "schema": SCHEMA,
        "algorithm": str(configuration["algorithm"]),
        "trials": int(configuration["trials"]),
        "policy": {
            "timing": "the complete NFElo state is frozen immediately before each opening match",
            "hindsight": "completed results may reveal a clear top-one/top-two pathway, but never fix a simulated later opponent",
            "future": "every build discovers new editions and applies the same evidence classifier",
            "failure": "only structurally contradictory or genuinely inconclusive editions publish no percentage",
        },
        "coverage": {
            "editions": len(editions),
            "ready": ready,
            "unsupported": len(editions) - ready,
            "percent": round(100.0 * ready / max(1, len(editions)), 3),
        },
        "editions": editions,
    }
    manifest["manifest_sha256"] = digest({
        "schema": manifest["schema"],
        "algorithm": manifest["algorithm"],
        "trials": manifest["trials"],
        "editions": editions,
    })
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "editions": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if int(value.get("schema", -1)) != SCHEMA or not isinstance(value.get("editions"), dict):
        raise ValueError("Unsupported tournament-odds manifest schema")
    return value


def retryable_format_failure(error: FormatUnavailable, start: str) -> bool:
    """Retry transient failures and formats that can still improve pre-opener."""
    opening = datetime.fromisoformat(f"{start}T00:00:00+00:00")
    if datetime.now(timezone.utc) < opening:
        return True
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "request failed",
            "timed out",
            "temporarily unavailable",
        )
    )


def update_manifest(
    source: Path,
    config_path: Path,
    output: Path,
    *,
    offline: bool = False,
    only_profile: str | None = None,
    only_start: str | None = None,
) -> dict[str, Any]:
    configuration = load_configuration(config_path)
    old = load_manifest(output)
    old_editions = dict(old.get("editions", {}))
    editions: dict[str, Any] = (
        dict(old_editions) if only_profile or only_start else {}
    )
    client = MediaWikiClient(configuration["wikipedia"])
    failures: list[dict[str, str]] = []
    for profile, cluster in discover(source, configuration):
        start = cluster[0].date_text
        if only_profile and str(profile["id"]) != only_profile:
            continue
        if only_start and start != only_start:
            continue
        key = f"{profile['id']}:{start}"
        previous = old_editions.get(key)
        known = dict(profile.get("known_editions", {}).get(start, {}))
        fail_closed = known.get("fail_closed", profile.get("fail_closed"))
        source_signature = digest([
            (row.date_text, row.team1, row.team2, row.tournament, row.venue, row.home_sign)
            for row in cluster[:int(profile["group_matches"])]
        ])
        if (
            previous
            and previous.get("source_signature") == source_signature
            and previous.get("profile") == profile["id"]
            and int(previous.get("facts_version", 0)) == FACTS_VERSION
            and (
                previous.get("status") == "ready"
                or (
                    previous.get("status") == "unsupported"
                    and not bool(previous.get("retryable"))
                )
                or bool(fail_closed)
            )
        ):
            print(f"Reusing {key}…", file=sys.stderr, flush=True)
            editions[key] = previous
            continue
        if offline:
            if (
                previous
                and previous.get("source_signature") == source_signature
                and int(previous.get("facts_version", 0)) == FACTS_VERSION
            ):
                print(f"Reusing {key} offline…", file=sys.stderr, flush=True)
                editions[key] = previous
            else:
                failures.append({"edition": key, "error": "offline and not previously imported"})
            continue
        print(f"Importing {key}…", file=sys.stderr, flush=True)
        try:
            entry = make_entry(client, profile, cluster)
            entry["source_signature"] = source_signature
            editions[key] = entry
        except FormatUnavailable as error:
            if (
                previous
                and previous.get("status") == "ready"
                and previous.get("source_signature") == source_signature
                and int(previous.get("facts_version", 0)) == FACTS_VERSION
            ):
                editions[key] = previous
            else:
                entry = {
                    "facts_version": FACTS_VERSION,
                    "profile": profile["id"],
                    "family": profile["family"],
                    "source_codes": sorted(str(code).upper() for code in profile["source_codes"]),
                    "start": start,
                    "source_end": cluster[-1].date_text,
                    "status": "unsupported",
                    "reason": str(error),
                    "retryable": retryable_format_failure(error, start),
                    "source_signature": source_signature,
                }
                entry["facts_sha256"] = digest(entry)
                editions[key] = entry
                failures.append({"edition": key, "error": str(error)})
    manifest = {
        "schema": SCHEMA,
        "algorithm": str(configuration["algorithm"]),
        "trials": int(configuration["trials"]),
        "policy": {
            "timing": "last revision safely before the opening date or an audited pre-kickoff revision",
            "language_order": configuration["wikipedia"]["languages"],
            "hindsight": "realised knockout opponents are never imported as fixed entrants",
            "failure": "unsupported or ambiguous formats publish no percentage",
        },
        "editions": editions,
    }
    manifest["manifest_sha256"] = digest({
        "schema": manifest["schema"],
        "algorithm": manifest["algorithm"],
        "trials": manifest["trials"],
        "editions": editions,
    })
    changed = write_json_if_changed(output, manifest)
    ready = sum(entry.get("status") == "ready" for entry in editions.values())
    print(canonical_json({
        "status": "ok",
        "changed": changed,
        "editions": len(editions),
        "ready": ready,
        "unsupported": len(editions) - ready,
        "failures": failures,
    }))
    return manifest


def validate_manifest(path: Path) -> dict[str, Any]:
    manifest = load_manifest(path)
    expected = digest({
        "schema": manifest["schema"],
        "algorithm": manifest["algorithm"],
        "trials": manifest["trials"],
        "editions": manifest["editions"],
    })
    if manifest.get("manifest_sha256") != expected:
        raise ValueError("Tournament manifest digest does not match its contents")
    for key, entry in manifest["editions"].items():
        if int(entry.get("facts_version", 0)) != FACTS_VERSION:
            raise ValueError(f"Stale tournament facts in {key}")
        if entry.get("status") != "ready":
            continue
        facts_expected = digest({
            "profile": entry["profile"],
            "start": entry["start"],
            "participants": entry["participants"],
            "rules": entry["rules"],
            "provenance": entry["provenance"],
        })
        if entry.get("facts_sha256") != facts_expected:
            raise ValueError(f"Tournament facts digest mismatch in {key}")
        if entry.get("profile") == INFERRED_PROFILE:
            participants = set(str(code) for code in entry["participants"])
            if len(participants) < 2:
                raise ValueError(f"Inferred tournament has too few participants in {key}")
            rules = entry["rules"]
            kind = str(rules.get("knockout_kind"))
            if kind not in {"league", "inferred-field"}:
                raise ValueError(f"Unknown inferred tournament kind in {key}: {kind}")
            groups = {
                str(group["name"]): set(str(code) for code in group["teams"])
                for group in rules.get("groups", [])
            }
            represented = set().union(*groups.values()) if groups else set()
            if not represented.issubset(participants):
                raise ValueError(f"Inferred group contains an unknown participant in {key}")
            if sum(len(values) for values in groups.values()) != len(represented):
                raise ValueError(f"Inferred groups overlap in {key}")
            active = [str(name) for name in rules.get("active_groups", [])]
            if any(name not in groups for name in active):
                raise ValueError(f"Unknown active inferred group in {key}")
            byes = set(str(code) for code in rules.get("bye_entrants", []))
            if not byes.issubset(participants) or byes.intersection(represented):
                raise ValueError(f"Invalid inferred bye entrants in {key}")
            fixtures = rules.get("group_fixtures", [])
            for fixture in fixtures:
                name = str(fixture["group"])
                if name not in groups or {
                    str(fixture["team1"]), str(fixture["team2"])
                } - groups[name]:
                    raise ValueError(f"Inferred fixture/group mismatch in {key}")
            if kind == "league":
                if len(groups) != 1 or represented != participants:
                    raise ValueError(f"Incomplete inferred league in {key}")
            else:
                field_size = (
                    len(active) * int(rules.get("advance_per_group", 0))
                    + int(rules.get("best_next", 0))
                    + len(byes)
                )
                if field_size < 2 or field_size > len(participants):
                    raise ValueError(f"Invalid inferred title field in {key}: {field_size}")
            if int(entry.get("trials", 0)) < 10_000:
                raise ValueError(f"Too few inferred simulation trials in {key}")
            continue
        cutoff = str(entry["cutoff"])
        if any(str(row["timestamp"]) >= cutoff for row in entry["provenance"]):
            raise ValueError(f"Post-opening provenance in {key}")
        rules = entry["rules"]
        participants = set(entry["participants"])
        hosts = set(rules.get("hosts", []))
        if not hosts.issubset(participants):
            raise ValueError(f"Unknown tournament host in {key}")
        scheduled = {
            code
            for fixture in rules["group_fixtures"]
            for code in (fixture["team1"], fixture["team2"])
        }
        if scheduled != participants:
            raise ValueError(f"Participant/schedule mismatch in {key}")
        if rules["knockout_kind"] == "revision_graph":
            nodes = rules["knockout_matches"]
            if len([
                node for node in nodes
                if node["team1"][0] != "loser" and node["team2"][0] != "loser"
            ]) != int(rules["knockout_teams"]) - 1:
                raise ValueError(f"Incomplete knockout graph in {key}")
            resolved: set[str] = set()
            for node in nodes:
                if not node.get("date"):
                    raise ValueError(f"Undated knockout node in {key}")
                if node.get("venue_host") is not None and node["venue_host"] not in hosts:
                    raise ValueError(f"Invalid knockout venue host in {key}")
                for kind, value in (node["team1"], node["team2"]):
                    if kind in {"winner", "loser"} and str(value) not in resolved:
                        raise ValueError(f"Non-causal knockout order in {key}")
                resolved.add(str(node["id"]))
            if int(rules.get("best_third", 0)):
                try:
                    validate_third_place_allocation(
                        rules["third_place_allocation"],
                        len(rules["groups"]),
                        int(rules["best_third"]),
                    )
                except FormatUnavailable as error:
                    raise ValueError(f"Invalid third-place allocation in {key}: {error}") from error
        elif rules["knockout_kind"] == "two_leg_graph":
            ties = rules["knockout_ties"]
            if len(ties) != int(rules["knockout_teams"]) - 1:
                raise ValueError(f"Incomplete two-leg graph in {key}")
            resolved = set()
            for tie in ties:
                if len(tie.get("legs", [])) != 2:
                    raise ValueError(f"Incomplete two-leg tie in {key}")
                for leg in tie["legs"]:
                    if not leg.get("date"):
                        raise ValueError(f"Undated two-leg tie in {key}")
                    for kind, value in (leg["home"], leg["away"]):
                        if kind in {"winner", "loser"} and str(value) not in resolved:
                            raise ValueError(f"Non-causal two-leg order in {key}")
                resolved.add(str(tie["id"]))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    update = subparsers.add_parser("update")
    update.add_argument("--source", type=Path, default=Path("source"))
    update.add_argument("--config", type=Path, default=Path("config/tournament_odds.json"))
    update.add_argument("--output", type=Path, default=Path("source/tournament_odds/manifest.json"))
    update.add_argument("--offline", action="store_true")
    update.add_argument("--only-profile")
    update.add_argument("--only-start")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, default=Path("source/tournament_odds/manifest.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "update":
        update_manifest(
            args.source,
            args.config,
            args.output,
            offline=args.offline,
            only_profile=args.only_profile,
            only_start=args.only_start,
        )
    else:
        manifest = validate_manifest(args.manifest)
        print(canonical_json({
            "status": "ok",
            "editions": len(manifest["editions"]),
            "ready": sum(row.get("status") == "ready" for row in manifest["editions"].values()),
        }))


if __name__ == "__main__":
    main()
