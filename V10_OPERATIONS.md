# V10 club installer — 23 October 2026

This installs the saved global club ledger, unchanged frozen model, complete existing club interface, and automatic updater into `nfelo/nfelo.github.io`. It is an operational release with explicitly incomplete historical and live coverage. It does not assert the old global scientific acceptance gates have passed.

## What updates automatically

Fifteen domestic league routes are configured: England tiers 1–4; Spain, Italy, Germany, France, Portugal and Netherlands top divisions; Brazil, Japan, Australia, South Africa and Saudi Arabia top divisions. The release seed includes the tested Premier League refresh. The other configured feeds perform their first refresh after activation. Each route must establish a consistent historical competition binding. Source club IDs bind using unique exact country-scoped names or multiple distinct dated historical fixtures. Unknown or conflicting identities stay held. The site lists actual source health and held observations.

New regulation results, upcoming fixtures and corrections to previously admitted live results flow through source collection, reconciliation, the frozen rating model and the full club archive. Cup/two-leg/extra-time/shootout live adapters are not implemented in this release; the historical corpus still includes those competitions. Other worldwide competitions retain their saved snapshot. The inherited history includes 259 mixed-identity matches requiring later repair. The two different club projects have not been merged; this is the historical V10 project.

Each update checks current feed indexes and caches detailed event facts. A bounded 14-day correction window refreshes recent details. Changed scoreboard facts also refresh details. Unchanged model inputs do not trigger a rating replay. Accepted input changes currently use a complete frozen-model replay. An unavailable source retains its last successful observations; other sources proceed. Ambiguous rows cannot silently become results. The prior generation survives calculation or publication failure.

## Install using only Termux

Download and unzip `V10_RELEASE.zip` into a new folder in Downloads. Keep its files together until installation completes. If phone storage permission has not been granted, run `termux-setup-storage` once.

```sh
pkg install -y python git gh unzip
unzip "$HOME/storage/downloads/V10_RELEASE.zip" -d "$HOME/storage/downloads/V10_RELEASE_20261023"
bash "$HOME/storage/downloads/V10_RELEASE_20261023/V10_INSTALL.sh" --repo "$HOME/v10" --no-push
```

The installer clones the existing repository if `$HOME/v10` is absent. An existing target must have the correct origin. It verifies every embedded payload file, backs up replaced club files, preserves the national page and permanent `pages.yml`, and leaves changes for review. Repeating the same installation is harmless and does not reset updated data. `--verify-only` verifies the embedded payload without installing; `--no-network` requires an existing repository. No DuckDB installation is needed on the phone for installation or preview.

Preview in Termux:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory "$HOME/v10/public"
```

Open `http://127.0.0.1:8765/clubs/` in the phone browser. Stop the preview with Ctrl-C.

## Publish and enable updates when you choose

The assistant has not pushed, deployed or enabled scheduling. Installation also does not perform those actions. These commands are the explicit activation step after reviewing the local changes:

```sh
cd "$HOME/v10"
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
git status --short
git add -- scripts/v10 club-state public/clubs .github/workflows/v10-clubs.yml V10_UPDATE.sh V10_OPERATIONS.md V10_RELEASE.json .gitignore
git commit --only -m "Install self-updating V10 clubs" -- scripts/v10 club-state public/clubs .github/workflows/v10-clubs.yml V10_UPDATE.sh V10_OPERATIONS.md V10_RELEASE.json .gitignore
git pull --rebase origin main
git push origin HEAD:main
gh variable set V10_CLUBS_ENABLED --body true --repo nfelo/nfelo.github.io
gh workflow run v10-clubs.yml --repo nfelo/nfelo.github.io
```

If Git reports existing edits, a conflict, authentication or branch protection, resolve that reported issue before continuing. The updater uses an independent workflow at 05:45, 14:45 and 22:45 UTC. GitHub can delay scheduled starts. It commits only the saved club state, club pages and update receipt, then dispatches the unchanged Pages workflow. The existing national build validates and retains the prebuilt club archive. A GitHub Actions bot push alone does not trigger a Pages build, which is why the explicit dispatch is included.

Pause automatic updates without deleting the installed site:

```sh
gh variable set V10_CLUBS_ENABLED --body false --repo nfelo/nfelo.github.io
```

Manual workflow runs remain available. Inspect runs with `gh run list --workflow v10-clubs.yml --repo nfelo/nfelo.github.io`.

## Local calculation and recovery

The automatic calculation runs on GitHub's Ubuntu/Python 3.12 runner with `duckdb==1.4.0`. For a local Linux/Codespaces calculation, install that dependency and run `bash V10_UPDATE.sh`. Native Android calculation has not been tested; the installer and static preview use standard Python only.

`club-state` contains deterministic Parquet partitions, the source observation database and checksums. These reconstruct the saved native databases without recalculating history. Runtime databases and raw HTTP caches live in the ignored `.v10-runtime` folder. To rebuild a damaged runtime, stop any running updater and rename that folder; the next update restores from `club-state`. Do not delete `club-state` or `public/clubs`.

Installer backups are in `.v10-install-backups`. Installation leaves all remote history and the national model untouched. If an installation fails, it restores the club paths it replaced. Store the release ZIP separately so phone storage cleanup cannot remove the only copy.

## Validation and limits

The included verification receipt records the actual tested platform, source results, integration tests, full native-state restoration comparison, installation repeat, national-site compatibility and interface data checks. Browser visual testing is reported separately and is not assumed. The code is prepared for Termux installation; no Android device was available for execution. Coverage is described by source and competition rather than assumed from the overall match count. This is the delivered installer; further historical coverage work is not a prerequisite for running it.

Technical references: https://docs.github.com/en/actions/concepts/security/github_token and https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow .
