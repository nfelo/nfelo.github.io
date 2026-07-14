# Repository guidance

- Preserve the frozen deployment parameters unless the task explicitly asks
  for a new, reviewed bake-off release.
- Do not replace full covariance with a diagonal approximation.
- Keep every probability pre-match and swap-invariant.
- Preserve first-nine-field deduplication and the official-state same-day order.
- A routine source refresh may update `source/` but must not refit parameters.
- Run `python scripts/build_site.py`, the unittest suite, and
  `node --check public/assets/app.js` before publishing.
- Never commit authentication tokens, cookies, source-site session data, or
  local virtual environments.
