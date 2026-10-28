# Club update and calibration review — 28 October 2026

The installer restores 12,629 dated Brazilian historical results, includes the
26 October engine and input corrections, and rebuilds the club website. Install
this file directly; there is no need to install the previous release first.
The existing visual design and national-team engine are
unchanged. The club homepage now says “Club football, past and present.” The
repeated development labels, “limits visible” headline and technical publication
language have been removed. Methodology and coverage details remain on their
relevant pages.

## Completed league-calibration comparison

The fixed four-model comparison is complete. The existing coefficients were
retained because all three alternatives increased prediction error. No club or
association received a manual adjustment. The comparison used the exact same
1,690,260 corrected results and the complete historical replay for every model.

| Alternative | International log loss, 2018–2022 | International log loss, 2023–2026 |
| --- | ---: | ---: |
| Existing coefficients | 0.966406 | 0.963254 |
| Reduce association update share from 0.15 to 0.05 | 0.987041 | 0.986186 |
| Increase annual club retention from 0.82 to 0.95 | 0.973592 | 0.968387 |
| Apply both changes | 0.991228 | 0.988115 |

Lower log loss is better. Selection used 8,194 international matches in
2018–2022, subject to an all-match accuracy guard; the later review included
6,819 international matches. All-match prediction error also increased for every
alternative in both periods. The selection rule and all four candidates were
recorded before running them. No further candidates were added after inspecting
the result. These periods have been examined in previous releases, so this is
retrospective evidence, not an untouched test set or proof that every ranking is
correct.

Brighton remains ninth in the corrected snapshot. The English-ranking concern is
not declared resolved. These results do not justify a blanket reduction in
English club ratings. `league-calibration.json` contains every comparison and
`league-calibration-protocol.json` contains the baseline parameters and selection
rule. The production model and its configuration are byte-for-byte unchanged
from the verified 27 October installer.

To reproduce a candidate using the corrected frozen ledger:

```sh
PYTHONPATH=scripts/v10:scripts/v10/engine python scripts/v10/compare_league_calibration.py --input /path/to/input.duckdb --output /path/to/comparison --protocol docs/club-correction/league-calibration-protocol.json --candidate baseline
```

Repeat for `slower_league`, `longer_club_memory` and `combined`, then use the same
command with `--select` in place of `--candidate baseline`. This comparison is
separate from the scheduled updater. Routine refreshes do not refit parameters.

## Model corrections

The 26–27 October structural and historical corrections retained the predictive
coefficients. The completed 28 October comparison also retained them.
The version is `2026-10-27-historical-results`.

- Promotion or relegation transfers the old/new tier-component difference into the
  club component. A division change alone cannot increase estimated strength.
- Cup feed defaults cannot replace established domestic-league membership. Two
  contradictory league tiers on the same day stop the update for review.
- Recentring country components transfers the equal offset to the confederation
  component. This bookkeeping operation now preserves every club's total strength
  and every forecast; previously it could change cross-region comparisons.
- Competitive continental guest appearances across confederations count as regional
  evidence, as do intercontinental and global tournaments. Domestic cross-border
  leagues retain their existing treatment.
- Inferred cup membership is used for rating calculations without overwriting the
  source tier fields in the rated ledger. This fixes an input/output validation
  failure that would otherwise stop automatic updates. Predictions are unchanged
  by this record-preservation correction.

The previous release's direct publication of estimated strength, separate
uncertainty, second-leg score handling and caching fixes are retained.

## Reviewed input repairs

The audit used repository snapshot
`eaa1aa0198f5dd8f15bf1a7681988d5e1657b127` and its checksummed Parquet state. The
repair manifest records the full before/after row and evidence for each change.
A repair applies only when the current row exactly matches the reviewed original;
a subsequent source correction is preserved and reported. Repeated application
made zero further changes. The engine configuration pins the repair-file checksum.

| Change | Count |
| --- | ---: |
| Remove duplicate Brazilian results with a retained, matching CBF-derived row within one day | 2,112 |
| Restore Brazilian state identities for Botafogo PB/SP rows assigned to Botafogo RJ | 260 |
| Remove English fixtures incorrectly dated in 2025 when the matching 2026 result is retained | 74 |
| Hold contradictory or ambiguous English dates for review | 32 |
| Assign Spanish second-division reserve matches to Real Sociedad II | 11 |
| Restore historical Intercontinental Cup classification and neutral Japan venues from 1980 | 64 |
| Correct Heart of Midlothian's association from England to Scotland | 1 club |

There were 2,554 applied changes. All 2,112 removed Brazilian duplicates have a
retained matching result after every other repair. The 32 held rows are listed in
data health; no replacement date was guessed. The accepted replay contains
**1,677,631 matches**, compared with 1,679,849 in the audit input. All 134 conflicting
same-day league-tier cases in that input are resolved by the evidence-backed
repairs and holds.

