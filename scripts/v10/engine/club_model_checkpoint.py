#!/usr/bin/env python3
"""Atomic end-of-day checkpoints for resumable club-model replay."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import duckdb


CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_FILES = {
    "checkpoint.json",
    "model-state.json",
    "rated-matches.parquet",
    "year-openings.parquet",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def strict_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value} in {path}")

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint JSON must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _checkpoint_route(
    input_connection: duckdb.DuckDBPyConnection,
    checkpoint_day: str,
) -> tuple[int, str]:
    row = input_connection.execute(
        """SELECT matches_through_day,prefix_sha256
           FROM model_route_days WHERE day=?""",
        [checkpoint_day],
    ).fetchone()
    if row is None:
        raise ValueError(f"checkpoint day {checkpoint_day} is absent from model input")
    return int(row[0]), str(row[1])


def validate_checkpoint(
    path: Path,
    input_connection: duckdb.DuckDBPyConnection,
    identity: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Cold-validate a checkpoint against the current model-input prefix."""

    if not path.is_dir():
        raise ValueError(f"model checkpoint is not a directory: {path}")
    names = {item.name for item in path.iterdir()}
    if names != CHECKPOINT_FILES:
        raise ValueError(
            f"model checkpoint has unexpected files: {sorted(names ^ CHECKPOINT_FILES)}"
        )
    metadata = strict_json(path / "checkpoint.json")
    state = strict_json(path / "model-state.json")
    if metadata.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("unsupported model checkpoint container schema")
    if metadata.get("identity") != identity:
        raise ValueError("model checkpoint identity does not match current input")
    checkpoint_day = str(metadata.get("checkpoint_day") or "")
    matches, prefix_hash = _checkpoint_route(input_connection, checkpoint_day)
    if (
        int(metadata.get("matches") or -1) != matches
        or metadata.get("input_prefix_sha256") != prefix_hash
        or state.get("checkpoint_day") != checkpoint_day
        or int(state.get("processed") or -1) != matches
    ):
        raise ValueError("model checkpoint route metadata does not match current input")

    files = metadata.get("files")
    if not isinstance(files, dict) or set(files) != CHECKPOINT_FILES - {"checkpoint.json"}:
        raise ValueError("model checkpoint file manifest is incomplete")
    for name, expected in files.items():
        source = path / name
        if (
            not source.is_file()
            or source.stat().st_size != expected.get("bytes")
            or sha256_file(source) != expected.get("sha256")
        ):
            raise ValueError(f"model checkpoint file failed hash validation: {name}")

    connection = duckdb.connect()
    try:
        rated = int(connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(path / "rated-matches.parquet")],
        ).fetchone()[0])
        openings = int(connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(path / "year-openings.parquet")],
        ).fetchone()[0])
        maximum = connection.execute(
            "SELECT max(day) FROM read_parquet(?)",
            [str(path / "rated-matches.parquet")],
        ).fetchone()[0]
    finally:
        connection.close()
    if (
        rated != matches
        or rated != int(metadata.get("tables", {}).get("rated_matches", -1))
        or openings != int(metadata.get("tables", {}).get("year_openings", -1))
        or maximum is None
        or str(maximum) != checkpoint_day
    ):
        raise ValueError("model checkpoint Parquet rows do not match its state")
    return metadata, state


def write_checkpoint(
    root: Path,
    state: dict[str, Any],
    input_connection: duckdb.DuckDBPyConnection,
    output_connection: duckdb.DuckDBPyConnection,
    identity: dict[str, str],
) -> Path:
    checkpoint_day = str(state["checkpoint_day"])
    matches, prefix_hash = _checkpoint_route(input_connection, checkpoint_day)
    if int(state["processed"]) != matches:
        raise ValueError("model state is not at the end of its input day")
    root.mkdir(parents=True, exist_ok=True)
    name = f"{checkpoint_day}-{prefix_hash[:12]}"
    target = root / name
    if target.exists():
        validate_checkpoint(target, input_connection, identity)
        return target

    temporary = Path(tempfile.mkdtemp(prefix=f".{name}.building-", dir=root))
    try:
        state_path = temporary / "model-state.json"
        rated_path = temporary / "rated-matches.parquet"
        openings_path = temporary / "year-openings.parquet"
        write_json(state_path, state)
        output_connection.execute(
            "COPY rated_matches TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(rated_path)],
        )
        output_connection.execute(
            "COPY year_openings TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(openings_path)],
        )
        opening_rows = int(output_connection.execute(
            "SELECT count(*) FROM year_openings"
        ).fetchone()[0])
        metadata = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_day": checkpoint_day,
            "matches": matches,
            "input_prefix_sha256": prefix_hash,
            "identity": identity,
            "tables": {
                "rated_matches": matches,
                "year_openings": opening_rows,
            },
            "files": {
                path.name: {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in (state_path, rated_path, openings_path)
            },
        }
        write_json(temporary / "checkpoint.json", metadata)
        validate_checkpoint(temporary, input_connection, identity)
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    print(
        f"model checkpoint: {checkpoint_day} after {matches:,} matches",
        flush=True,
    )
    return target


def select_checkpoint(
    root: Path,
    input_database: Path,
    identity: dict[str, str],
) -> dict[str, Any]:
    """Select the latest checkpoint whose complete prefix is still identical."""

    rejected: list[dict[str, str]] = []
    candidates: list[tuple[int, Path, dict[str, Any]]] = []
    if not root.is_dir():
        return {"path": None, "metadata": None, "rejected": rejected}
    connection = duckdb.connect(str(input_database), read_only=True)
    try:
        for path in sorted(root.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            try:
                metadata, _ = validate_checkpoint(path, connection, identity)
            except (OSError, ValueError, duckdb.Error) as error:
                rejected.append({"checkpoint": path.name, "reason": str(error)})
                continue
            candidates.append((int(metadata["matches"]), path, metadata))
    finally:
        connection.close()
    if not candidates:
        return {"path": None, "metadata": None, "rejected": rejected}
    _, path, metadata = max(candidates, key=lambda item: (item[0], item[1].name))
    return {"path": path, "metadata": metadata, "rejected": rejected}


def restore_checkpoint(
    path: Path,
    input_connection: duckdb.DuckDBPyConnection,
    output_connection: duckdb.DuckDBPyConnection,
    identity: dict[str, str],
) -> dict[str, Any]:
    _, state = validate_checkpoint(path, input_connection, identity)
    output_connection.execute(
        "CREATE TABLE rated_matches AS SELECT * FROM read_parquet(?)",
        [str(path / "rated-matches.parquet")],
    )
    output_connection.execute(
        "CREATE TABLE year_openings AS SELECT * FROM read_parquet(?)",
        [str(path / "year-openings.parquet")],
    )
    return state
