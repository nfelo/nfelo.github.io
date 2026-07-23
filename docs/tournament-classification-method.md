# Tournament classification method

## Operational rule

NFELO uses three audit states:

- **friendly** — positive evidence establishes that the matches are
  international friendlies, exhibitions or preparation matches;
- **competitive** — the competition has official championship,
  qualification, league, promotion, relegation or medal consequences;
- **uncertain** — the available evidence is not decisive.

For rating updates, both `competitive` and `uncertain` receive the
competitive multiplier of `1.00`. Unknown future codes also default to
competitive. This is deliberately asymmetric: a competition is
downweighted only after positive friendly evidence.

## Why the method is conservative

Official regulations explicitly distinguish competition matches from
friendly matches. UEFA's EURO regulations, for example, separately
describe friendly matches played when teams are not involved in
competition matches. FIFA likewise distinguishes competitive matches,
such as World Cup qualification, from friendlies. FIFA's own description
of the FIFA Series explicitly states that all its matches are
international friendlies.

Primary references:

- https://documents.uefa.com/r/Regulations-of-the-UEFA-European-Football-Championship-2026-28/Article-25-Friendly-matches-Online
- https://inside.fifa.com/en/transfer-system/agents/match-agents
- https://inside.fifa.com/organisation/media-releases/fifa-series-2026-match-schedule-now-available

## Evidence order

The classifier applies evidence in this order:

1. Date- or edition-specific registry override.
2. Explicit evidence record with an official organiser URL.
3. Official consequences: qualification, playoffs, Nations League,
   promotion or relegation.
4. Exact friendly exceptions such as `FIFA Series`.
5. Recognised official championship or multi-sport-games structure.
6. Unambiguous friendly, invitational, exhibition, memorial or
   anniversary wording.
7. WFER importance levels 2–4 as competitive.
8. Otherwise `uncertain`, operationally competitive.

Official consequences always beat friendly-looking words. Thus a row
called “World Cup qualifier and Memorial Cup” remains competitive.

## Historical competitions

The registry contains every code in the current historical sample.
Ambiguous codes remain `uncertain`, but they are competitive for model
weighting. The registry supports `overrides` with `effective_from` and
`effective_to` dates when the same code changes meaning by edition or
combines multiple competitions.

A secondary historical index may support an exact-title historical
entry, but it cannot override official competition evidence and must
never be matched against undelimited page text.

## Future competitions

Every source refresh applies the classifier during the model replay. A new code is:

- classified automatically when the evidence is decisive;
- otherwise marked `uncertain`;
- treated as competitive immediately;
- available in the standalone audit command's JSON and CSV reports.

This permits unattended source refreshes without risking accidental
downweighting of a new official competition.

To resolve a new ambiguous code, add a record to
`config/tournament_evidence.json`, using
`config/tournament_evidence.example.json` as the template. Official
organiser regulations or an explicit official description are preferred.

## Full-sample coefficient fit

With every evidence-backed friendly code classified as friendly and
every uncertain code operationally competitive:

- complete ledger: 52,312 matches;
- scored period: 46,801 matches from 1960 through 11 July 2026;
- scored friendlies: 16,907;
- coefficient and class temperatures jointly refitted:
  **0.75185**;
- coefficient-only fit with the currently deployed temperatures fixed:
  **0.75408**.

The five-decimal joint optimum is numerically precise for this fixed
historical sample and objective. It is not a five-decimal estimate of
the true population parameter; classification changes and future data
can move it.
