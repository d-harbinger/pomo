#!/usr/bin/env bash
# One-shot scan of the FULL git history for content that looks like device
# or host identifiers. Run before any public push, after any history rewrite,
# or periodically as a sanity check.
#
# Usage:
#   bash scripts/audit-privacy.sh         — scans full history
#   bash scripts/audit-privacy.sh HEAD~5  — scans only the last 5 commits
#   bash scripts/audit-privacy.sh --explain — on a finding, print the rewrite recipes
#
# Exit code 0 = clean, 1 = matches found. Output is the commit SHA + file
# + matching lines, so you can decide whether each hit is a real leak or
# a false positive.
#
# Patterns are the same set the pre-commit hook checks (scripts/hooks/pre-commit
# `BUILTIN_PATTERNS` array) plus anything in a local .privacy-patterns file.
# If you tweak one, mirror the other.

set -e

RED=$'\e[31m'
GREEN=$'\e[32m'
YELLOW=$'\e[33m'
RESET=$'\e[0m'

PG_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/patterns.sh"
if [ ! -f "$PG_LIB" ]; then
  printf '%s\n' "${RED}privacy-guard: pattern library missing at $PG_LIB — install incomplete; re-run install.sh --force${RESET}" >&2
  exit 1
fi
# shellcheck source=lib/patterns.sh
. "$PG_LIB"

# Detection patterns: single-sourced from lib/patterns.sh (scope commit|both).
mapfile -t BUILTIN_PATTERNS < <(pg_grep_patterns)

repo_root="$(git rev-parse --show-toplevel)"
extra_patterns_file="$repo_root/.privacy-patterns"

EXTRA_PATTERNS=()
if [ -f "$extra_patterns_file" ]; then
  while IFS= read -r line; do
    case "$line" in
      ''|'#'*) continue ;;
      *) EXTRA_PATTERNS+=("$line") ;;
    esac
  done < "$extra_patterns_file"
fi

ALL_PATTERNS=("${BUILTIN_PATTERNS[@]}" "${EXTRA_PATTERNS[@]}")

# Default range = entire history. Caller may pass a narrower revision range.
range=""
EXPLAIN=0
for arg in "$@"; do
  case "$arg" in
    --explain) EXPLAIN=1 ;;
    *) range="$arg" ;;
  esac
done

EXCLUDE_PATHS=( "${PG_EXCLUDE_PATHS[@]}" )

# Scope — the paths this project actually writes, declared in the committed
# .privacy-scope (one git pathspec per line, `#` comments). Absent, everything
# is scanned, which is the behaviour every repository has today.
#
# It exists for a shape the value-based allow list cannot express. A fork that
# vendors a large upstream carries that upstream's files, and with them every
# contact address its maintainers put in their own source. One such repository
# matches 128 distinct values that way, around a hundred of them third-party
# addresses and none of them the owner's. Silencing those by value would mean
# committing a list of other people's contact details, which is a worse outcome
# than the finding it answers.
#
# Entries are git pathspecs, so a scope may name the paths a project writes or
# exclude the ones it merely carries. For a fork the second is the practical
# form: listing everything an upstream fork authors is impractical, while
# naming the vendored packaging directory is one line.
#
# That does make this a path exemption, which the allow-list note below refuses
# for values. What makes it safe here is a different control, and it is the
# whole argument: **the commit hook is not scoped**. It reads every staged line
# in every path, so an identifier written into an excluded directory is still
# refused at the moment someone tries to commit it. The audit is the reporting
# control and may be narrowed; the hook is the preventive one and is not.
#
# Verified rather than assumed: staging a file carrying a home path inside a
# scope-excluded directory is still blocked by the hook.
SCOPE_FILE="$repo_root/.privacy-scope"
SCOPE_PATHS=()
if [ -f "$SCOPE_FILE" ]; then
  while IFS= read -r raw; do
    line="${raw%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -z "$line" ] && continue
    SCOPE_PATHS+=("$line")
  done < "$SCOPE_FILE"