## Measured effect

`structural-comparison.json` contains paired match comparisons, model hashes,
current rankings and historical peaks. These are retrospective, previously
inspected periods, **not a new untouched holdout**. Lower log loss is better.

| 2023–2026 paired matches | Matches | Before | Corrected |
| --- | ---: | ---: | ---: |
| All | 186,374 | 1.005035 | 1.003173 |
| International club competitions | 6,819 | 0.964653 | 0.963287 |
| English clubs against foreign opponents | 350 | 0.869278 | 0.865568 |
| Between confederations | 82 | 0.883658 | 0.890203 |

Overall and English-club prediction error improved slightly. The recent
interconfederation sample became slightly worse; the 2018–2022 sample improved.
These small samples do not establish precise worldwide calibration.

In the corrected snapshot, Al Ahly (Egypt) peaks at 1,674.2, below several South
American clubs. Arsenal's December 2025 peak moves from fifth to seventh at
1,858.1. **Brighton remains ninth in the current rankings.** There was no manual
club, country or peak adjustment to obtain a preferred order. The English-ranking
concern is not claimed to be resolved.

## Restored Brazilian history

The supplement uses 74 RSSSF Brasil season pages: Taça Brasil 1959–1968,
Robertão 1967–1970, the national championship 1971–1976, and the Paulista and
Carioca championships 1950–1976. It adds **12,629 matches and 14 clubs**, bringing
the replay to **1,690,260 matches**. Each result retains its source URL; source
page hashes and the supplement checksum are recorded. RSSSF Brasil is credited
in the payload. This is additional coverage, not a claim that all Brazilian
historical competitions are now complete.

Santos now peaks in December 1962 at approximately **1,855**, the highest
non-European club peak in this snapshot. This results from the restored matches;
no club-specific bonus or predictive coefficient change was applied.
`history-comparison.json` records the precise rankings and metrics. The overall
2018–2026 prediction loss is effectively unchanged and slightly worse after the
addition; this release does not claim a predictive accuracy improvement.
Brighton remains ninth, so the English-ranking concern remains open.

The importer distinguishes state identities, expands dated two-leg score lists,
excludes unplayed or suspended results, and holds conflicts. On this snapshot it
holds 43 conflicting rows and skips one already present result. Applying it again
adds zero matches and zero clubs, while retaining later corrections. The Paulista
1962 source summary disagrees with its dated score list; the importer preserves
the score list and documents the discrepancy in `history-validation.json`.

The historical supplement is installed automatically during the next full club
update. It is a fixed, reviewed archive import. The existing current-results
feeds continue refreshing automatically. Other inherited identity, venue, date
and coverage gaps remain. `model-comparison.json` describes an earlier release;
`history-validation.json` describes this release's full replay and export.

## Automatic updates and validation

The existing 566 provider routes, including GSA domestic and official OFC routes,
remain enabled. Routes overlap and do not imply 566 distinct or fully covered
competitions. FotMob, ESPN and Soccerway observations are reconciled, source
failures remain retryable, and backfill progress is persisted. Routine updates do
not refit the model. Input changes invalidate affected checkpoints; unchanged
inputs can reuse the frozen replay.

All **73 updater and comparison tests passed**, including regressions for source-field preservation,
historical parsing, idempotent imports, tier transitions, cup membership,
cross-confederation guests, country centring and installer upgrades from the
previous release. The two added tests verify that measurement does not change
ratings and that later results cannot select a runner-up. The verified 27 October
full replay checks every source field against the rated
ledger and exports the complete club archive. JavaScript syntax, Python compilation
and patch whitespace checks passed.
See `history-validation.json` for the complete static-export result and the exact
scope of local validation. The full national build and complete repository/browser
suite were not rerun locally in this partial checkout. The existing Pages workflow
runs its build, repository tests and browser-code syntax check before deployment.
No successful remote deployment is asserted by this report.

## Install

Download the new `NFelo_Club_Update.sh` into Android Downloads and run in Termux:

```sh
bash ~/storage/downloads/NFelo_Club_Update.sh
```

If storage access has not been granted, run `termux-setup-storage` once. The script
installs Python and GitHub CLI if needed, reuses your GitHub login, uploads only
changed code and dispatches `v10-clubs.yml`. It does not clone or push the large
match archive on the phone. GitHub performs the replay and publication; Termux can
be closed once the workflow has started. The existing schedule continues at
05:45, 14:45 and 22:45 UTC.

The installer checks each target file against the reviewed base, the exact
26 October release, or the desired content,
rechecks the branch before advancing it, and never force-pushes. If only routine
data updates advance main during installation, rerun this script. Unexpected code
changes cause it to stop before changing the branch.

To inspect the embedded files without changing GitHub:

```sh
bash NFelo_Club_Update.sh --extract ./club-update-review
```
