#!/usr/bin/env python3
"""Conservative tournament classification for NFELO.

The audit status has three values: friendly, competitive and uncertain.
For model weighting, uncertain and unknown tournaments are always treated
as competitive. Friendly status therefore requires positive evidence.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable


VALID_STATUSES = {"friendly", "competitive", "uncertain"}
VALID_MODEL_CLASSES = {"friendly", "competitive"}
DEFAULT_STATUS = "uncertain"
DEFAULT_MODEL_CLASS = "competitive"

PROTECTED_COMPETITIVE_CODES = {
    "WC", "WQ", "EQ", "CQ", "AQ", "FQ", "OQ", "NL", "AC", "EC",
}
PROTECTED_FRIENDLY_CODES = {"F", "FFS"}

OFFICIAL_CONSEQUENCE_PATTERNS = (
    r"\bqualif(?:ier|iers|ying|ication)?\b",
    r"\bpreliminary competition\b",
    r"\bplay[\s-]?offs?\b",
    r"\bnations league\b",
    r"\bleague [abcd]\b",
    r"\bpromotion\b",
    r"\brelegation\b",
)

OFFICIAL_STRUCTURE_PATTERNS = (
    r"\bfifa world cup\b",
    r"\bworld cup\b",
    r"\beuropean championship\b",
    r"\basian cup\b",
    r"\bafrica cup of nations\b",
    r"\bafrican nations cup\b",
    r"\bcopa america\b",
    r"\bgold cup\b",
    r"\bnations cup\b",
    r"\bconfederations cup\b",
    r"\bchampionship\b",
    r"\bolympic games\b",
    r"\basian games\b",
    r"\bafrican games\b",
    r"\bpan[\s-]?american games\b",
    r"\bpacific games\b",
    r"\bsouth pacific games\b",
    r"\bmediterranean games\b",
    r"\barab games\b",
    r"\bcentral american and caribbean games\b",
)

EXACT_FRIENDLY_EXCEPTIONS = {
    "friendly",
    "international friendly",
    "fifa series",
    "fifa series and capital cup",
    "friendship games",
    "mini world cup",
    "world football cup",
}

FRIENDLY_SIGNAL_PATTERNS = (
    r"\bfriendly\b",
    r"\bfriendship\b",
    r"\bgoodwill\b",
    r"\binvitational\b",
    r"\bmemorial\b",
    r"\banniversary\b",
    r"\bjubilee\b",
    r"\bexhibition\b",
    r"\bfootball festival\b",
    r"\btestimonial\b",
    r"\bpreparation\b",
    r"\bcommemorat(?:ion|ive)\b",
    r"\bcentenary\b",
    r"\bcentennial\b",
    r"\bindependence (?:anniversary )?(?:tournament|cup|festival|celebration)\b",
    r"\bmerdeka (?:tournament|cup|games)\b",
)


@dataclass(frozen=True)
class Decision:
    status: str
    operational_class: str
    confidence: str
    basis: str
    evidence_type: str
    source_url: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "operational_class": self.operational_class,
            "confidence": self.confidence,
            "basis": self.basis,
            "evidence_type": self.evidence_type,
            "source_url": self.source_url,
        }


def normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


def operational_class(status: str) -> str:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid tournament status: {status}")
    return "friendly" if status == "friendly" else "competitive"


def read_aliases(path: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = [field.strip() for field in line.split("\t")]
        if len(fields) < 2 or not fields[0]:
            continue
        aliases = [value for value in fields[1:] if value]
        if aliases:
            result[fields[0]] = aliases
    return result


def read_levels(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(code): int(level)
        for code, level in payload.get("tournament_levels", {}).items()
    }


def read_supplemental_names(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(code): [str(name)]
        for code, name in payload.items()
        if str(code) and str(name)
    }


def merge_aliases(*mappings: dict[str, list[str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for mapping in mappings:
        for code, aliases in mapping.items():
            current = result.setdefault(code, [])
            for alias in aliases:
                if alias and alias not in current:
                    current.append(alias)
    return result


def read_evidence(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("tournaments", payload)
    if not isinstance(rows, dict):
        raise ValueError("Evidence file must contain a tournament mapping.")
    return {
        str(code): dict(value)
        for code, value in rows.items()
        if isinstance(value, dict)
    }


def explicit_evidence_decision(
    evidence: dict[str, Any] | None,
) -> Decision | None:
    if not evidence:
        return None
    status = str(evidence.get("status", "")).strip().casefold()
    if status not in VALID_STATUSES:
        raise ValueError(f"Evidence has invalid status: {status!r}")
    source_url = str(evidence.get("source_url", "")).strip()
    statement = str(evidence.get("source_statement", "")).strip()
    confidence = "high" if source_url and statement else "medium"
    return Decision(
        status=status,
        operational_class=operational_class(status),
        confidence=confidence,
        basis=statement or "explicit evidence record",
        evidence_type=(
            "official_source_declaration"
            if source_url
            else "maintainer_evidence_record"
        ),
        source_url=source_url,
    )


def classify_candidate(
    code: str,
    aliases: Iterable[str],
    level: int,
    evidence: dict[str, Any] | None = None,
) -> Decision:
    explicit = explicit_evidence_decision(evidence)
    if explicit is not None:
        return explicit

    values = [normalise(alias) for alias in aliases if alias]
    combined = " ".join(values)
    alias_set = set(values)

    if code == "F":
        return Decision(
            "friendly",
            "friendly",
            "high",
            "dedicated source friendly code",
            "dedicated_source_code",
        )

    if any(re.search(pattern, combined) for pattern in OFFICIAL_CONSEQUENCE_PATTERNS):
        return Decision(
            "competitive",
            "competitive",
            "high",
            "official qualification, playoff or league consequence",
            "official_consequence_rule",
        )

    if alias_set & EXACT_FRIENDLY_EXCEPTIONS:
        return Decision(
            "friendly",
            "friendly",
            "high",
            "exact friendly-format exception",
            "exact_friendly_exception",
        )

    if any(re.search(pattern, combined) for pattern in OFFICIAL_STRUCTURE_PATTERNS):
        return Decision(
            "competitive",
            "competitive",
            "high",
            "recognised official championship or games structure",
            "official_structure_rule",
        )

    if any(re.search(pattern, combined) for pattern in FRIENDLY_SIGNAL_PATTERNS):
        return Decision(
            "friendly",
            "friendly",
            "high",
            "unambiguous friendly, exhibition or commemorative naming",
            "friendly_name_rule",
        )

    if level >= 2:
        return Decision(
            "competitive",
            "competitive",
            "medium",
            "source importance level 2-4 without friendly evidence",
            "source_importance_level",
        )

    return Decision(
        DEFAULT_STATUS,
        DEFAULT_MODEL_CLASS,
        "low",
        "no decisive official or friendly evidence",
        "unresolved_default",
    )


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tournaments = payload.get("tournaments")
    if not isinstance(tournaments, dict):
        raise ValueError("Registry is missing the tournaments mapping.")
    return payload


def load_model_classes(path: Path) -> dict[str, str]:
    payload = load_registry(path)
    result: dict[str, str] = {}
    for code, entry in payload["tournaments"].items():
        status = str(entry.get("status", DEFAULT_STATUS))
        result[str(code)] = str(
            entry.get("operational_class", operational_class(status))
        )
    return result


def _in_override(date_text: str, override: dict[str, Any]) -> bool:
    first = str(override.get("effective_from", "0000-00-00"))
    last = str(override.get("effective_to", "9999-99-99"))
    return first <= date_text <= last


def classify_match(
    code: str,
    date_text: str,
    registry: dict[str, Any],
) -> str:
    entry = registry.get("tournaments", {}).get(code)
    if not isinstance(entry, dict):
        return DEFAULT_MODEL_CLASS
    for override in entry.get("overrides", []):
        if isinstance(override, dict) and _in_override(date_text, override):
            return operational_class(
                str(override.get("status", DEFAULT_STATUS))
            )
    status = str(entry.get("status", DEFAULT_STATUS))
    return str(entry.get("operational_class", operational_class(status)))


def classify_runtime(
    code: str,
    date_text: str,
    registry: dict[str, Any],
    *,
    aliases: Iterable[str] = (),
    level: int = 1,
    evidence: dict[str, Any] | None = None,
) -> str:
    entry = registry.get("tournaments", {}).get(code)
    if isinstance(entry, dict):
        return classify_match(code, date_text, registry)
    return classify_candidate(
        code,
        aliases or (code,),
        level,
        evidence,
    ).operational_class


def runtime_is_friendly(
    code: str,
    date_text: str,
    registry: dict[str, Any],
    *,
    aliases: Iterable[str] = (),
    level: int = 1,
    evidence: dict[str, Any] | None = None,
) -> bool:
    return classify_runtime(
        code,
        date_text,
        registry,
        aliases=aliases,
        level=level,
        evidence=evidence,
    ) == "friendly"


def is_friendly(
    code: str,
    date_text: str,
    registry: dict[str, Any],
) -> bool:
    return classify_match(code, date_text, registry) == "friendly"


def count_matches(source: Path) -> dict[str, int]:
    unique: dict[tuple[str, ...], str] = {}
    pages = source / "elo_pages"
    for path in sorted(pages.glob("*.tsv")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            fields = line.split("\t")
            if len(fields) != 16:
                raise ValueError(
                    f"{path}:{line_number} has {len(fields)} fields, expected 16"
                )
            unique.setdefault(tuple(fields[:9]), fields[7])

    counts: dict[str, int] = {}
    for code in unique.values():
        counts[code] = counts.get(code, 0) + 1

    supplemental = source / "supplemental_results.csv"
    if supplemental.exists():
        with supplemental.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                code = str(row.get("tournament_code", "")).strip()
                if code:
                    counts[code] = counts.get(code, 0) + 1
    return counts


def validate_registry(payload: dict[str, Any]) -> None:
    tournaments = payload["tournaments"]
    for code, entry in tournaments.items():
        status = str(entry.get("status", ""))
        model_class = str(entry.get("operational_class", ""))
        if status not in VALID_STATUSES:
            raise ValueError(f"{code}: invalid status {status!r}")
        if model_class not in VALID_MODEL_CLASSES:
            raise ValueError(
                f"{code}: invalid operational class {model_class!r}"
            )
        if model_class != operational_class(status):
            raise ValueError(
                f"{code}: operational class conflicts with status {status!r}"
            )
        if status == "friendly" and not entry.get("basis"):
            raise ValueError(f"{code}: friendly entry lacks a basis")
        for override in entry.get("overrides", []):
            if str(override.get("status", "")) not in VALID_STATUSES:
                raise ValueError(f"{code}: override has invalid status")

    for code in PROTECTED_COMPETITIVE_CODES:
        if code in tournaments and tournaments[code]["status"] != "competitive":
            raise ValueError(f"Protected official code {code} is not competitive")
    for code in PROTECTED_FRIENDLY_CODES:
        if code in tournaments and tournaments[code]["status"] != "friendly":
            raise ValueError(f"Protected friendly code {code} is not friendly")


def audit(
    source: Path,
    config: Path,
    registry_path: Path,
    evidence_path: Path | None,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    validate_registry(registry)
    stored = registry["tournaments"]

    aliases = merge_aliases(
        read_aliases(source / "en.tournaments.tsv"),
        read_supplemental_names(source / "supplemental_tournaments.json"),
    )
    levels = read_levels(config / "elo_matches.json")
    evidence = read_evidence(evidence_path)
    match_counts = count_matches(source)

    all_codes = sorted(
        set(stored) | set(aliases) | set(levels) | set(match_counts)
    )
    rows: list[dict[str, Any]] = []
    new_codes: list[str] = []
    changed_names: list[str] = []

    for code in all_codes:
        current_aliases = aliases.get(code, [])
        level = int(levels.get(code, 0 if code == "F" else 1))
        if code in stored:
            entry = stored[code]
            status = str(entry["status"])
            model_class = str(entry["operational_class"])
            confidence = str(entry.get("confidence", ""))
            basis = str(entry.get("basis", "registry entry"))
            evidence_type = str(entry.get("evidence_type", "registry"))
            source_url = str(
                entry.get("evidence", {}).get("source_url", "")
            )
            stored_aliases = {
                normalise(value)
                for value in entry.get("aliases", [])
                if value
            }
            current_normal = {
                normalise(value)
                for value in current_aliases
                if value
            }
            if current_normal and not current_normal.issubset(stored_aliases):
                changed_names.append(code)
            origin = "registry"
        else:
            decision = classify_candidate(
                code,
                current_aliases or [code],
                level,
                evidence.get(code),
            )
            status = decision.status
            model_class = decision.operational_class
            confidence = decision.confidence
            basis = decision.basis
            evidence_type = decision.evidence_type
            source_url = decision.source_url
            origin = "new-code rule"
            new_codes.append(code)

        rows.append(
            {
                "code": code,
                "name": (
                    current_aliases[0]
                    if current_aliases
                    else stored.get(code, {}).get("name", code)
                ),
                "aliases": current_aliases,
                "wfer_level": level,
                "status": status,
                "operational_class": model_class,
                "confidence": confidence,
                "basis": basis,
                "evidence_type": evidence_type,
                "source_url": source_url,
                "origin": origin,
                "matches": int(match_counts.get(code, 0)),
                "active": bool(
                    code in aliases
                    or code in levels
                    or code in match_counts
                ),
            }
        )

    status_counts = {
        status: sum(1 for row in rows if row["status"] == status)
        for status in sorted(VALID_STATUSES)
    }
    match_status_counts = {
        status: sum(
            int(row["matches"])
            for row in rows
            if row["status"] == status
        )
        for status in sorted(VALID_STATUSES)
    }
    model_counts = {
        model_class: sum(
            int(row["matches"])
            for row in rows
            if row["operational_class"] == model_class
        )
        for model_class in sorted(VALID_MODEL_CLASSES)
    }

    return {
        "schema_version": 1,
        "registry_methodology_version": registry.get(
            "methodology_version", ""
        ),
        "summary": {
            "codes": len(rows),
            "matches": sum(int(row["matches"]) for row in rows),
            "status_code_counts": status_counts,
            "status_match_counts": match_status_counts,
            "model_match_counts": model_counts,
            "new_codes": len(new_codes),
            "changed_name_codes": len(changed_names),
            "unknown_model_default": DEFAULT_MODEL_CLASS,
        },
        "new_codes": new_codes,
        "changed_name_codes": changed_names,
        "rows": rows,
        "model_classes": {
            row["code"]: row["operational_class"]
            for row in rows
        },
    }


def write_outputs(payload: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "tournament_classification_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    (output / "tournament_model_classes.json").write_text(
        json.dumps(
            payload["model_classes"],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    rows = payload["rows"]
    fields = (
        "code",
        "name",
        "aliases",
        "wfer_level",
        "status",
        "operational_class",
        "confidence",
        "basis",
        "evidence_type",
        "source_url",
        "origin",
        "matches",
        "active",
    )
    with (
        output / "tournament_classification_audit.csv"
    ).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            value = dict(row)
            value["aliases"] = " | ".join(row["aliases"])
            writer.writerow({field: value[field] for field in fields})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("source"))
    parser.add_argument("--config", type=Path, default=Path("config"))
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/tournament_classification.json"),
    )
    parser.add_argument("--evidence", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/tournament-classification"),
    )
    parser.add_argument("--fail-on-any-new", action="store_true")
    parser.add_argument(
        "--fail-on-new-uncertain",
        action="store_true",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = audit(
        args.source,
        args.config,
        args.registry,
        args.evidence,
    )
    write_outputs(payload, args.output)

    summary = payload["summary"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    for code in payload["new_codes"]:
        row = next(
            item for item in payload["rows"] if item["code"] == code
        )
        print(
            "::warning::New tournament "
            f"{code} ({row['name']}) => status={row['status']}, "
            f"model={row['operational_class']}"
        )
    for code in payload["changed_name_codes"]:
        print(
            "::warning::Tournament aliases changed for "
            f"{code}; review the registry entry."
        )

    if args.fail_on_any_new and payload["new_codes"]:
        raise SystemExit(2)
    if args.fail_on_new_uncertain:
        uncertain = [
            code
            for code in payload["new_codes"]
            if next(
                row
                for row in payload["rows"]
                if row["code"] == code
            )["status"]
            == "uncertain"
        ]
        if uncertain:
            raise SystemExit(3)


if __name__ == "__main__":
    main()