fi
if [ "${#SCOPE_PATHS[@]}" -gt 0 ]; then
  PATHSPEC=( "${SCOPE_PATHS[@]}" "${EXCLUDE_PATHS[@]}" )
  SCOPE_NOTE=" · scoped to ${#SCOPE_PATHS[@]} declared path(s) in .privacy-scope"
else
  PATHSPEC=( "${EXCLUDE_PATHS[@]}" )
  SCOPE_NOTE=""
fi

echo "${YELLOW}audit-privacy: scanning ${range:-full history} against ${#ALL_PATTERNS[@]} pattern(s)${SCOPE_NOTE}${RESET}"

# Hook wiring check. The audit reads history; it does not run the commit hook,
# so a clone with no active hook still audits clean. Warn, never fail: the exit
# code stays a verdict on the scanned content alone.
hooks_path="$(git config core.hooksPath 2>/dev/null || true)"
if [ "$hooks_path" != "scripts/hooks" ]; then
  echo "${YELLOW}audit-privacy: warning: core.hooksPath is '${hooks_path:-<unset>}', not 'scripts/hooks' — the commit hook is not active in this clone. Fix: git config core.hooksPath scripts/hooks${RESET}"
elif [ ! -x "$repo_root/scripts/hooks/pre-commit" ]; then
  echo "${YELLOW}audit-privacy: warning: core.hooksPath is 'scripts/hooks' but scripts/hooks/pre-commit is missing or not executable — the commit hook will not run. Fix: re-run install.sh --force${RESET}"
fi

# Self-match excludes — the scanner sources plus lib/patterns.sh (which now
# holds the regex definitions) and the templates/ tree — are single-sourced
# from lib/patterns.sh as PG_EXCLUDE_PATHS. The pre-commit hook reuses the same
# list; gitleaks handles its own via the `[allowlist]` block in .gitleaks.toml.

