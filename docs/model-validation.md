# Model validation

The published model was selected using rolling historical evaluation. At each
test stage, model choices were made from earlier matches and scored on a later
period that had not been used for that choice.

The evaluation covered 46,801 match predictions from 1960 to 2026. The primary
measure was three-way logarithmic loss because it evaluates the full win, draw
and loss probability distribution and penalises unjustified certainty. Brier
score, ranked probability score and most-likely-outcome accuracy were secondary
measures.

| Measure | Network Football Elo | Comparison World Football Elo forecast |
| --- | ---: | ---: |
| Log loss | 0.884219 | 0.902619 |
| Brier score | 0.520573 | — |
| Ranked probability score | 0.173179 | — |
| Most-likely-outcome accuracy | 59.095% | — |

Lower values are better for log loss, Brier score and ranked probability score.

The model uses a common evidence weight for friendly and competitive results.
Allowing separate update weights produced no stable improvement across the
historical test periods. Friendly and competitive matches still use separate
probability-calibration settings.

The evaluation also supported:

- retaining uncertainty shared across the opponent network;
- adjusting scoring margins for the historical goal environment;
- allowing home advantage and draw frequency to change by era; and
- starting new teams relative to the active international pool.

Exact deployed parameters are stored in `config/elo_matches.json`. The full
equations, parameter table, display-rating definition and limitations are on the
site's [Methodology page](https://benyominnemoff-lab.github.io/network-football-elo/#/methodology).

This is historical out-of-sample evidence, not proof that the model will be best
on every future period. Routine data updates do not change its parameters.
