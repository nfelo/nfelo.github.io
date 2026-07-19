# NFELO methodology audit

> **Release integration note (19 July 2026):** this document is the independent
> audit as delivered; recommendations remain visible even where the product
> decision differs. The release adopts the complete-date update, boundary gate,
> score-grid reconciliation, evidence labels and prospective ledger while
> retaining NFELO's established evidence-adjusted public rating. Publishing the
> raw posterior mean was rejected for the cross-era product because cancelling
> shared network uncertainty made pre-First World War British teams implausibly
> dominate the record table. No manual era cap was introduced.
>
> The audit evaluator's 0.880568 strict-date diagnostic grouped by a synthetic
> numeric day, including rows whose month/day are unknown and one possible
> cross-year collision. The release follows the report's written recommendation
> and keeps incomplete dates sequential. Its generated retrospective diagnostic
> is approximately 0.880683 on the 18 July source snapshot and is computed from
> the deployed match rows at build time. The nested 0.884219 result, core-
> parameter decision and complete-date recommendations are unchanged.

- **Audit date:** 19 July 2026
- **Repository:** `nfelo/nfelo.github.io` at commit `b005b42da17269a8908bec5bb6a1102143e13b52`
- **Evaluation cutoff:** 11 July 2026
- **Primary target:** pre-match three-way win/draw/loss log loss
- **Allowed information:** prior results and scores, date, team identity/succession, venue and competition class; no line-ups, players, injuries, markets or other match-day information

## Executive verdict

NFELO's core is a genuinely strong results-only model. The full opponent covariance, time-varying football environment, active-pool debut prior, goal-margin information and friendly/competitive probability temperatures are all supported by historical evidence. The original rolling bake-off reports log loss **0.884219** over 46,801 later matches, versus **0.892970** for its best scalar-Elo benchmark and **0.902619** for the published World Football Elo forecast.

It is not established as the best possible results-only model, and the current public validation claim is not sound. The newer displayed **0.880710** figure is a retrospective replay with core constants fitted through 2026, not a nested out-of-sample estimate. The original fitting/evaluation programs and frozen evaluation dataset named in the bake-off were never committed, so the original selection cannot be independently reproduced exactly.

My best defensible conclusion is:

1. **Keep the core model class and the frozen core constants for now.** A new broad search produced unstable fold winners and no statistically reliable improvement over those constants.
2. **Change the chronological unit from a row to a date.** Forecast every match on a date from one frozen prior state, initialise all same-date debutants jointly, and use a joint Gaussian update for the date. This is invariant to unknown kickoff order and had no predictive cost in the replay. Combined with the improved gate, it is the best tested argmax-preserving retrospective system at **0.880568** log loss.
3. **Separate strength ranking from conservative record ranking.** The latent posterior mean is the best tested strength signal. It beat the public breadth-adjusted lower-confidence rating by **0.005888** log loss per eligible future match, with a 95% interval of **0.004662–0.007287** in its favour.
4. **Replace the all-or-nothing forecast gate.** If preserving the network's top pick is a product requirement, move toward the score forecast only as far as that constraint permits. This keeps exactly the same top pick while improving every proper score in the replay.
5. **Restore an executable research release.** Version the immutable ledger, pre-match predictions, fitters, search space and generated report. Display the honest **0.884219** rolling estimate separately from any full-history replay diagnostic.

There is no finite experiment that can test “all possible” formulae: the model space is infinite and future football is not stationary. This audit therefore combines the repository's original bake-off with more than 7,000 additional fold/year fits or full-history replays across a declared search space. “Best” below means best supported under that protocol, not a proof of global optimality.

## 1. What the deployed system does

