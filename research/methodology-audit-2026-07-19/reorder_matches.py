#!/usr/bin/env python3
"""Create a result-independent within-date ordering for the audit evaluator."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    comments: list[str] = []
    rows: list[list[str]] = []
    for line in args.source.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            comments.append(line)
        elif line:
            rows.append(line.split("\t"))
    # day, unordered pair, orientation, stable original identifier. No score,
    # published rating, venue, or competition field participates in ordering.
    rows.sort(key=lambda row: (
        int(row[1]), min(int(row[5]), int(row[6])), max(int(row[5]), int(row[6])),
        int(row[5]), int(row[6]), int(row[0]),
    ))
    text = "\n".join(comments + ["\t".join(row) for row in rows]) + "\n"
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
