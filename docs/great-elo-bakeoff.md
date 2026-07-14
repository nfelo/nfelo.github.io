# The Great Elo Bake-off

**Completed:** 14 July 2026  
**Results included through:** 11 July 2026  
**Data:** 52,302 senior men's internationals, 248 canonical national-team histories, 30 November 1872–11 July 2026

## Verdict

The previous network model was not the best tested forecaster. The best defensible model is:

> **Full-covariance dynamic Gaussian opponent-network ratings, an expectation-preserving Elo probability link, era-normalised goal-margin information, an active-pool debut prior, one common state-update information weight for all match classes, and two forecast temperatures: friendly versus competitive.**

It produced the following genuinely pre-match results over 46,801 held-out matches from 1960–2026:

| Model | Log loss ↓ | Brier ↓ | RPS ↓ | Accuracy |
|---|---:|---:|---:|---:|
| Raw numerical winner: unequal update weights + two temperatures | **0.884203** | 0.520574 | 0.173189 | 59.065% |
| **Recommended: common update weight + two temperatures** | **0.884219** | **0.520573** | **0.173179** | **59.095%** |
| Five forecast temperatures | 0.884286 | 0.520632 | 0.173207 | 59.095% |
| Wider, weakly regularised uncertainty search | 0.884562 | 0.520777 | 0.173269 | 59.093% |
| One global forecast temperature | 0.885159 | 0.521086 | 0.173375 | 59.095% |
| Base full-network expectation model | 0.885274 | 0.521169 | 0.173340 | 59.095% |
| Previous network formula | 0.886856 | 0.522046 | 0.173721 | 58.973% |
| Best tested scalar World-Football-style Elo | 0.892970 | 0.525985 | 0.175420 | 58.527% |
| Seven-margin-category G-Elo | 0.895187 | 0.526726 | 0.175452 | 58.779% |
| Published World Football Elo baseline | 0.902619 | 0.531976 | 0.177407 | 58.804% |

The raw winner is only 0.0000154 log-loss per match ahead of the recommended model. Its paired calendar-year bootstrap interval is **−0.000123 to +0.000092**, and its fitted competitive/friendly update ratio reverses across eras. That is noise, not a defensible K hierarchy. The common-update version is therefore the release model.

Against the published baseline, the recommended model improves log loss by **0.018400 per match**, with a paired year-cluster 95% interval of **0.015270–0.021477** in its favour. This is a 2.04% relative reduction in log loss. Its top-label expected calibration error is **0.00849**, versus **0.06031** for the published baseline.

## What was tested

Every scored prediction was made before its match. Five outer test blocks were used:

| Parameters available through | Untouched test block | Matches |
|---:|---:|---:|
| 1959 | 1960–1979 | 8,346 |
| 1979 | 1980–1999 | 12,881 |
| 1999 | 2000–2009 | 9,520 |
| 2009 | 2010–2019 | 9,734 |
| 2019 | 2020–2026 | 6,320 |

Network hyperparameters and probability-layer choices were selected on the immediately preceding inner block, then frozen for the next outer block. The primary metric was three-way logarithmic loss; Brier score, ranked probability score and accuracy were secondary. Paired uncertainty intervals used 20,000 calendar-year cluster-bootstrap draws.

The bake-off included:

- the published World Football Elo formula;
- fixed 20:30:40:50:60 K ratios, a common K, a monotone five-K curve and five independent Ks;
- no goal-margin weighting, the old margin curve, a fitted curve and seven-category G-Elo;
- fixed, median-pool and active-pool debut ratings;
- expectation-preserving, Davidson, ordered-logit and likelihood-score probability/update links;
- scalar Elo, diagonal uncertainty and full opponent-network covariance;
- pooled and match-level state information;
- one, two and five forecast temperatures;
- extra home and draw calibration terms;
- equal and nested probability ensembles;
- a deliberately wider uncertainty-hyperparameter search.