The implementation is in [the network replay](https://github.com/nfelo/nfelo.github.io/blob/main/scripts/model.py), [forecast layer](https://github.com/nfelo/nfelo.github.io/blob/main/scripts/forecast_layer.py) and [ledger parser](https://github.com/nfelo/nfelo.github.io/blob/main/scripts/ledger.py).

### 1.1 Ledger and identity

- The public World Football Elo team-page TSV rows are deduplicated by their first nine fields.
- Historical codes are mapped through 55 predecessor/rename relationships into 248 canonical team histories.
- A blank source venue means team 1 is treated as the home team; otherwise venue identity determines home, away or neutral status.
- Same-date rows are currently ordered by reconstructing the source's published pre/post Elo state.
- Unknown historical month/day values are retained as zero.

The current snapshot contains 52,310 matches from 30 November 1872 through 18 July 2026. The fixed audit window contains 46,801 matches from 1960 through 11 July 2026. Of those, 41,688 (89.1%) share their date with at least one other match, 196 have an unknown month or day, and the largest date contains 66 matches. Date handling is therefore a first-order methodological issue, not an edge case.

### 1.2 Dynamic Gaussian opponent network

The latent ratings have a joint Gaussian approximation

\[
\mathbf r\sim N(\boldsymbol\mu,\Sigma),
\]

where \(\Sigma\) is the complete team-by-team covariance matrix. A participant's diagonal variance receives Brownian drift before its next match:

\[
\Sigma_{ii}\leftarrow\Sigma_{ii}+19.7502126^2\,\Delta t.
\]

A debutant receives prior standard deviation 300 and a mean relative to the active international pool:

\[
\mu_{\rm new}=\operatorname{median}(\mathcal R_y)-192.900220
-84.248606\log[(A_y+10)/50].
\]

The pool uses recently active teams with at least 30 matches, falling back to at least 10 when necessary.

### 1.3 Era-varying expectation and W/D/L probabilities

For team 1 against team 2,

\[
\delta=a_y(\mu_1-\mu_2)+H_yh,
\qquad E=\{1+10^{-\delta/400}\}^{-1}.
\]

The deployed knot values are:

| Year | Gap scale \(a_y\) | Equivalent divisor | Home \(H_y\) | Equal-team draw rate |
|---:|---:|---:|---:|---:|
| 1900 | 1.932980 | 206.9 | 73.123 | 0.184517 |
| 1930 | 1.560214 | 256.4 | 96.742 | 0.217433 |
| 1960 | 1.304446 | 306.6 | 112.896 | 0.259656 |
| 1990 | 1.121857 | 356.6 | 112.661 | 0.308676 |
| 2020+ | 1.000000 | 400.0 | 83.534 | 0.325135 |

Scale is interpolated in log space, draw rate in a bounded-logit coordinate and home advantage linearly. At a fixed latent gap,

\[
D=p_{D,y}4E(1-E),\quad W=E-D/2,\quad L=1-E-D/2.
\]

This preserves \(W+D/2=E\). The model integrates these probabilities over

\[
V=\Sigma_{11}+\Sigma_{22}-2\Sigma_{12}
\]

with 11-point Gauss–Hermite quadrature, then raises the three probabilities to power 0.9697407 for friendlies or 1.0635626 for competitive matches and renormalises.

### 1.4 Result and margin update

For result score \(S\in\{0,0.5,1\}\), let

\[
\mathbf v=\Sigma_{:,1}-\Sigma_{:,2},\quad
\beta=a_y\ln(10)/400,\quad
\lambda=1.7440261\,G(m),
\]

\[
d=1+\lambda\beta^2E(1-E)V.
\]

The assumed-density update is

\[
\boldsymbol\mu' = \boldsymbol\mu+
\mathbf v\frac{\lambda\beta(S-E)}d,
\qquad
\Sigma'=\Sigma-
\mathbf v\mathbf v^T\frac{\lambda\beta^2E(1-E)}d.
\]

Every competition class has the same state-update information ratio. Goal margin has a 20-year scoring-environment adjustment and a capped piecewise curve: draw 3.486643, one-goal 1, two-goal 1.755270, three-goal 2.201047 and +1.467768 per further effective goal, capped at seven. The update is a useful Gaussian/quasi-likelihood approximation, not an exact posterior update for the displayed three-way likelihood; the project should describe it that way rather than simply as “Bayesian.”

### 1.5 Hidden attack/defence score layer

A parallel, non-ranking state tracks attack \(A_i\) and defence \(D_i\). A trailing current-plus-eight-calendar-year goal mean, with a 100-match prior at 1.3 goals per team, supplies \(B\). With network expected score \(E\),

\[
g=s\log[E/(1-E)],
\]

\[
\lambda_1=B\exp(g/2+A_1-D_2),\qquad
\lambda_2=B\exp(-g/2+A_2-D_1).
\]

Independent Poisson scores are collapsed to W/D/L. Goals are clipped at seven, residuals at four, and attack/defence decay as \(\exp(-0.3t)\). The release schedule is:

| Forecast years | Gap scale | Learning rate |
|---|---:|---:|
| 1960–1979 | 0.6 | 0.03 |
| 1980–1999 | 0.7 | 0.05 |
| 2000–2009 | 0.8 | 0.05 |
| 2010–2019 | 0.7 | 0.03 |
| 2020+ | 0.8 | 0.05 |

At each January boundary, the score distribution gets a draw tilt and friendly/competitive powers fitted on the preceding eight complete years. A network/score linear-pool weight is then fitted. If the pool changes the network argmax, the deployed code discards the entire correction for that match.

### 1.6 Public rating and match record score

Opponent weights decay with an eight-year half-life. Their Kish-style effective count \(N_i\) gives \(\rho_i=N_i/(N_i+4)\). With \(B\) the mean of the ten strongest eligible latent means,

\[
M_i=2000+\rho_i(\mu_i-B),
\qquad NR_i=M_i-1.644854\sqrt{\Sigma_{ii}}.
\]

The match record score is

\[
Q_{ij}=M_i+M_j-1.644854
\sqrt{\Sigma_{ii}+\Sigma_{jj}+2\Sigma_{ij}}.
\]

Both teams require 30 prior matches. These formulae intentionally rank evidence-backed records, but they are not the posterior estimate of current strength.

## 2. What the original bake-off establishes

The detailed report and JSON survive only in Git history at [the 14 July research commit](https://github.com/nfelo/nfelo.github.io/blob/d014d0686b4b6af85efa7ed56a7488bab3f666b3/docs/great-elo-bakeoff.md). It reports five rolling outer blocks: 1960–1979, 1980–1999, 2000–2009, 2010–2019 and 2020–2026. Model choices use the immediately preceding block; 20,000 paired calendar-year bootstrap draws quantify conditional uncertainty.

That search covers published WFE; common, monotone and independent competition K structures; no, old, fitted and G-Elo-style margin likelihoods; fixed, median-pool and active-pool debuts; expectation-preserving, Davidson, ordered-logit and likelihood-score links; scalar, diagonal and full-covariance states; pooled and match-level information; one, two and five forecast temperatures; extra home/draw calibration; probability ensembles; and a deliberately wider uncertainty search. My additions target the major gaps left by that list: chronological date batching, a joint order-invariant date update, the newer score layer and gate, Dixon–Coles low-score dependence, identity continuity, and the public ranking formula.

| Original rolling candidate | Log loss | Accuracy |
|---|---:|---:|
| Common-update full network + two temperatures | **0.884219** | 59.095% |
| Unequal update weights + two temperatures | 0.884203 | 59.065% |
| Five forecast temperatures | 0.884286 | 59.095% |
| One global temperature | 0.885159 | 59.095% |
| Previous network | 0.886856 | 58.973% |
| Best scalar World-Football-style Elo | 0.892970 | 58.527% |
| G-Elo | 0.895187 | 58.779% |
| Published World Football Elo | 0.902619 | 58.804% |

The common-update model beats published WFE by 0.018400 log loss per match; its reported 95% paired interval is 0.015270–0.021477 in NFELO's favour. The unequal-update numerical lead is only 0.000015 and its interval crosses zero, so choosing the common update is correct. Two temperatures beat one by 0.000940 with a wholly favourable interval; five do not improve on two. Full covariance beats a diagonal approximation by about 0.0056. Goal margin and the active-pool debut prior are also clearly supported.

This is strong comparative evidence. It is not currently reproducible: `elo_objective.cpp`, `fit_bakeoff_candidate.py`, `network_bakeoff.py`, both tuning programs, `analyse_bakeoff.py` and `data/elo_matches.npz` are listed with hashes but appear in no repository commit.

## 3. Independent audit protocol

I rebuilt a faithful C++ evaluator and captured every deployed pre-match network and score-layer state. The exact current replay over the fixed 46,801 matches is:

| Current full-history replay | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Network only | 0.882136 | 0.519154 | 0.172745 | 59.125% |
| Score pool, ungated | 0.880667 | 0.518479 | 0.172569 | 59.014% |
| Deployed all-or-nothing gate | 0.880693 | 0.518495 | 0.172568 | 59.125% |
| Joint date update + date-frozen score state + boundary gate | **0.880568** | **0.518488** | **0.172565** | 59.125% |

These are faithful diagnostics, not out-of-sample estimates of the core: the same final core constants are replayed into earlier matches. The site's hard-coded 0.880710 differs only by routine source refresh, but [the current page text](https://github.com/nfelo/nfelo.github.io/blob/main/public/assets/app.js) describes it as rolling pre-match evidence. That description should be corrected. [The shorter validation document](https://github.com/nfelo/nfelo.github.io/blob/main/docs/model-validation.md) still reports the original 0.884219, so the repository currently presents two incompatible evidence classes without labelling the distinction.

The additional search comprised:

- 995 deployed-era network fold replays over prior SD, drift, quality, margin curve, friendly information ratio and same-date mode;
- 1,236 observation-parameter stress-test replays over those values plus scale, home advantage and draw rate;
- 500 targeted result-order-invariant daily-update replays;
- 1,407 annual score calibration/pooling fits over four windows and four pool families, plus five fixed score-state grids;
- 2,680 annual ranking-proxy fits over latent, uncertainty, breadth and public-WFE gaps;
- targeted Dixon–Coles, successor, diagonal, margin, gate and ordering ablations.

The observation stress test removes future-fitted era curves but still uses the deployed margin and debut formula constants, so it is a sensitivity check rather than a fully clean replacement for the missing nested fitter.

## 4. Main experimental findings

### 4.1 The core architecture survives ablation

| Change from current network replay | Log-loss change | Paired year-cluster 95% interval | Verdict |
|---|---:|---:|---|
| Diagonal covariance | +0.005430 | +0.004108 to +0.006928 | Reject |
| No goal-margin information | +0.002388 | +0.000927 to +0.003665 | Reject |
| No predecessor/successor merging | +0.001078 | +0.000464 to +0.001833 | Reject hard removal |
| Freeze forecasts within date, sequential posterior update | +0.000091 | +0.000004 to +0.000202 | Honest timing costs a tiny amount |
| Joint order-invariant date update | **−0.000059** | −0.000365 to +0.000221 | Prefer structurally; no measured cost |

The simultaneous-date update freezes all expectations and curvatures at the pre-date state, adds their information to the Gaussian precision jointly, and applies the final covariance to the summed score vector. Reordering same-date rows by a result-independent key changes aggregate log loss by less than \(10^{-7}\). This removes both direct same-day leakage and arbitrary order dependence from the approximate update.

The no-successor result shows that continuity information is useful. It does not prove every hard merge is correct. Renames should remain exact; political successors should eventually be tested as discounted transfer priors with added variance, preserving separate historical records.

### 4.2 A broader parameter search does not justify new global constants

Using the deployed era curves, fold-specific selection reduces replay log loss from 0.882144 to 0.881322, a difference of −0.000822. Its conditional paired interval is **−0.002357 to +0.000265**, crossing zero; Brier score is slightly worse. The fold winners are extremely unstable: prior SD 76–585, drift 10–33 and quality 0.37–6.31. The order-invariant version scores 0.881433 and is also statistically tied.

When scale, home and draw are selected only from the preceding block and held constant in the following block, the batch model scores 0.882950 versus 0.884909 for a simple constant-observation reference; the improvement interval is −0.003674 to −0.000478. Selected scale, home and draw change materially by era, supporting time variation, but the other hyperparameters remain too unstable to turn the fold winners into a single new release.

Therefore the optimal numerical decision now is **no core parameter change**. Refit only after the original nested research pipeline has been restored and the same-date rule has been fixed in advance.

### 4.3 The score layer helps, but its newer headline is not yet cleanly validated

Against the same retrospective core, the deployed score layer improves log loss in every chronological block and both friendly/competitive and neutral/non-neutral subgroups. Its top-label 20-bin calibration error falls from approximately 0.0125 to 0.0071. This supports the attack/defence idea.

However, the score-layer release has no committed research program or immutable predictions. Its current 0.880710 headline is not a nested test of the whole system. The release schedule is also noisy: replaying the common \(s=0.8\), learning-rate 0.05 state in every era is the best retrospective grid point (0.880510), and the chosen schedule loses to another grid state in four of five blocks in hindsight. That is a candidate for a new nested test, not permission to change it from the full sample.

Jointly fitting the score calibration and friendly/competitive pool weights is numerically best in the sequential replay (0.880599 versus 0.880693 deployed), but the paired interval against the deployed gate is −0.000430 to +0.000223. Under date-frozen forecasts the best window changes from eight to twenty years and the gain remains statistically uncertain. The existing eight-year sequential calibration is therefore a reasonable low-variance default.

A Dixon–Coles low-score correction, tested inside the same annual joint pool, slightly worsens log loss by 0.000041 (95% interval −0.000041 to +0.000138), although Brier/RPS improve minutely. Do not add it when log loss is primary. This is consistent with the correction's purpose in low-score dependence but shows that the existing draw calibration already captures most of its W/D/L value. The test follows the low-score adjustment introduced by [Dixon and Coles](https://rss.onlinelibrary.wiley.com/doi/abs/10.1111/1467-9876.00065).

### 4.4 The gate can be improved without changing a single top pick

The deployed gate completely reverts 784 of 46,801 sequential forecasts (1.68%) when the score pool changes the network argmax. Ungated pooling is better in log loss but changes 52 top-label calls in aggregate.

A boundary gate follows the line from network probability to pooled probability and stops immediately before the original top outcome would cease to be top. It keeps exactly the network's argmax while retaining, on average, 50.7% of the score correction on affected rows.

| Gate, sequential replay | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Full reversion | 0.880693 | 0.518495 | 0.172568 | 59.125% |
| Boundary gate | **0.880660** | **0.518474** | **0.172563** | 59.125% |

The boundary-minus-reversion log-loss interval is −0.000076 to +0.000008. With the joint order-invariant network update and date-frozen score state it is **−0.000083 to −0.000001**, while accuracy remains identical. The complete strict-date boundary system improves on the currently deployed replay by 0.000125, although that broader paired interval (−0.000437 to +0.000114) crosses zero. The gate change is simple and constraint-preserving and should replace full reversion if retaining the core top pick is non-negotiable. If log loss is the only objective, remove the gate and fit the pool directly.

### 4.5 The exact-score grid does not match the advertised W/D/L forecast

The UI's score grid is the raw independent-Poisson matrix. Its cells do not include the fitted draw tilt, probability powers, network pool or safety gate. Across the evaluation window, the mean L1 difference between raw score-derived and final W/D/L probabilities is 0.0705; their top outcomes differ on 4.81% of matches.

Reconcile the grid by multiplying every score cell in outcome region \(o\in\{W,D,L\}\) by

\[
P_{\rm final}(o)/P_{\rm raw\ score}(o).
\]

This preserves relative scoreline probabilities within win/draw/loss while making the grid sum exactly to the displayed final outcome probabilities. Tail mass above 5–5 must be included before the displayed cells are cut off.

### 4.6 The public rating is not the best strength ranking

For matches where both teams had 30 prior results, I fitted the same swap-invariant W/D/L calibration annually to alternative pre-match rating gaps. This isolates how much future-result signal each ranking carries.

| Ranking signal, 8-year annual calibration | Matches | Log loss | Accuracy | Higher-ranked winner in neutral decisive matches |
|---|---:|---:|---:|---:|
| **Latent posterior mean** | 43,076 | **0.891291** | 58.264% | 74.564% |
| Latent mean minus 1.645 raw SE | 43,076 | 0.891429 | 58.295% | 74.506% |
| Public breadth + 1.645 lower bound | 43,076 | 0.897179 | 57.991% | 74.151% |
| Published WFE pre-match rating | 43,076 | 0.898369 | 58.139% | — |

The latent-minus-public paired difference is −0.005888, with a 95% interval of −0.007287 to −0.004662. This is decisive.

There is also a statistical inconsistency in the public formula. \(M_i\) multiplies the latent deviation by \(\rho_i\), but the uncertainty penalty uses the unscaled \(\sqrt{\Sigma_{ii}}\), ignoring \(\rho_i\), uncertainty in the elite reference and covariance with that reference. At minimum, if \(B=k^{-1}\sum_{j\in\mathcal E}\mu_j\), the adjusted-mean variance is

\[
\operatorname{Var}(M_i)=\rho_i^2\left[
\Sigma_{ii}+k^{-2}\mathbf1^T\Sigma_{\mathcal E\mathcal E}\mathbf1
-2k^{-1}\sum_{j\in\mathcal E}\Sigma_{ij}
\right].
\]

Elite-set selection uncertainty is additional. The match-record variance needs the analogous delta-method covariance of two adjusted deviations from the reference, not the raw variance of \(\mu_i+\mu_j\).

Publish two products:

- **Strength ranking:** posterior mean \(\mu_i-B\), with posterior interval shown separately. This is the predictive ranking.
- **Evidence/record ranking:** a correctly propagated lower bound, explicitly labelled conservative. Show opponent breadth as a reliability field rather than multiplying the strength estimate and then subtracting an unscaled uncertainty penalty.

## 5. Recommended system and numbers

### 5.1 Release now without a new global refit

Use the current frozen core numbers because no searched replacement has a reliable outer advantage:

- prior SD 300;
- drift SD 19.7502126 points per square-root year;
- quality scale 1.7440261;
- current era scale 1, home advantage 83.533639 and equal-team draw rate 0.325135, with the existing historical knots;
- current era-normalised margin curve;
- active-pool debut prior;
- common update ratio 1 for every competition class;
- friendly/competitive network powers 0.9697407 and 1.0635626;
- existing score-state release schedule and eight-year annual calibration until a clean nested refit.

Change the mechanics, which do not require choosing new statistical constants:

1. Group the ledger by date.
2. Initialise every new team on that date from the same pre-date pool.
3. Add participant drift once and forecast every match from the frozen pre-date state.
4. Apply the joint, order-invariant daily Gaussian update.
5. Freeze the goal environment and attack/defence state for all forecasts on the date; apply their additive updates only after all predictions are saved.
6. Use an ungated pool for a pure-log-loss product, or the boundary gate when the network top pick must be preserved.
7. Rake the exact-score matrix to the final W/D/L probabilities.
8. Rank strength by latent posterior mean; move the conservative lower-bound score to a separately named table.

### 5.2 Next research release

Pre-register the following before looking at its outer results:

- the result-order-invariant date update;
- a small regularised core grid centred on the current constants, rather than unbounded fold-specific winners;
- joint versus sequential score calibration;
- one common score state versus the five-period schedule, particularly \((s,\eta,\gamma)=(0.8,0.05,0.3)\);
- hard rename continuity versus discounted successor transfer priors;
- expectation-preserving versus ordered-logit probability links (the original bake-off found them tied);
- independent Poisson versus Dixon–Coles only as a secondary proper-score trade-off;
- 8-, 12- and 20-year calibration windows;
- strength-mean and properly propagated conservative rankings as different objectives.

Use the original five outer blocks or expanding annual origins, but repeat the complete hyperparameter choice inside every outer training set. Generate one immutable row per forecast containing data hash, code commit, state hash, model ID and probability vector. A nested/block bootstrap should repeat selection where feasible; the current calendar-year bootstrap is conditional on the fitted models and understates search uncertainty.

For context, NFELO's full-covariance idea is related to dynamic paired-comparison uncertainty in [Glickman's rating research](https://www.glicko.net/ratings/cl-article.pdf), while the original G-Elo comparison is based on [the margin-likelihood G-Elo paper](https://arxiv.org/abs/2010.11187). These are useful benchmark families, not evidence that any named system is universally optimal.

## 6. Reproducibility and publication checklist

- Commit or release the exact frozen evaluation ledger, subject to data licensing.
- Commit the six bake-off programs named in the original report, or replace the report with an executable equivalent.
- Store out-of-sample prediction rows, not only aggregate JSON and hashes of absent files.
- Generate validation values from those immutable rows; do not hard-code a retrospective replay and call it rolling validation.
- Label evidence as **nested historical holdout**, **retrospective full-history replay**, or **prospective**.
- Add tests for team-swap invariance, date-order invariance, joint debut equality, probability sums, covariance symmetry/positive semidefiniteness and score-grid/WDL reconciliation.
- Keep a prospective forecast ledger from this release onward. It is the only clean test of the final all-data parameter set.

## Bottom line

The project has a better core than ordinary Elo and the original rolling evidence for that claim is persuasive. The largest weakness is not the Elo mathematics; it is the evidence boundary around the newest score layer and the public ranking label. The best next version is the same regularised full-covariance core, made date-order invariant, paired with a simpler constrained probability pool and two explicitly different rankings. That is a stronger and more defensible system than replacing the current constants with the numerically best values from another wide search.
