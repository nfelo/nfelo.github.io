# Global club ratings

The Global Clubs section is an independent senior men’s club model. It does not
reuse the national-team state, covariance, parameters or rankings.

## Canonical match ledger

The independent build combines seven machine-readable source layers:

- `schochastics/football-data` supplies the broad historical top-division and
  continental backbone.
- `engsoccerdata` adds English tiers 2–8, Scottish lower tiers, Germany tier 2,
  domestic cups, playoffs and European competition metadata.
- current `openfootball/football.json` CC0 files add complete 2025/26 league
  membership for two tiers where available, repairing stale promotion and
  relegation labels before the current ranking is published.
- the current `dcaribou/transfermarkt-datasets` feed adds stable modern match,
  competition, round and club identifiers.
- `BrazilianFootball/Data` adds CBF-report-derived Série A–D and Copa do Brasil
  results for 2013–2025. A compact, hash-manifested snapshot is stored in this
  repository and refreshed during the existing weekly full source pass.
- `FerrerasRP/FootballData` adds fourteen CC0 Brazilian state championships
  for 2019–2026. Its 112 JSON files are schema-checked and compacted into a
  second hash-manifested repository snapshot.
- a deliberately small reviewed layer can fill a feed-cutoff gap only when a
  row contains a direct authoritative source. The present layer supplies the
  30 May 2026 UEFA Champions League final from UEFA's match record.

The source directory supplied by the site owner at
<https://docs.ufpr.br/~mmsabino/sstatistics/fontes_pesquisa.html> is retained as
a discovery and corroboration index. Its many historical pages are not scraped
by the scheduled build because their formats and identifiers are not stable
enough for a fail-closed replay.

Every candidate match is normalised to a common schema, including date, clubs,
score, competition, competition kind, tiers, venue, cross-border status,
duration, leg, round, source and source-row reference. Overlap is removed only
after club identity resolution. The richer source wins an exact duplicate, but
its original source reference remains public.

Club identity resolution is deliberately conservative:

1. stable source identities, with federation-state scoping where names collide;
2. exact and normalised same-country labels when they are unambiguous;
3. a fixture fingerprint only when the name evidence, coverage and winning
   candidate margin all pass fixed thresholds;
4. a short, reviewed, country-scoped alias table for long/short forms;
5. competition-jurisdiction repair when a source attaches a same-named club's
   country to an otherwise unambiguous domestic fixture;
6. reviewed association repair for continental-only rows whose source omitted
   a country, never for a club that already has source-backed metadata; and
7. explicit separation when legal or sporting succession is ambiguous.

This prevents a similarly named lower-tier club from inheriting a major club’s
history. It also avoids blanket corporate-suffix merging: Wimbledon and AFC
Wimbledon, for example, remain different identities.

Placeholder teams, self-matches, same-association duplicate public histories,
unassigned countries/confederations, unequal penalty scores, the known Santa
Clara cross-country collision and an incomplete reviewed final are all
release-blocking conditions. Country-code and historical-name aliases are
canonicalised before modelling, so “Cabo Verde” and “Cape Verde Islands” do
not become separate scales.

## Hierarchical Elo state

Each club has a residual strength, each domestic tier has a relative component,
each association has a shared coefficient, and each confederation has an
independently connected global coefficient:

```text
mean_i = 1500 + club_residual_i + tier_i
         + association_coefficient_i + confederation_coefficient_i
rating_i = mean_i - uncertainty_penalty × standard_error_i
```

Same-tier domestic matches move the two club residuals. Cross-tier domestic
matches allocate 45% of the update to the two tier levels and 55% to the clubs.
Same-confederation cross-border matches allocate 15% to the two associations
and 85% to the clubs, so one elite participant cannot be counted again across
its whole domestic league. Eligible inter-confederation matches allocate 50%
to the regional bridge and 50% to the clubs.

Tier one is fixed at zero inside every association. Lower levels start 80
points apart and can learn only their distance from tier one. This constraint
is essential: a domestic cup identifies a division gap, but cannot identify an
entire country's absolute global strength.

Association coefficients are identified at the evidence-weighted 90th
percentile inside each confederation. Global club tournaments select champions
and other leading clubs, so this elite but non-maximum anchor puts the regional
bridge on the same level as its evidence without allowing one sparse outlier to
set an entire confederation's scale.

The public table ranks the uncertainty-adjusted `rating`; forecasts use the
latent `mean`. The published lower estimate subtracts 1.25 standard errors.
Evidence decays with a 730-day half-life, and club, tier, association and
confederation prior uncertainties are retained separately. New, sparse or
inward-looking clubs are therefore ranked cautiously even when their estimated
mean is high.

The result update uses a fixed K factor of 18, a logarithmic goal-margin
multiplier, competition-kind weight and duration weight. Transfermarkt shootout
kicks are removed from the football score using its event feed; penalty
decisions are learned as reduced-weight match draws, not as ordinary goal
margin. If a source proves that penalties occurred but its mixed total cannot
be separated safely, the public score is “Draw” (`P?`) instead of an invented
number. Annual regression retains 82% of club residual, 65% of learned tier
effect, 97% of association coefficient and 96% of confederation bridge.

