#!/usr/bin/env bash
set -Eeuo pipefail

SELF="$(basename "$0")"
NO_PUSH=false
REBUILD=false
DRY_RUN=false

for argument in "$@"; do
  case "$argument" in
    --no-push) NO_PUSH=true ;;
    --rebuild) REBUILD=true ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help)
      cat <<'EOF'
Usage: bash install-global-club-rankings-v5.sh [options]

  --no-push  Commit the fix locally without pushing it.
  --rebuild  Rebuild/re-export the club archive even if it is already valid.
  --dry-run  Validate and stage everything, but do not commit or push.
EOF
      exit 0
      ;;
    *) printf 'ERROR: Unknown option: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '\n==> %s\n' "$*"; }

REPOSITORY_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" ||
  die "Run this from the nfelo.github.io repository."
cd "$REPOSITORY_ROOT"
[ -f scripts/build_club_site.py ] || die "This is not the NFELO repository root."

note "Checking the installed V3 club code and repository state"
python3 - <<'PY'
import json
from pathlib import Path

configuration = json.loads(Path("config/club_model.json").read_text(encoding="utf-8"))
if configuration.get("version") != "2026-08-11-global-club-v3":
    raise SystemExit(
        "V5 expects the V3 club model to be installed; found "
        + repr(configuration.get("version"))
    )
site_builder = Path("scripts/build_site.py").read_text(encoding="utf-8")
if "validate_prebuilt_club_site" not in site_builder:
    raise SystemExit("The independent prebuilt-club validation hook is missing.")
PY

git fetch --quiet origin main
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse origin/main)"
[ "$LOCAL_HEAD" = "$REMOTE_HEAD" ] ||
  die "Local main is not current. Run 'git pull --ff-only origin main', then run V5 again."

UNEXPECTED="$(
  git status --porcelain --untracked-files=all |
    awk -v self="$SELF" '
      substr($0,4) != self && index(substr($0,4), ".club-install-venv/") != 1 {
        print
      }
    '
)"
[ -z "$UNEXPECTED" ] || {
  printf '%s\n' "$UNEXPECTED" >&2
  die "Resolve the unrelated working-tree changes above before running V5."
}

validate_archive() {
  python3 - <<'PY'
import json
from pathlib import Path

data = Path("public/clubs/data")
required = [
    "meta.json", "bootstrap.json", "rankings.json", "clubs.json",
    "associations.json", "competitions.json", "records.json", "sources.json",
    "matches/index.json", "history/index.json",
]
missing = [name for name in required if not (data / name).is_file()]
if missing:
    raise SystemExit("missing archive files: " + ", ".join(missing))

def read(name):
    return json.loads((data / name).read_text(encoding="utf-8"))

meta = read("meta.json")
catalog = read("clubs.json").get("clubs", [])
match_index = read("matches/index.json")
history_index = read("history/index.json")

if meta.get("model_version") != "2026-08-11-global-club-v3":
    raise SystemExit("the generated archive is not from the V3 club model")
if int(meta.get("matches", 0)) <= 0 or int(meta.get("rated_clubs", 0)) <= 0:
    raise SystemExit("the generated archive metadata is empty")
if len(catalog) != int(meta["rated_clubs"]):
    raise SystemExit("clubs.json does not match meta.json rated_clubs")

match_years = match_index.get("years", [])
if sum(int(row["count"]) for row in match_years) != int(meta["matches"]):
    raise SystemExit("the yearly match index does not match meta.json")
for row in match_years:
    path = data / "matches" / str(row["file"])
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"missing or empty match archive: {path}")
for row in history_index.get("years", []):
    path = data / "history" / str(row["file"])
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"missing or empty history archive: {path}")
for club in catalog:
    path = data / "club" / f"{club['code']}.json"
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"missing or empty club profile: {path}")

print(
    f"Archive validated: {meta['matches']:,} matches, "
    f"{meta['rated_clubs']:,} clubs, through {meta.get('results_through', 'unknown')}."
)
PY
}

ARCHIVE_READY=false
if [ "$REBUILD" = false ] && validate_archive; then
  ARCHIVE_READY=true
  note "Reusing the complete club archive left by V4"
fi

