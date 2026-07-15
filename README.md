# Network Football Elo

A static, searchable international-football rating site built from the public
World Football Elo Ratings TSV ledger and the frozen winner of the Great Elo
Bake-off. It includes current rankings, every historical source result, one
all-time peak per nation, the highest-rated match instances, team histories,
and a current-state probability calculator.

The predictive state is a full-covariance dynamic Gaussian opponent network.
The familiar base-10 Elo curve remains the observation link; uncertainty,
debut priors, era-adjusted home advantage, goal-margin information and the
friendly/competitive probability temperatures are all replayed chronologically.

## What is automatic

The Pages workflow runs daily at 06:20, 15:20 and 23:20 UTC, after the main
Americas, Asia/Oceania and Europe/Africa match windows. It can also be run manually.
It:

1. validates the public ranking and reference TSVs;
2. refreshes team pages whose published rating changed;
3. performs a full active-team reconciliation on Sundays;
4. refuses empty, malformed or implausibly truncated source pages;
5. replays all history with the frozen model;
6. runs Python and JavaScript checks;
7. deploys the new static artifact only after every check passes.

Routine updates never refit the model. A re-fit is a separate research release.

## Connect GitHub so Codex can publish it

Do **not** paste a personal access token into chat. Use the GitHub App flow:

1. Create an empty GitHub repository, ideally public and named
   `network-football-elo`.
2. Open [Codex](https://chatgpt.com/codex), sign in with ChatGPT, choose
   **Connect GitHub**, and authorize that repository.
3. In Codex environment settings, create an environment for the repository.
4. Give Codex the exact `owner/repository` name. Codex can then put this project
   into the repository and open the initial pull request (or push if the
   repository permissions allow it).
5. In the repository, open **Settings → Pages** and choose **GitHub Actions** as
   the publishing source.
6. In **Settings → Actions → General → Workflow permissions**, select
   **Read and write permissions**. This lets the scheduled bot preserve newly
   validated source snapshots. Pages deployment also uses its dedicated token
   permissions in the workflow.
7. Merge the initial pull request if branch protection requires review. The
   first run builds and publishes the site; no further manual updates are
   required.

GitHub may take several minutes to show a newly authorized repository in Codex.
Organization repositories can also require an administrator to approve the
GitHub App.

## Local build

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/build_site.py
python -m unittest discover -s tests -v
node --check public/assets/app.js
python -m http.server 8000 --directory public
```

Open `http://localhost:8000`. The site has no application server and sends no
visitor data to a project backend.

To check the public source before building:

```bash
python scripts/fetch_sources.py --source source
```

Use `--full` for an explicit full reconciliation. The fetcher is rate-limited,
retries transient failures and stages every response before replacing the last
good snapshot.

## Repository layout

- `source/` — validated first-party TSV snapshot.
- `config/` — exact bake-off parameters and tournament metadata.
- `scripts/ledger.py` — canonicalisation, deduplication and same-day ordering.
- `scripts/model.py` — frozen network replay and conservative record layer.
- `scripts/build_site.py` — static JSON generation and build manifest.
- `scripts/fetch_sources.py` — guarded public-source updater.
- `public/` — GitHub Pages application shell; generated data is ignored by Git.
- `.github/workflows/pages.yml` — scheduled refresh, checks and deployment.
- `docs/great-elo-bakeoff.md` — held-out model-selection report.

## Rating conventions

Predictions use the joint posterior mean and covariance directly. The displayed
network rating is intentionally conservative:

```text
M_i  = 2000 + breadth_reliability_i × (mu_i - elite_reference)
NR_i = M_i - 1.6448536269514715 × sqrt(Sigma_ii)
```

The record score for a match is:

```text
Q_ij = M_i + M_j
       - 1.6448536269514715
         × sqrt(Sigma_ii + Sigma_jj + 2 Sigma_ij)
```

Both participants need 30 prior matches. Every match instance is retained;
there is no one-per-pair rule.

## Source and status

Historical match rows and labels are from [World Football Elo Ratings](https://eloratings.net/).
Recent results use the CC0 `international_results` dataset, with OpenFootball's
public-domain World Cup JSON as a second, independently validated source. Future
fixtures use World Football Elo Ratings' cross-confederation schedule, supplemented by
TheSportsDB's documented schedule API for richer competition-specific details.
Duplicate fixtures are merged and conflicting scores stop publication. Every pushed
build refreshes sources first, preventing an older committed snapshot from replacing a
newer deployment. This project is independent and is not affiliated with eloratings.net,
FIFA or any confederation.

The model omits line-ups, injuries, red cards, travel, rest, weather, tactics and
betting markets. Its probabilities are model estimates, not betting advice.

## License

The project code is MIT-licensed. Source data remains attributable to its
publisher and is not relicensed by this repository.