## Home, away and probabilities

A match forecast uses:

```text
difference = home_mean - away_mean + venue_adjustment
expected_home_score = 1 / (1 + 10 ^ (-difference / 400))
draw = draw_peak × 4 × expected_home_score × (1 - expected_home_score)
home_win = expected_home_score - draw / 2
away_win = 1 - expected_home_score - draw / 2
```

Domestic and cross-border home advantages are fitted separately. Neutral
matches receive zero. Swapping the clubs and reversing the venue swaps home and
away probabilities.

All matches on one complete date are forecast from a single frozen
start-of-day state. Only after every probability for that date has been stored
are its results combined into an update. The probabilities are therefore
pre-match and invariant to same-date input order.

## Aggregate-aware two-leg ties

Explicit first and second legs are paired before rating. A second leg receives
full weight when:

- the aggregate is level before or after it;
- the aggregate leader confirms its advantage by winning or drawing the leg;
- the match reverses which club leads the tie; or
- the source does not identify a reliable tie.

Only a controlled loss by the club that remains ahead on aggregate is
discounted. For that case:

```text
leverage = max(exp(-abs(aggregate_before) / scale),
               exp(-abs(aggregate_after) / scale))
weight = floor + (1 - floor) × leverage
```

The selected floor is `0.00` and the scale is `1.0` goal. If a club wins the
first leg 4–0 and accepts a 0–1 second-leg loss, the latter retains about 5.0%
of ordinary information. The 4–1 aggregate superiority is preserved, while the
second result is not erased.

The aggregate values are always stored from that row’s home-club perspective,
along with the final leg weight and total evidence weight.

## Coefficient selection and frozen release

The club coefficients were selected with a chronological coordinate-grid
bake-off. The replay warms up from 2000, selects ordinary coefficients on
2018–2022 log loss, and reports 2023 onward as an untouched test window.
Aggregate floor and scale are selected only on matches played within 120 days
after a controlled-loss second leg, which tests whether the adjusted rating
state improves subsequent prediction rather than rewarding an in-sample story
about the leg itself.

The exact selected constants and validation counts are stored in
`config/club_model.json`. Routine source refreshes replay those constants and do
not refit them. Any future coefficient change must be an explicit reviewed
methodology release.

## Publication schema

The static build writes:

- current club and association rankings;
- active and historical club catalogs;
- one year-opening ranking file per year;
- one complete match archive file per calendar year;
- one compact annual trajectory and match-year index per club;
- competition coverage, peaks, strongest matches, upsets, aggregate examples
  and year-opening number ones;
- full source manifests, build-time hashes, licences and limitations; and
- all fitted coefficients and validation metadata.

Large match files use an array schema published in `data/meta.json` and
`data/matches/index.json`. Calendar-year match archives are deterministic gzip
JSON and are decompressed in the browser. This keeps the complete archive
practical on static GitHub Pages while preserving every field needed by the
browser.

## Record definitions and timing

Every Records list publishes its measure, sort order, eligibility rule and
interpretation next to the data:

- **Post-match club peaks** use the highest cautious rating immediately after
  a retained match. A club needs at least 50 prior results and uncertainty no
  greater than 145 points.
- **Highest-rated matches** sum the two cautious pre-match ratings; both clubs
  must clear the same uncertainty ceiling.
- **Largest winning upsets** use `−ln(P(observed winner))` from pre-match
  probabilities. Draws, shootouts, low-information results and uncertain clubs
  are excluded.
- **Controlled second legs** are exactly the aggregate-discounted cases defined
  above, ordered from the lowest retained information weight.
- **Year-opening world No. 1** requires an active tier-one club with at least 50
  prior results and uncertainty no greater than 145. Unsupported early years
  are left unclaimed rather than filled with a local or disconnected leader.

Historical peaks are therefore post-match; strongest-match and upset evidence
is pre-match. These timing rules and known false-claim regressions are tested
before publication.

## Atomic updates and interface contract

The ledger and model are written to dedicated temporary databases, committed,
checkpointed, reopened read-only and verified. The complete static archive is
then built in a sibling directory and checked for every indexed file, profile,
year count, identity, confederation, guarded record and reviewed result before
it atomically replaces the prior archive. A failed replay is never committed or
pushed by the installer.

The club application imports the exact national NFELO critical and full style
sheets. Club-only CSS may fit the large club name plus smaller nation and
confederation context, but may not redefine the header, navigation, footer,
palette or shared controls. Desktop uses full data tables; tablet and mobile
switch long match and record rows to complete cards so no column becomes
unreachable. The same token system supplies light, dark, forced-colour,
reduced-motion and print behaviour.

## Limitations

Coverage is broad rather than literally complete. Lower tiers, state leagues,
early domestic cups and some confederations are uneven. Mutable source feeds
can publish historical corrections; their downloaded bytes and SHA-256 hashes
are recorded for each build. Identity evidence can also improve. Either change
can alter a later replay without changing the frozen coefficients.

Ratings are comparative estimates, not official classifications or betting
advice.