if [ "$ARCHIVE_READY" = false ]; then
  note "The archive needs to be exported; preparing the isolated runtime"
  if [ ! -x .club-install-venv/bin/python ]; then
    python3 -m venv .club-install-venv
  fi
  if ! .club-install-venv/bin/python -c 'import duckdb, numpy, scipy' 2>/dev/null; then
    .club-install-venv/bin/python -m pip install --upgrade pip
    .club-install-venv/bin/python -m pip install --requirement requirements.txt
    .club-install-venv/bin/python -m pip check
  fi

  if [ -s .club-cache/club-ledger.duckdb ] &&
     [ -s .club-cache/club-model.duckdb ] &&
     [ -s .club-cache/manifest.json ]; then
    note "Re-exporting from V4's completed ledger and model cache"
    .club-install-venv/bin/python scripts/build_club_site.py \
      --source source --config config --output public --cache .club-cache \
      --reuse-ledger .club-cache/club-ledger.duckdb \
      --reuse-model .club-cache/club-model.duckdb
  else
    note "No reusable cache was found; replaying the club model once"
    .club-install-venv/bin/python scripts/build_club_site.py \
      --source source --config config --output public --cache .club-cache
  fi
  validate_archive
fi

note "Auditing the generated files against GitHub's per-file limit"
python3 - <<'PY'
from pathlib import Path

root = Path("public/clubs/data")
files = sorted(path for path in root.rglob("*") if path.is_file())
limit = 99_000_000
too_large = [(path, path.stat().st_size) for path in files if path.stat().st_size >= limit]
if too_large:
    details = "\n".join(f"  {size:,} bytes  {path}" for path, size in too_large)
    raise SystemExit(
        "These files are too large for ordinary GitHub storage:\n" + details
    )
total = sum(path.stat().st_size for path in files)
largest = max(files, key=lambda path: path.stat().st_size)
print(f"Archive: {len(files):,} files, {total / 1_000_000:.1f} MB total")
print(f"Largest file: {largest} ({largest.stat().st_size / 1_000_000:.1f} MB)")
PY

python3 -m py_compile \
  scripts/build_club_site.py scripts/build_site.py \
  scripts/club_ledger.py scripts/club_model.py
if command -v node >/dev/null 2>&1; then
  node --check public/clubs/clubs.js
fi

note "Making the club snapshot a permanent, tracked part of the site"
python3 - <<'PY'
from pathlib import Path

path = Path(".gitignore")
lines = path.read_text(encoding="utf-8").splitlines()
filtered = [line for line in lines if line.strip() != "public/clubs/data/"]
if ".club-install-venv/" not in filtered:
    filtered.append(".club-install-venv/")
if filtered != lines:
    path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
PY

git add -- .gitignore public/clubs/index.html
# The V4 deployment failed because this directory was ignored.  -f is
# intentional and non-negotiable: the complete static snapshot must be in the
# commit that GitHub Pages checks out.
git add -f -- public/clubs/data

python3 - <<'PY'
from pathlib import Path
import subprocess

disk = {
    path.as_posix()
    for path in Path("public/clubs/data").rglob("*")
    if path.is_file()
}
tracked_raw = subprocess.check_output(
    ["git", "ls-files", "-z", "--", "public/clubs/data"]
)
tracked = {
    item.decode("utf-8")
    for item in tracked_raw.split(b"\0")
    if item
}
missing = sorted(disk - tracked)
if missing:
    preview = "\n".join("  " + value for value in missing[:20])
    raise SystemExit(
        f"{len(missing)} generated files were not staged:\n{preview}"
    )
required = {
    "public/clubs/data/meta.json",
    "public/clubs/data/bootstrap.json",
    "public/clubs/data/clubs.json",
    "public/clubs/data/matches/index.json",
}
if not required.issubset(tracked):
    raise SystemExit("the Git index is missing required club entry-point files")
print(f"Git index contains all {len(disk):,} generated club files.")
PY

git diff --cached --check

if [ "$DRY_RUN" = true ]; then
  note "Dry run complete; the full archive is validated and staged"
  exit 0
fi

if git ls-files --error-unmatch "$SELF" >/dev/null 2>&1; then
  git rm -- "$SELF"
else
  rm -f -- "$SELF"
fi

git diff --cached --quiet && die "Nothing was staged; the deployment repair was not applied."
git config user.name >/dev/null 2>&1 || git config user.name "NFELO installer"
git config user.email >/dev/null 2>&1 ||
  git config user.email "installer@users.noreply.github.com"
git commit -m "fix: track club archive for Pages deployment"

if [ "$NO_PUSH" = false ]; then
  note "Pushing the deployment repair to main"
  git fetch --quiet origin main
  git merge-base --is-ancestor origin/main HEAD ||
    die "Remote main advanced while V5 was running. The fix is committed locally; rebase it before pushing."
  git push origin HEAD:main
  note "Done. The push has triggered a new Pages validation and deployment."
else
  note "Done. V5 committed the repair locally; --no-push left it for review."
fi
