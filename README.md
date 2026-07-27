# Network Football Elo

[NFELO](https://nfelo.github.io/) is a static, searchable rating and prediction
site for senior men's international football. It covers results from 1872 to
the present, current and historical rankings, tournament snapshots, every
source match, team peaks, number-one chronology and totals, top match
instances, largest upsets, Best tournaments, team comparison and a date-aware
probability calculator.

## What the model publishes

NFELO publishes one rating everywhere: current rankings, rankings on historical
dates, team peaks, team pages and match records all use the same
evidence-adjusted network rating. A hidden attack/defence state refines match
probabilities only; it never changes ratings, ranking order, peaks or points
gained from results.

**Current methodology version:** `2026-07-27-country-home-dependence`.

Tournament snapshots use the same published rating immediately before and
after each completed edition. Tournament rating change and Best tournaments
include only published movement from that edition’s matchdays, excluding annual
recalibration and unrelated results. Tables use the team name active during the
edition; selectors use joined lineage labels so successor names remain easy to
find.

The rating state is a full-covariance dynamic Gaussian opponent network. The
base-10 Elo expectation remains the observation link, while the model also
represents uncertainty shared through common opponents, era-specific home and
draw conditions, time-varying country venue profiles, an active-pool debut
prior and goal-margin information.
Competitive and unresolved results use information ratio 1.00; evidence-backed friendlies use 0.78621.

Every match with a complete shared date is forecast from one frozen start-of-day
state. Same-date debutants receive the same pre-date pool prior, and all results
on that date are learned in a single order-invariant Gaussian update. Historical
rows without a complete day remain in their source sequence.

## The public rating

Recent opponent weights have an eight-year half-life. Their effective distinct
count gives reliability `rho_i = N_i / (N_i + 4)`. If `B` is the mean latent
strength of the ten strongest eligible active teams, the published rating is:

```text
M_i  = 2000 + rho_i × (mu_i - B)
NR_i = M_i - 1.6448536269514715 × sqrt(Sigma_ii)
```

After every complete matchday, a compact global snapshot stores the network
mean and marginal variance for every eligible team. This matters because the
full covariance update can move a connected team even when that team did not
play. Current Rankings and the latest History view are reconstructed from the
same global state and checked for identical membership, order and displayed
values.

For a ranking or prediction date after a team's latest appearance, the model
projects its marginal variance forward without changing its latent mean:

```text
Sigma_ii(as of t) = Sigma_ii(last match) + 19.750212594949737² × Delta t
```

This gradually lowers the cautious public rating while a recently active team
is inactive and widens future-match uncertainty. Ranking eligibility means an
appearance in the selected calendar year or one of the preceding four calendar
years. The projection is read-only: completed matchday ratings, historical
peaks and the fitted replay are not rewritten.

The marginal variance `Sigma_ii` is retained deliberately. Cancelling uncertainty
shared with a contemporaneous elite reference can make a small, inward-looking
historical network appear far more certain—and therefore far stronger across
eras—than the evidence warrants. The latent posterior mean remains available
inside the forecast calculation but is not published as a competing ranking.
Because match forecasts use that latent strength distribution, venue and the
attack/defence layer, the higher-rated team is not guaranteed to have the higher
win probability. The rating is the cautious ranking output; the forecast is the
full predictive output for one match.

For an eligible match instance:

```text
Q_ij = M_i + M_j
       - 1.6448536269514715
         × sqrt(Sigma_ii + Sigma_jj + 2 Sigma_ij)
```

Both participants need 30 prior matches. Every match instance is retained;
repeat pairings are not collapsed.

## Country-specific home and away profiles

A non-neutral forecast combines the worldwide home baseline for the football
era with one causal, time-varying value for each country:

```text
C_ij = h × (d_i + d_j) / 2
delta = a(year) × (mu_i - mu_j) + H(year) × h + C_ij
```

Here `h` is `+1` when the first-listed team is home, `-1` when the
second-listed team is home and `0` at a neutral venue. A positive `d_i`
contributes `+d_i/2` when team `i` hosts and `-d_i/2` from its own
perspective when it visits. Neutral matches receive no era or country venue
adjustment and do not update the country venue state.

Each `d_i` begins at zero with a 60-point prior standard deviation. Between
appearances, its mean and posterior precision revert toward that prior with a
40-year half-life. This allows genuine country differences to change through
time without treating short runs or old conditions as permanent national
traits. Non-neutral competitive results have learning ratio 1; evidence-backed
friendlies use 0.78621. All matches on one complete date use frozen pre-date
profiles before their venue evidence is combined.

The source ledger lists the host first in 38,769 non-neutral rows and second in
only one. Independent country host and visitor parameters are therefore not
cleanly identifiable. The audit still tested host-only, away-only, separate
host/away, neutral, non-home, global and combined structures. The strongest
earlier-only selection was one shared country “home dependence” value divided
equally between hosting and visiting. Adding a country-specific neutral term
or adding venue-state posterior variance to match variance made forecasts
worse.

Team pages publish the selected-date dependence estimate, hosting and away
components, neutral value, standard error, 95% interval, evidence count and
reliability. These numbers affect match expectations, not the public ranking
formula directly.

## Forecast probabilities

The network forecast integrates uncertainty in the strength difference and
uses separate friendly and competitive probability temperatures. A parallel
team-specific attack/defence model produces a score-based W/D/L vector. Annual
draw calibration, probability powers and the pool weight are fitted using only
the preceding eight complete calendar years. Before use, the four fitted
coefficients are placed on a fixed six-decimal publication grid. This removes
platform-level optimiser jitter without changing any displayed probability.

The score correction is boundary-gated: NFELO moves toward the pooled forecast
only as far as it can without changing the network model's most likely W/D/L
outcome. The exact-score table is then raked so its win, draw and loss regions
sum to the displayed final probabilities; omitted scorelines above 5–5 remain
in the reported tail mass.

Completed matches retain the exact pre-match probability vector. The arbitrary
historical calculator reconstructs the exact selected-date marginal states, but
the static archive does not retain every historical off-diagonal covariance;
those W/D/L values are therefore labelled as approximations. Its rating-effect
table is an isolated one-match scenario that holds the elite reference,
opponent breadth and other same-date results fixed.

The 0.78621 friendly multiplier applies to the opponent-network update before
the joint matchday calculation. It scales both gradient and curvature, so a
friendly's displayed point movement is not mechanically 78.6% of an otherwise
similar competitive match.

The same friendly ratio is used when the separate country venue state learns,
but its selected update uses result surprise rather than goal margin. This was
chosen using earlier matches only; applying the main margin-weighted update to
the venue state forecast later matches less accurately.

## Chronology and publication safeguards

Every match on a complete date is forecast from the same frozen start-of-day
state. Same-date debutants receive the same prior, and all results from that
date enter one joint, order-invariant update. The attack and defence state is
also held fixed until every forecast for the date has been stored.

The probability layer keeps the largest score-based correction that does not
change the network model's most likely outcome. Exact-score probabilities are
then reconciled with the displayed win, draw and loss vector. First-published
future forecasts are stored by methodology version so later evaluation can use
probabilities recorded before the result was known.

NFELO publishes one evidence-adjusted rating for rankings, records and
historical comparisons. The latent network mean remains part of the forecast
calculation rather than appearing as a competing public table.

## Tournament classification and friendly information

Tournament importance and match class are separate. The maintained registry
contains 188 friendly codes covering 21,529 matches, 239 competitive codes
covering 30,165 matches and 233 uncertain codes covering 618 matches. Uncertain
and unknown competitions use the competitive information weight.

Every family previously placed in the fallback Other tournaments category has
been reviewed. Seventy-two source codes represent invitationals, preparation
events or friendly series; sixteen represent formal regional, federation or
multi-sport competitions. Friendly families are excluded from both Tournaments
and Best tournaments.

Under this classification, the full 52,312-match replay jointly fitted:

- friendly information ratio `0.78621`;
- friendly network temperature `0.896294991479`; and
- competitive network temperature `1.061356232973`.

The scoring period contains 46,801 forecasts from 1960 through 11 July 2026,
including 18,546 friendlies. The network-only log-loss minimum is
`0.881475145850`. At the previous ratio of `0.76064`, with both temperatures
refitted under the same classification, it is `0.881478166958`.

These are reproducible full-sample constants for the fixed ledger and
objective, not claims of equivalent population precision. Classification
evidence, future results and prospective scoring can move the preferred value.

An additional chronology-first study tested 1,650 constant, stepped and smooth
era-varying friendly ratios. Every flexible family selected on 2010–2019
worsened forecasts on untouched 2020–2026 matches. A separate 170-profile
check of friendly learning in the country venue state found no reliable
incremental era effect over one constant. NFELO therefore keeps `0.78621`
across eras rather than publishing a curve that did not generalise.

## Validation: two different evidence classes

The primary comparative result is the original five-block **nested historical
holdout** over 46,801 matches from 1960 onward:

| Model | Three-way log loss | Most-likely W/D/L correct |
| --- | ---: | ---: |
| NFELO network | **0.884219** | **59.095%** |
| Best tested scalar Elo | 0.892970 | 58.527% |
| G-Elo comparison | 0.895187 | 58.779% |
| Published World Football Elo forecast | 0.902619 | 58.804% |

Choices used earlier periods and were scored on later periods. The aggregate
result is retained, but the original fitter programs and frozen derived dataset
were not committed, so it cannot currently be reconstructed bit-for-bit.

The site also calculates a **retrospective diagnostic** on every build by
replaying the final constants through the fixed 1960–11 July 2026 window. It is
useful for checking date batching, the boundary gate and other mechanics, but
it is not a second out-of-sample estimate and must not be compared as if it were
the same experiment as the nested holdout.

The country venue release has a separate temporal study. It executed 1,949
overlapping screening fits across 16 formula structures and associated prior,
half-life, learning and predictive-variance choices. Selection used matches
through 2019. The final end-to-end replay was then scored on 6,320 untouched
matches from 2020 through 11 July 2026.

| Country venue comparison | Three-way log loss |
| --- | ---: |
| Previous final-layer replay | 0.880169 |
| Selected country-profile replay | **0.878333** |
| Improvement | **0.001836** |

The untouched-period improvement was `0.001315`. A paired year-block bootstrap
put its 95% interval at `0.000208` to `0.002607`, with 99.0% of resamples
favouring the country-profile model. All five time blocks from 1960–1979
through 2020–2026 improved. This supports adoption as an average forecast
improvement; it does not establish that every country has a non-zero effect.
The complete protocol, formula-family comparison and guardrails are in
[`research/home-advantage-2026-07-27/`](research/home-advantage-2026-07-27/).

First-published fixture probabilities are stored in
`source/prospective_forecasts.jsonl` by methodology version, source hash,
model-state hash and results-through date. That ledger supplies genuinely
prospective evidence as matches are completed.

See [Model validation](docs/model-validation.md) and the
[19 July 2026 methodology audit](docs/methodology-audit-2026-07-19.md). The
executable reproduction materials are retained under
`research/methodology-audit-2026-07-19/`.

## Automatic updates

The Pages workflow checks results and fixtures at 06:20, 15:20 and 23:20 UTC.
It validates and stages external data, replays the complete history, runs the
test suite and deploys only a verified static artifact. If input or model checks
fail, the last good site remains online.

Routine updates do not refit core rating, country-venue or score-state
structure. Country profiles continue to learn causally under the frozen
60-point prior and 40-year half-life. At each
January boundary, only the declared forecast calibration is refitted from the
preceding eight complete years, then canonicalised to six decimal places.
Every rebuild applies the tournament
classifier to new source codes; unresolved events remain competitive until
positive friendly evidence is recorded. The standalone audit command can be
run whenever a classification review report is needed.

## Local build

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/build_site.py --source source --config config --output public
python -m unittest discover --start-directory tests --verbose
node --check public/assets/app.js
python -m http.server 8000 --directory public
```

## Repository layout

- `source/` — validated results, fixtures and the prospective forecast ledger.
- `config/` — frozen deployment parameters and tournament metadata.
- `scripts/ledger.py` — identity mapping, deduplication and source ordering.
- `scripts/tournament_classification.py` — evidence registry, future-code rules and audit.
- `scripts/model.py` — date-batched opponent-network replay and public rating.
- `scripts/venue_effects.py` — causal time-varying country venue state.
- `scripts/forecast_layer.py` — hidden score state, annual calibration and gate.
- `scripts/build_site.py` — static data, history, records and fixture generation.
- `scripts/fetch_sources.py` — guarded multi-source updater.
- `public/` — GitHub Pages application shell; generated data is ignored by Git.
- `tests/` — model, data, UI and historical regression checks.
- `docs/` and `research/` — validation, audit and reproduction materials.

## Data and limitations

Historical rows and labels are based on [World Football Elo Ratings](https://eloratings.net/).
The ledger follows recorded senior international histories rather than FIFA
membership alone, so it includes some territories, regional selections and
defunct teams. Inclusion is a data-scope decision, not a statement about
political status or eligibility for a particular competition.
Recent results also use the CC0 `international_results` dataset and OpenFootball's
public-domain World Cup data. Future fixtures use the World Football Elo schedule
plus TheSportsDB. Duplicate events are merged; conflicting scores stop publication.

NFELO does not use squads, injuries, red cards, tactics, travel, rest, weather
or betting markets. Political successor mappings and cross-era comparison remain
modelling assumptions. Ratings and probabilities are estimates, not certainties
or betting advice.

## License

Project code is MIT-licensed. Source data remains attributable to its publisher
and is not relicensed by this repository.
