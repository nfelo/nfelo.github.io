# Club update release — 26 October 2026

The single-file Termux installer updates the code in nfelo/nfelo.github.io, enables
V10_CLUBS_ENABLED and dispatches the existing club workflow. It sends only changed
code files through GitHub's API; it does not clone or push the large match archive
on the phone. GitHub restores the existing state, performs the corrected replay,
exports the club site and requests the existing Pages deployment. Later updates
run automatically at 05:45, 14:45 and 22:45 UTC.

## Changes

- FotMob, ESPN and Soccerway replace the old narrow feed list. Stable provider
  identities, agreeing-match reconciliation and overlapping seasons fill holes.
- The registry has 566 provider routes. These overlap; they are NOT 566 distinct
  competitions or a completeness claim. Thirty GSA domestic routes and an official
  OFC route are enabled. GSA follows the competition's season menu and reconciles
  four rounds per refresh, persisting progress and retrying failed rounds.
- The estimated strength is now published directly. Uncertainty is separate;
  tier one's fixed reference contributes no extra division uncertainty.
- Actual second-leg football wins are retained when a level aggregate leads to
  penalties. Shootout kicks do not become football goals.
- Agreeing providers share one result and one upcoming fixture. Conflicts and
  unresolved identities remain held with source health and backfill progress.
- Model/asset changes invalidate the appropriate caches. Unchanged observations
  do not replay the model. Saved states are accepted only with matching prefixes.
- The ledger writer uses a separate working basename; the published database is
  cold-verified. A stale writer WAL cannot be replayed over its published copy.
- Development-version branding and the obsolete uncertainty-deduction explanation
  are removed from the public club pages. The parser dependency is installed by CI.

## Measured evidence and limits

The earlier fixed chronological comparison favoured the retained hierarchical
model over plain Elo: test log loss 0.996238 vs 1.000783 over 134,476 matches.
Only 72 test matches crossed confederations; precise worldwide comparability is
not established. See model-comparison.json for configurations and subgroups.

The local full export in this conversation completed with 1,644,050 accepted
matches, matching input/output rows and zero invalid probabilities. This was
16,599 more than the latest 1,627,451-match repository snapshot. The broader
integration's accepted domestic changes covered 92 countries, not complete seasons
in all 92. A repeated cached-input update took 4.234 seconds with no replay.
Those checks used saved source observations, not an assertion that every network
route had been exercised live. The previous raw full-replay checkpoint is described
in the pass-two evidence files retained alongside this document.

A real six-request Samoa/OFC exercise retrieved 20 Samoa records and 21 OFC records.
Eight Samoa records normalized; the rest and all 21 OFC records remained held for
identity resolution. One GSA round returned HTTP 503 and remained pending for retry.
This is partial coverage, not a claim that Oceania ingestion is complete.

There remain 28,795 held source observations in the main integration, with provider
overlap. These are not 28,795 distinct missing fixtures. Historical coverage,
identity, venue and leg gaps remain. Brighton is ninth in the tested output;
Arsenal's December 2025 peak is still third. Removing the uncertainty deduction
does not establish a valid absolute ranking of different eras. No club's rating
was manually forced to a preferred rank. The legacy test requiring a South American
club always to outrank every Asian club was replaced by the actual contract:
published rating equals the estimated strength.

A transient workspace reset interrupted the national build and final complete
repository/browser checks. No successful deployment is claimed. The normal Pages
workflow still performs its national build and repository checks before publishing;
a failed run retains the previous public deployment. The installer is a concrete
update to automation and publication, not a claim that every methodological or
historical-data problem has been solved.

## Use

Save NFelo_Club_Update.sh in Android Downloads, then run in Termux:

    bash ~/storage/downloads/NFelo_Club_Update.sh

If Termux has not been granted storage access, run termux-setup-storage first.
The script installs Python/gh if needed and reuses an existing GitHub login.
It prints the workflow progress link. GitHub does the heavy work; the phone can
close Termux once dispatch succeeds. If main advances during upload, rerun the same
script. It will not force-push or overwrite unrelated code changes.

To review the embedded files without contacting GitHub:

    bash NFelo_Club_Update.sh --extract ./club-update-review
