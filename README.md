# Network Football Elo

Network Football Elo is an independent international football rating and
prediction site covering senior men's internationals from 1872 to the present.
It provides current rankings, complete historical results, upcoming fixtures,
match probabilities, national-team histories and all-time records.

**Live site:** <https://benyominnemoff-lab.github.io/network-football-elo/>

## How it works

The model retains the familiar Elo relationship between a rating gap and an
expected result, while adding three features that ordinary scalar Elo does not
have:

- uncertainty for every team's estimated strength;
- connections through shared opponents; and
- era-adjusted home advantage, draw rates and winning-margin information.

The public rating is deliberately conservative. It adjusts estimated strength
for the breadth of a team's opponents and subtracts an uncertainty allowance.
This prevents teams with a narrow or poorly connected schedule from appearing
artificially high.

The complete explanation and exact equations are available on the site's
[Methodology page](https://benyominnemoff-lab.github.io/network-football-elo/#/methodology).
A summary of the historical evaluation is in
[`docs/model-validation.md`](docs/model-validation.md).

## Data and automatic updates

Historical results and labels are based on
[World Football Elo Ratings](https://eloratings.net/). Recent results and future
fixtures come from the CC0-licensed
[international_results](https://github.com/martj42/international_results)
dataset.

GitHub Actions checks for new data at 04:17 and 18:17 UTC every day. Before a
new version is published, the update process validates the source, rebuilds the
complete chronological rating history, runs the automated test suite and checks
the browser code. If any check fails, the existing site remains online.

Routine data updates do not change the model parameters.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/build_site.py
python -m unittest discover -s tests -v
node --check public/assets/app.js
python -m http.server 8000 --directory public
```

Open <http://localhost:8000>.

To retrieve the current results and fixture feed before building:

```bash
python scripts/fetch_sources.py --source source
```

## Repository layout

- `source/` — historical match data and the current open-data supplement.
- `config/` — model parameters and tournament metadata.
- `scripts/` — data retrieval, validation, replay and static-site generation.
- `public/` — the GitHub Pages site and generated data.
- `tests/` — consistency, probability and static-build checks.
- `.github/workflows/pages.yml` — scheduled updates and Pages deployment.

## Rating conventions

Predictions use the complete strength and uncertainty state. The displayed team
rating is:

```text
M_i  = 2000 + breadth_reliability_i × (mu_i - elite_reference)
NR_i = M_i - 1.6448536269514715 × sqrt(Sigma_ii)
```

The combined rating for a matchup is:

```text
Q_ij = M_i + M_j
       - 1.6448536269514715
         × sqrt(Sigma_ii + Sigma_jj + 2 Sigma_ij)
```

Both teams need 30 previous matches before a historical rating or matchup is
eligible for the record tables. Repeat pairings are retained.

## Limitations

The model does not use squad selection, injuries, red cards, travel, rest,
weather, tactics or betting-market information. Ratings and probabilities are
estimates, not certainties or betting advice.

This project is independent and is not affiliated with its data sources, FIFA
or any confederation.

## License

The project code is MIT-licensed. Source data remains attributable to its
publisher and is not relicensed by this repository.