# Synthetic data declared in .privacy-allow (committed, one literal VALUE per
# line; `#` comments and blank lines ignored). Same file and same value-based
# model as the pre-commit hook: scan everything (only the tool's own source is
# path-excluded above) and suppress a finding ONLY when the matched text is
# exactly a declared value. Allowing a value, never a path, is what stops a real
# identifier from hiding in an allow-listed fixture directory. For a gitleaks-
# detected match inside demo data, use [allowlist] in .gitleaks.toml instead.
allow_file="$repo_root/.privacy-allow"
ALLOW_VALUES=()
if [ -f "$allow_file" ]; then
  while IFS= read -r raw; do
    line="${raw%%#*}"                          # strip inline comment
    line="${line#"${line%%[![:space:]]*}"}"    # ltrim
    line="${line%"${line##*[![:space:]]}"}"    # rtrim
    [ -z "$line" ] && continue
    ALLOW_VALUES+=("$line")
  done < "$allow_file"
fi

_is_allowed() {  # exact match against a declared synthetic value
  local v="$1" a
  for a in "${ALLOW_VALUES[@]}"; do
    [ "$v" = "$a" ] && return 0
    # Several patterns (the address one especially) accept "+" and "-" as value
    # characters, so a sign written next to a value is swallowed into the match
    # and "+ci-bot@example.com" never equals the declared "ci-bot@example.com".
    # The history scan strips the diff marker before matching; this covers the
    # same swallow anywhere else. Compared with the sign stripped as well as
    # with it intact, so a value that genuinely begins with one still matches.
    [ "${v#[+-]}" = "$a" ] && return 0
  done
  return 1
}

# Read lines on stdin; print a line only if it still holds a match of $1 whose
# value is NOT declared synthetic. A line whose every match is an allowed value
# is dropped — the same per-value suppression the hook applies.
#
# Works from the set of distinct values, because a saved web page can be one
# line of several megabytes and bash reads a pipe a byte at a time. A long line
# prints as its start plus the text around the value.
_filter_unallowed() {
  local pat="$1" v
  cat > "$audit_tmp/filter.in"
  : > "$audit_tmp/filter.values"
  while IFS= read -r v; do
    [ -z "$v" ] && continue
    _is_allowed "$v" || printf '%s\n' "$v" >> "$audit_tmp/filter.values"
  done < <(grep -aEo -- "$pat" "$audit_tmp/filter.in" 2>/dev/null | LC_ALL=C sort -u)
  [ -s "$audit_tmp/filter.values" ] || return 0
  grep -aF -f "$audit_tmp/filter.values" "$audit_tmp/filter.in" | LC_ALL=C awk '
    NR == FNR { values[++n] = $0; next }
    length($0) <= 300 { print; next }
    {
      for (i = 1; i <= n; i++) {
        at = index($0, values[i])
        if (at) {
          from = at > 40 ? at - 40 : 1
          print substr($0, 1, 80) " ... " substr($0, from, length(values[i]) + 80) " ..."
          next
        }
      }
    }
  ' "$audit_tmp/filter.values" -
}

hits=0

# PDFs: read each version in the scanned range once, as extracted text and
# metadata. Their raw bytes are marked binary for this run, because they hold no
# readable text and matching a regex across them can take many minutes per
# pattern. See the PDF reader in lib/patterns.sh.
audit_tmp="$(mktemp -d)"
_audit_cleanup() { rm -rf "${audit_tmp:?}"; }
trap _audit_cleanup EXIT
mkdir "$audit_tmp/text"
: > "$audit_tmp/records"
printf '*.[pP][dD][fF] -diff\n' > "$audit_tmp/attributes"
_git() { git -c core.attributesFile="$audit_tmp/attributes" "$@"; }

if [ -n "$range" ]; then log_range=("$range"); else log_range=(--all); fi

# History is written out once and searched with grep. Git's own regex engine is
# quadratic on a long run of address characters, so a saved web page held the
# address pattern for minutes. Every added or removed line is read, so a value
# that moved or was swapped without changing its count is still seen. The leading
# +/- diff marker is stripped: several patterns accept "+" and "-" as value
# characters, so a marker could otherwise stand in for the part before the "@"
# and a line reading "@name.dev" would be reported as an address.
if ! _git log "${log_range[@]}" -p --unified=0 --pretty=format:'%n--- commit %h ---' -- "${PATHSPEC[@]}" > "$audit_tmp/history.raw" 2>/dev/null; then
  echo "${RED}audit-privacy: could not read history for '${range:-all refs}'. Nothing was scanned.${RESET}" >&2
  exit 2
fi
LC_ALL=C sed -E 's/^[+-]//' "$audit_tmp/history.raw" > "$audit_tmp/history"
rm -f "$audit_tmp/history.raw"

# Tracked files as they stand, searched with grep for the same reason.
_tree_grep() {
  git ls-files -z -- "${PATHSPEC[@]}" ':(exclude,icase)*.pdf' \
    | xargs -0 -r env LC_ALL=C grep -InHE -e "$1" -- 2>/dev/null
}

declare -A PDF_BLOBS=()
while IFS= read -r -d '' token; do
  token="${token#$'\n'}"
  case "$token" in :*) ;; *) continue ;; esac
  IFS= read -r -d '' changed_path || break
  case "${changed_path,,}" in *.pdf) ;; *) continue ;; esac
  read -r _ _ _ blob _ <<<"$token"
  case "$blob" in ''|*[!0]*) ;; *) continue ;; esac
  [ -n "$blob" ] || continue
  [ -n "${PDF_BLOBS[$blob]:-}" ] || PDF_BLOBS[$blob]="$changed_path"
done < <(git -c core.quotePath=false log "${log_range[@]}" -m --no-renames --raw --no-abbrev --format= -z --diff-filter=ACMRT -- "${PATHSPEC[@]}" 2>/dev/null || true)

