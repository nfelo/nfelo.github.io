# Network Football Elo

[NFELO](https://nfelo.github.io/) is a static, searchable rating and prediction
site for senior men's international football. It covers results from 1872 to
the present, current and historical rankings, every source match, one peak per
nation, top match instances, number-one chronology, team comparison and a
date-aware probability calculator.

## What the model publishes

NFELO publishes one rating everywhere: current rankings, rankings on historical
dates, nation peaks, team pages and match records all use the same
evidence-adjusted network rating. A hidden attack/defence state refines match
probabilities only; it never changes ratings, ranking order, peaks or points
gained from results.

The rating state is a full-covariance dynamic Gaussian opponent network. The
base-10 Elo expectation remains the observation link, while the model also
represents uncertainty shared through common opponents, era-specific home and
draw conditions, an active-pool debut prior and goal-margin information.

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

The marginal variance `Sigma_ii` is retained deliberately. Cancelling uncertainty
shared with a contemporaneous elite reference can make a small, inward-looking
historical network appear far more certain—and therefore far stronger across
eras—than the evidence warrants. The latent posterior mean remains available
inside the forecast calculation but is not published as a competing ranking.

For an eligible match instance:

```text
Q_ij = M_i + M_j
       - 1.6448536269514715
         × sqrt(Sigma_ii + Sigma_jj + 2 Sigma_ij)
```

Both participants need 30 prior matches. Every match instance is retained;
repeat pairings are not collapsed.

## Forecast probabilities

The network forecast integrates uncertainty in the strength difference and
uses separate friendly and competitive probability temperatures. A parallel
team-specific attack/defence model produces a score-based W/D/L vector. Annual
draw calibration, probability powers and the pool weight are fitted using only
the preceding eight complete calendar years.

The score correction is boundary-gated: NFELO moves toward the pooled forecast
only as far as it can without changing the network model's most likely W/D/L
outcome. The exact-score table is then raked so its win, draw and loss regions
sum to the displayed final probabilities; omitted scorelines above 5–5 remain
in the reported tail mass.

## What the 19 July 2026 audit changed

The audit supported the existing core constants and did not justify a broad
parameter refit. This release adopts the findings that improve chronology,
probability consistency and publication quality without replacing the public
rating:

- complete-date forecasts and score states are frozen at the start of the day;
- same-date network evidence is learned jointly and is row-order invariant;
- the probability gate retains the maximum safe score correction instead of
  reverting the whole vector;
- exact-score probabilities agree with the displayed W/D/L forecast;
- first-published future forecasts are appended to a versioned prospective
  ledger;
- validation evidence is labelled by design; and
- tests cover date order, covariance validity, probability symmetry, score-grid
  reconciliation and historical peak guardrails.

The audit's proposal to publish raw posterior-mean strength as the main ranking
was not adopted. That signal predicted near-term results well, but it does not
serve NFELO's cross-era record objective: cancelling common uncertainty made
pre-First World War British football implausibly dominate the all-time table.
The established evidence-adjusted rating remains the sole public measure.

## Validation: two different evidence classes

The primary comparative result is the original five-block **nested historical
holdout** over 46,801 matches from 1960 onward:

| Model | Three-way log loss |
| --- | ---: |
| NFELO network | **0.884219** |
| Best tested scalar Elo | 0.892970 |
| Published World Football Elo forecast | 0.902619 |

Choices used earlier periods and were scored on later periods. The aggregate
result is retained, but the original fitter programs and frozen derived dataset
were not committed, so it cannot currently be reconstructed bit-for-bit.

The site also calculates a **retrospective diagnostic** on every build by
replaying the final constants through the fixed 1960–11 July 2026 window. It is
useful for checking date batching, the boundary gate and other mechanics, but
it is not a second out-of-sample estimate and must not be compared as if it were
the same experiment as the nested holdout.

From this release onward, first-published fixture probabilities are stored in
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

Routine updates do not refit core rating or score-state structure. At each
January boundary, only the declared forecast calibration is refitted from the
preceding eight complete years.

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
- `scripts/model.py` — date-batched opponent-network replay and public rating.
- `scripts/forecast_layer.py` — hidden score state, annual calibration and gate.
- `scripts/build_site.py` — static data, history, records and fixture generation.
- `scripts/fetch_sources.py` — guarded multi-source updater.
- `public/` — GitHub Pages application shell; generated data is ignored by Git.
- `tests/` — model, data, UI and historical regression checks.
- `docs/` and `research/` — validation, audit and reproduction materials.

## Data and limitations

Historical rows and labels are based on [World Football Elo Ratings](https://eloratings.net/).
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