The G-Elo candidate follows the idea of modelling a discretised margin likelihood and updating ratings by its score, as developed in the [G-Elo paper](https://arxiv.org/abs/2010.11187). The uncertainty candidates are related in spirit to Glickman's use of rating deviation, although this model retains the complete cross-team covariance rather than independent RDs; see [Glickman's original article](https://www.glicko.net/ratings/cl-article.pdf).

## K and match importance

### Scalar Elo result

| K structure | Held-out log loss |
|---|---:|
| Common K | **0.893194** |
| Monotone five-level K | 0.893316 |
| Five independent Ks | 0.893556 |
| Published 20:30:40:50:60 ratio | 0.895391 |

Common K beats the monotone ladder by 0.0000974 (95% interval 0.0000252–0.0001802) and five independent Ks by 0.0003622 (95% interval 0.0001755–0.0005671).

The independent estimates themselves are unstable:

| Fit through | Friendly | Other | Qualifier/major | Continental final | World Cup |
|---:|---:|---:|---:|---:|---:|
| 1959 | 10.890 | 7.065 | 11.132 | 14.054 | 13.975 |
| 1979 | 16.208 | 13.166 | 17.329 | 19.237 | 17.243 |
| 1999 | 16.201 | 14.909 | 16.630 | 16.305 | 15.999 |
| 2009 | 15.403 | 13.728 | 15.177 | 15.024 | 16.243 |
| 2019 | 15.703 | 14.123 | 15.364 | 15.420 | 15.333 |

They do not preserve the assumed tournament ordering. The monotone fit collapses to almost a single K after 1960.

### Network result

The network update uses match information rather than a literal constant Elo step. End-to-end competitive/friendly information ratios selected in the five folds were:

`0.727, 0.947, 1.174, 0.979, 1.134`.

Their raw aggregate gain over the common-update model was only 0.0000154 after probability calibration, with a confidence interval crossing zero. The release setting is therefore:

\[
q_{\rm friendly}=q_{\rm other}=q_{\rm qualifier}=q_{\rm continental}=q_{\rm WC}=1.
\]

The user's substantive intuition that friendlies differ from competitive matches is supported, but in the **forecast distribution**, not in a stable state-update K ladder:

\[
P_{\rm final}(o)=\frac{P_{\rm base}(o)^{T_c}}
{\sum_h P_{\rm base}(h)^{T_c}},
\qquad
c\in\{\text{friendly},\text{competitive}\}.
\]

Two temperatures significantly beat one global temperature by 0.000940 log-loss per match (95% interval 0.000500–0.001387). Five temperatures score 0.000067 worse than two, with no significant difference. Extra home and draw shifts overfit badly, scoring 0.888615.

## Other decisive bake-offs

### Goal margin

Removing goal-margin information raises scalar log loss from **0.893194 to 0.899011**. The paired deterioration is 0.005817, with a 95% interval of 0.004603–0.007031. Margin weighting stays.

### Starting ratings

| Debut model | Log loss |
|---|---:|
| Active-pool prior | **0.893194** |
| Constant offset | 0.893959 |
| Raw active-pool median | 0.900008 |

The active-pool prior beats both alternatives significantly. This is the fix for teams such as Denmark debuting implausibly high: a newcomer starts below the contemporary established-team median, with the gap adjusted for the size of the active international pool.

### Full network versus diagonal uncertainty

Using the same broad hyperparameter grid, the full-covariance expectation model scored about **0.88549**, versus **0.89108** for its diagonal approximation. Full covariance is not ornamental: it carries information through the opponent graph and prevents isolated early sub-networks from being treated as globally certain.

### Probability formula

The refined expectation-preserving network scored **0.885274** before the final temperature layer; ordered logit scored **0.885270**. Their paired interval spans zero. The expectation-preserving link is retained because

\[
P(W)+\tfrac12P(D)=E
\]

exactly, so it remains directly interpretable on the Elo expected-score scale.

### Wider uncertainty search

A reparameterised search with extremely broad bounds improved the immediately preceding tuning blocks but worsened the next untouched blocks from **0.884219 to 0.884562**. The paired interval for the deterioration is 0.000150–0.000585. The extreme solutions were hyperparameter overfit; the regularised uncertainty search is retained.

## Exact release model

This is an **Elo-linked dynamic Bayesian opponent-network model**, not classical pairwise scalar Elo. It maintains

\[
\mathbf r\sim N(\boldsymbol\mu,\Sigma)
\]

with the full team-by-team covariance matrix.

### Era curves

The knot years are `1900, 1930, 1960, 1990, 2020`. Values are linearly interpolated; the calibration scale is interpolated in log space and the draw rate in its bounded-logit coordinate.

| Year | Gap scale \(a_y\) | Effective divisor \(400/a_y\) | Home advantage | Equal-strength draw rate |
|---:|---:|---:|---:|---:|
| 1900 | 1.932980 | 206.934 | 73.123 | 0.184517 |
| 1930 | 1.560214 | 256.375 | 96.742 | 0.217433 |
| 1960 | 1.304446 | 306.644 | 112.896 | 0.259656 |
| 1990 | 1.121857 | 356.552 | 112.661 | 0.308676 |
| 2020+ | 1.000000 | 400.000 | 83.534 | 0.325135 |

For team 1 against team 2,

\[
\delta=a_y(\mu_1-\mu_2)+H_yh,
\qquad
E=\frac{1}{1+10^{-\delta/400}}.
\]

Here \(h=+1\) when team 1 is at home, \(-1\) when team 2 is at home, and zero on neutral ground.

### Three-way probabilities

At a fixed gap,

\[
D=p_{D,y}\,4E(1-E),
\qquad W=E-\tfrac12D,
\qquad L=1-E-\tfrac12D.
\]

Let

\[
V=\Sigma_{11}+\Sigma_{22}-2\Sigma_{12}.
\]

The base match probabilities integrate the equations above over

\[
Z\sim N(\delta,a_y^2V),
\]

using 11-point Gauss–Hermite quadrature. Finally apply the friendly or competitive temperature.

The deployment temperatures, fitted on 6,320 matches from 2020–2026 after fitting the state through 2019, are:

| Match class | Temperature | Binary-divisor approximation |
|---|---:|---:|
| Friendly | **0.9697407084** | 412.481 |
| Any competitive match | **1.0635626457** | 376.094 |

The divisor approximation is only intuition; the exact implementation raises all three integrated probabilities to the stated power and renormalises.

### Era-normalised margin information

Immediately before a match, take decisive matches in the previous 20 integer years. For each, define \(x_r=\min(m_r,7)-1\), and calculate

\[
C_y=\frac{20(1.10)+\sum_r x_r}{20+N_y}.
\]

For a decisive result,

\[
m_{\rm eff}=\min\left[7,1+(\min(m,7)-1)
\left(\frac{1.10}{\max(0.10,C_y)}\right)^{1.8802728894}\right].
\]

The information multiplier is

\[
G(m)=
\begin{cases}
3.4866425938,&m=0,\\
1,&0<m_{\rm eff}\le1,\\
1+(m_{\rm eff}-1)(1.7552704592-1),&1<m_{\rm eff}\le2,\\
1.7552704592+(m_{\rm eff}-2)(2.2010473569-1.7552704592),&2<m_{\rm eff}\le3,\\
2.2010473569+1.4677678225(m_{\rm eff}-3),&m_{\rm eff}>3.
\end{cases}
\]

The fitted draw multiplier being above one means a draw is highly informative about two teams being close in strength; it does not make a draw worth more than a win in the outcome score.

### State drift and update

For each participant, before the match,

\[
\Sigma_{tt}\leftarrow\Sigma_{tt}+sigma_{\rm drift}^2\Delta t,
\qquad \sigma_{\rm drift}=19.7502125949
\]

rating points per square-root year. A debutant receives variance

\[
\sigma_0^2,\qquad \sigma_0=300.
\]

For the update, set

\[
\lambda=1.7440260583\,G(m),
\quad
\beta=\frac{\ln 10}{400}a_y,
\quad
g=S-E,
\quad
I=E(1-E),
\]

\[
\mathbf v=\Sigma_{:,1}-\Sigma_{:,2},
\qquad
d=1+\lambda\beta^2IV.
\]

Then

\[
\boldsymbol\mu\leftarrow\boldsymbol\mu+
\mathbf v\frac{\lambda\beta g}{d},
\]

\[
\Sigma\leftarrow\Sigma-
\mathbf v\mathbf v^T\frac{\lambda\beta^2I}{d}.
\]

This is why different consecutive matches between the same teams can move the displayed ratings differently: their means, uncertainties and covariance with the entire opponent network have changed.

### Debut mean

Before a new team's first match, take teams active in the previous four integer years. Use the median of those with at least 30 matches, or those with at least 10 if fewer than five mature teams are available. If the reference pool is empty, use latent zero.

Otherwise,

\[
\mu_{\rm debut}=\operatorname{median}(\mathcal R_y)
-192.9002199173
-84.2486058682\log\left(\frac{A_y+10}{50}\right),
\]

where \(A_y\) is the active-team count. Add 1500 to every latent mean if a conventional Elo-looking display scale is wanted; this additive anchor cannot affect a prediction.

## Direct changes from the published constants

The [World Football Elo methodology](https://eloratings.net/about) uses a 400 divisor, 100-point home advantage, K values 20/30/40/50/60 and the familiar 1/1.5/1.75-plus margin curve.

For a scalar fallback fitted through 11 July 2026:

- K becomes **15.4002014476 for every match class**, changes of **−4.599799, −14.599799, −24.599799, −34.599799 and −44.599799** from 20/30/40/50/60;
- current-era home advantage becomes **83.5336389791**, a change of **−16.4663610209**;
- the current-era base divisor remains **400**; historical effective divisors are shown above;
- the raw fitted margin landmarks become draw 3.486643, one goal 1, two goals 1.755270, three goals 2.201047 and +1.467768 per additional effective goal, with era normalisation;
- starting ratings are replaced by the active-pool prior above.

For the recommended network, the scalar K value is not used directly. Its exact replacement is the covariance update with \(\lambda=1.7440260583G(m)\) and equal competition-class ratios.

## Data-ordering audit

The source represents neutral decisive matches winner-first. That makes a naive classwise calibration model appear implausibly strong. The invalid result was rejected.

All scored models and added probability transforms are invariant to swapping team 1 and team 2. Proper scores and top-label calibration are therefore unaffected. For win/draw/loss classwise calibration only, neutral rows were deterministically reoriented by team index, independent of the result.

## What this does—and does not—establish

This is the best model in the completed bake-off, not a proof of the best possible football forecaster. It does not use squad selection, player strength, injuries, red cards, travel, rest, tactical style or betting markets. The bootstrap is conditional on the five fitted rolling models and does not repeat all parameter fitting inside every resample.

The final 2026 parameter set is trained on all available results and therefore cannot itself have a future test block. Its model class is justified by the nested historical tests above. It should be monitored prospectively and re-baked when a material number of new internationals arrives.

## Reproducibility files

- `great_elo_bakeoff_results_2026-07-14.json`: exact results, confidence intervals, deployment parameters and hashes.
- `elo_objective.cpp`: scalar and full-network evaluators.
- `fit_bakeoff_candidate.py`: scalar candidate fitting.
- `network_bakeoff.py`: uncertainty/network tuning.
- `tune_competition_temperature.py` and `tune_forecast_layer.py`: nested probability-layer tests.
- `analyse_bakeoff.py`: scoring, calibration, subgroup analysis and paired bootstrap.
- `data/elo_matches.npz`: canonical chronological match ledger used by the evaluators.

The machine-readable JSON is authoritative if a displayed rounded value differs in the final decimal place.