if [ "${#PDF_BLOBS[@]}" -gt 0 ]; then
  if ! pg_pdf_tools_ready; then
    echo "${RED}audit-privacy: ${#PDF_BLOBS[@]} PDF version(s) cannot be read: install poppler (pdfinfo, pdftotext, pdfdetach).${RESET}"
    hits=$((hits + 1))
  else
    pdf_n=0
    pdf_refused=""
    for blob in "${!PDF_BLOBS[@]}"; do
      pdf_n=$((pdf_n + 1))
      pdf_name="${PDF_BLOBS[$blob]}"
      git cat-file blob "$blob" > "$audit_tmp/current.pdf"
      pdf_text="$audit_tmp/text/$pdf_n-$(basename "$pdf_name" | cut -c1-100).txt"
      pdf_rc=0
      pg_pdf_extract "$audit_tmp/current.pdf" "$pdf_text" || pdf_rc=$?
      if [ "$pdf_rc" -ne 0 ] && ! _is_allowed "pdf-blob:$blob"; then
        pdf_refused="${pdf_refused}    ${pdf_name}: $(pg_pdf_problem "$pdf_rc")
      pdf-blob:${blob}
"
      fi
      if [ -f "$pdf_text" ]; then
        PDF_NAME="$pdf_name (PDF text)" awk 'BEGIN { f = ENVIRON["PDF_NAME"] } { printf "%s:%d:%s\n", f, NR, $0 }' "$pdf_text" >> "$audit_tmp/records"
      fi
    done
    rm -f "$audit_tmp/current.pdf"
    echo "${YELLOW}audit-privacy: read ${#PDF_BLOBS[@]} PDF version(s) as text${RESET}"
    if [ -n "$pdf_refused" ]; then
      echo ""
      echo "${RED}PDFs that could not be fully read:${RESET}"
      printf '%s' "$pdf_refused"
      echo "${YELLOW}  After checking a file by eye, declare its pdf-blob: line in .privacy-allow.${RESET}"
      hits=$((hits + 1))
    fi
  fi
fi

for pat in "${ALL_PATTERNS[@]}"; do
  # Step 1: check the current tree. Findings here have a different fix path
  # (edit the file + commit) than history-only findings. Only TRACKED files are
  # read (so vendored trees like node_modules are skipped), under the same
  # EXCLUDE_PATHS pathspecs as the history scan.
  current_matches="$(_tree_grep "$pat" | _filter_unallowed "$pat" || true)"
  pdf_matches="$(LC_ALL=C grep -aE -- "$pat" "$audit_tmp/records" | _filter_unallowed "$pat" || true)"

  # Step 2: scan the history written out above.
  history_matches="$(LC_ALL=C grep -aE -- "$pat" "$audit_tmp/history" | _filter_unallowed "$pat" || true)"

  if [ -n "$current_matches" ] || [ -n "$history_matches" ] || [ -n "$pdf_matches" ]; then
    echo ""
    echo "${RED}Pattern: ${pat}${RESET}"
    if [ -n "$pdf_matches" ]; then
      echo "${YELLOW}  in PDF text or metadata:${RESET}"
      printf '%s\n' "$pdf_matches" | head -10 | sed 's/^/    /'
    fi
    if [ -n "$current_matches" ]; then
      echo "${YELLOW}  in current source (fix: edit the file + commit):${RESET}"
      printf '%s\n' "$current_matches" | head -10 | sed 's/^/    /'
    fi
    if [ -n "$history_matches" ]; then
      if [ -n "$current_matches" ]; then
        echo "${YELLOW}  also in history:${RESET}"
      else
        echo "${YELLOW}  in history only (fix: a history rewrite, see below):${RESET}"
      fi
      printf '%s\n' "$history_matches" | head -10 | sed 's/^/    /'
    fi
    hits=$((hits + 1))
  fi
done

