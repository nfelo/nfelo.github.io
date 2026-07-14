#!/usr/bin/env python3
"""Create a single non-archive PowerShell repository bootstrapper."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INCLUDE = (
    ".github/workflows/pages.yml",
    ".gitignore",
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "requirements.txt",
    "config/bakeoff-results.json",
    "config/elo_matches.json",
    "config/source_slugs.txt",
    "docs/great-elo-bakeoff.md",
    "scripts/build_site.py",
    "scripts/fetch_sources.py",
    "scripts/ledger.py",
    "scripts/model.py",
    "public/.nojekyll",
    "public/index.html",
    "public/assets/app.js",
    "public/assets/styles.css",
    "tests/test_build.py",
)


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    lines = [
        "# Network Football Elo: non-archive repository bootstrap",
        "# Generated from the tested project. This file contains plain text only.",
        "param(",
        "  [string]$Destination = (Join-Path $env:USERPROFILE 'Documents\\NetworkFootballElo')",
        ")",
        "$ErrorActionPreference = 'Stop'",
        "New-Item -ItemType Directory -Force -Path $Destination | Out-Null",
        "$Files = [ordered]@{",
    ]
    for relative in INCLUDE:
        encoded = base64.b64encode((ROOT / relative).read_bytes()).decode("ascii")
        lines.append(f"  {ps_quote(relative)} = {ps_quote(encoded)}")
    lines.extend(
        [
            "}",
            "foreach ($Entry in $Files.GetEnumerator()) {",
            "  $Target = Join-Path $Destination $Entry.Key",
            "  $Parent = Split-Path -Parent $Target",
            "  New-Item -ItemType Directory -Force -Path $Parent | Out-Null",
            "  [IO.File]::WriteAllBytes($Target, [Convert]::FromBase64String($Entry.Value))",
            "}",
            "Write-Host ('Created {0} project files in {1}' -f $Files.Count, $Destination)",
            "Write-Host 'Open that folder in Codex. The first GitHub Actions run will fetch and validate the historical TSV source.'",
            "",
        ]
    )
    args.output.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
