# Install global club rankings

This package replaces the oversized all-in-one workflow. The workflow is only
about 6 KB; its audited 809 KB compressed application patch is stored beside it
as ordinary repository data.

## Install

1. Extract this ZIP into the root of a local clone of `nfelo.github.io`.
2. Confirm that extraction created:
   - `.github/workflows/install-global-club-rankings.yml`
   - `.github/installers/global-club-rankings.patch.gz`
   - `INSTALL-GLOBAL-CLUB-RANKINGS.md`
3. Commit and push those three files to `main`:

   ```bash
   git add .github/workflows/install-global-club-rankings.yml \
     .github/installers/global-club-rankings.patch.gz \
     INSTALL-GLOBAL-CLUB-RANKINGS.md
   git commit -m "chore: add one-time club rankings bootstrap"
   git push origin main
   ```

4. In GitHub Actions, open **Install global club rankings** and choose
   **Run workflow**.

The bootstrap verifies both payload checksums, applies the update, rebuilds the
national-team and club sites, runs all tests, removes these three bootstrap
files, commits the verified installation, and dispatches the existing Pages
workflow. It does not modify `.github/workflows/pages.yml`.

If `main` advances while the build is running, the bootstrap stops without
pushing. Run it again from the new `main` revision.