echo ""
echo "${YELLOW}--- gitleaks detect (full history, default ruleset + .gitleaks.toml allowlist) ---${RESET}"
if command -v gitleaks >/dev/null 2>&1; then
  # `gitleaks detect` scans all commits; --no-banner suppresses the ASCII logo;
  # --redact keeps any matched secret out of stdout/scrollback. Non-zero exit
  # from gitleaks counts as one additional hit.
  if gitleaks detect --redact --no-banner --config="$repo_root/.gitleaks.toml"; then
    echo "${GREEN}gitleaks: clean${RESET}"
  else
    echo "${RED}gitleaks: secrets detected (see above).${RESET}"
    hits=$((hits + 1))
  fi
  if [ "${#PDF_BLOBS[@]}" -gt 0 ] && pg_pdf_tools_ready; then
    if gitleaks detect --no-git --source "$audit_tmp/text" --redact --verbose --no-banner --config="$repo_root/.gitleaks.toml"; then
      echo "${GREEN}gitleaks on PDF text: clean${RESET}"
    else
      echo "${RED}gitleaks on PDF text: secrets detected (see above; the file is the PDF's number and name).${RESET}"
      hits=$((hits + 1))
    fi
  fi
else
  echo "${RED}gitleaks not installed — full-history secret scan skipped. Install it:${RESET}"
  echo "  Arch / CachyOS: sudo pacman -S gitleaks"
  echo "  Mint / Debian:  https://github.com/gitleaks/gitleaks/releases (linux_x64.tar.gz)"
  hits=$((hits + 1))
fi

echo ""
if [ "$hits" -eq 0 ]; then
  if [ -n "$SCOPE_NOTE" ]; then
    echo "${GREEN}audit-privacy: clean within the declared scope — ${#SCOPE_PATHS[@]} path(s); paths outside .privacy-scope were NOT scanned.${RESET}"
  else
    echo "${GREEN}audit-privacy: clean — no patterns matched in scanned range.${RESET}"
  fi
  exit 0
else
  echo "${RED}audit-privacy: ${hits} issue(s) found. Review above.${RESET}"
  if [ "$EXPLAIN" -eq 0 ]; then
    echo "  A value in the working tree is fixed by editing the file and committing."
    echo "  A value in history needs a git-filter-repo rewrite: rerun with --explain for the recipes."
    exit 1
  fi
  echo "  pip install --user git-filter-repo   # both recipes need it"
  echo ""
  echo "  Pick the recipe by WHERE the value is. The two are not interchangeable:"
  echo "  a value in a file and a value in commit metadata need different flags,"
  echo "  and running the wrong one rewrites history without removing anything."
  echo ""
  echo "  1. In FILE CONTENTS or a COMMIT MESSAGE — check with:"
  echo "       git log -S'OFFENDING_STRING' --oneline"
  echo "     scrub=\$(mktemp); echo 'OFFENDING_STRING==>[redacted]' > \"\$scrub\""
  echo "     ~/.local/bin/git-filter-repo --replace-text \"\$scrub\" --replace-message \"\$scrub\" --force"
  echo ""
  echo "  2. In AUTHOR or COMMITTER identity (a name or an address attached to the"
  echo "     commit itself, which no grep over tracked files will ever show) — check with:"
  echo "       git log --format='%an <%ae>' | sort -u"
  echo "     map=\$(mktemp); printf 'Name <good@address> <leaked@address>\\n' > \"\$map\""
  echo "     ~/.local/bin/git-filter-repo --mailmap \"\$map\" --force"
  echo ""
  echo "  Then, for either: re-add the origin remote (filter-repo strips it) and force-push."
  echo "  Before that: 'git bundle create <repo>.bundle --all' is a complete, restorable backup."
  echo "  After that: every commit hash changes, so existing clones break and any hash"
  echo "  quoted elsewhere (notes, boards, issues) goes stale — .git/filter-repo/commit-map"
  echo "  holds the old-to-new mapping needed to repair them."
  exit 1
fi
