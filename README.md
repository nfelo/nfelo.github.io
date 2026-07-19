# Network Football Elo

[Network Football Elo](https://nfelo.github.io/) (NFELO) is an independent,
results-only rating and forecasting system for senior men's international
football. The static site includes current and historical rankings, more than
150 years of results, upcoming fixtures, team comparisons, all-time records and
a match predictor.

## What the model publishes

NFELO deliberately separates two questions:

- **Strength rating:** the model's posterior-mean estimate of playing strength.
  This is the number used for current rankings, historical rankings, movement
  and strength peaks.
- **Conservative record score:** a separate lower-bound measure for the record
  book. It discounts thin opponent networks and propagates uncertainty in both
  the team and the elite reference group.

Match probabilities start with the strength network, then use a hidden
team-specific attack and defence layer. The probability layer can improve the
win/draw/loss distribution, but it never changes a rating or ranking.

## Model outline

The rating state is a dynamic joint Gaussian opponent network. The complete
team-by-team covariance matrix carries evidence through shared opponents.
Home advantage, draw frequency, rating-gap scale and goal-margin information
vary with football's historical environment. New teams start relative to the
active international pool rather than at a universal fixed number.

Every match with a known complete date is handled as part of one matchday:

1. all same-date debutants receive the same pre-date pool prior;
2. every match is forecast from one frozen start-of-day state;
3. the attack/defence layer is also frozen for all forecasts that day; and
4. all results are learned together with an order-invariant Gaussian update.

Historical rows without a known month or day remain in their source sequence.

The hidden score distribution is calibrated each January from the preceding
eight complete years and blended with the network forecast. A boundary gate
keeps the network's most likely win/draw/loss outcome while retaining as much of
the score correction as that constraint permits. Exact-score probabilities are
then raked so their win, draw and loss regions add up to the displayed final
probabilities.

The complete equations, constants and limitations are on the site's
[Methodology page](https://nfelo.github.io/methodology/).

## Validation: two different evidence classes

The primary comparative evidence is the original five-block **nested historical
holdout** over 46,801 matches from 1960 onward. Choices were made using earlier
periods and scored on later periods:

| Model | Three-way log loss |
| --- | ---: |
| NFELO network | **0.884219** |
| Best tested scalar Elo | 0.892970 |
| Published World Football Elo forecast | 0.902619 |

With incomplete historical dates kept sequential, the deployed system scores
approximately **0.880702** when final constants are replayed through the fixed
11 July 2026 cutoff. The exact value is generated on every build. The audit
evaluator's earlier 0.880568 figure grouped unknown dates by a synthetic day and
is retained only as an audit diagnostic with an erratum. Either lower number is
a **retrospective diagnostic**, not a second out-of-sample result. It is useful
for testing mechanics such as complete-date batching and the boundary gate, but
must not be presented as equivalent to the nested holdout.

The original nested fitter programs and frozen derived evaluation file were not
preserved, so that older aggregate result cannot currently be reproduced
bit-for-bit. The repository now records first-published future-fixture forecasts
by methodology version to build a genuinely prospective evidence set.

See [Model validation](docs/model-validation.md) for the evidence boundaries,
audit findings and next research steps. The complete
[19 July 2026 methodology audit](docs/methodology-audit-2026-07-19.md) and its
[research release](research/methodology-audit-2026-07-19/) are also retained.

## Automatic updates

The Pages workflow checks results and fixtures at 06:20, 15:20 and 23:20 UTC,
after the main Americas, Asia/Oceania and Europe/Africa match windows. Each run:

1. stages and validates the public data feeds;
2. rejects empty, malformed, conflicting or implausibly truncated data;
3. preserves the last verified snapshot when a source is temporarily unusable;
4. replays the full rating history and refreshes future forecasts;
5. records previously unseen prospective forecasts;
6. runs Python, model-invariant and JavaScript checks; and
7. deploys only when the complete build passes.

Routine refreshes do not refit structural rating constants. Annual probability
calibration follows the declared prior-years-only rule.

## Local build

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/build_site.py --source source --config config --output public
python -m unittest discover -s tests -v
node --check public/assets/app.js
python -m http.server 8000 --directory public
```

Open `http://localhost:8000`. The deployed site is static and has no project
application server receiving visitor data.

To refresh the staged source snapshot before building:

```bash
python scripts/fetch_sources.py --source source
```

Use `--full` for an explicit full reconciliation. The fetcher is rate-limited,
retries transient failures and does not replace the last good source snapshot
until the new response passes validation.

## Repository layout

- `source/` — validated source snapshot and
  `prospective_forecasts.jsonl` forecast ledger.
- `config/` — fixed deployed parameters and tournament metadata.
- `scripts/ledger.py` — canonicalisation, identity succession and deduplication.
- `scripts/model.py` — joint opponent-network replay, rankings and records.
- `scripts/forecast_layer.py` — hidden score state, annual calibration and gate.
- `scripts/build_site.py` — static JSON, historical views and build manifest.
- `scripts/fetch_sources.py` — guarded source updater.
- `public/` — GitHub Pages application and generated data.
- `tests/` — data, model, interface and publication invariants.
- `docs/` — validation scope and methodology audit summary.

## Data sources and limitations

Historical match rows and labels are based on
[World Football Elo Ratings](https://eloratings.net/). Recent results are checked
against the CC0 `international_results` dataset and OpenFootball's public-domain
World Cup data. Future fixtures use World Football Elo Ratings' schedule,
supplemented by TheSportsDB where available. Conflicting completed scores stop
publication rather than being guessed.

The model does not use squads, injuries, red cards, travel, rest, weather,
tactics or betting markets. Political successor mappings remain a modelling
assumption. Ratings and probabilities are estimates, not certainties or betting
advice. This project is not affiliated with eloratings.net, FIFA or any
confederation.

## License

Project code is MIT-licensed. Source data remains attributable to its publisher
and is not relicensed by this repository.
