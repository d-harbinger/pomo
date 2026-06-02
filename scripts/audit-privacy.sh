#!/usr/bin/env bash
# One-shot scan of the FULL git history for content that looks like device
# or host identifiers. Run before any public push, after any history rewrite,
# or periodically as a sanity check.
#
# Usage:
#   bash scripts/audit-privacy.sh         — scans full history
#   bash scripts/audit-privacy.sh HEAD~5  — scans only the last 5 commits
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
range="${1:-}"

echo "${YELLOW}audit-privacy: scanning ${range:-full history} against ${#ALL_PATTERNS[@]} pattern(s)${RESET}"

# Self-match excludes — the scanner sources plus lib/patterns.sh (which now
# holds the regex definitions) and the templates/ tree — are single-sourced
# from lib/patterns.sh as PG_EXCLUDE_PATHS. The pre-commit hook reuses the same
# list; gitleaks handles its own via the `[allowlist]` block in .gitleaks.toml.
EXCLUDE_PATHS=( "${PG_EXCLUDE_PATHS[@]}" )

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
  for a in "${ALLOW_VALUES[@]}"; do [ "$v" = "$a" ] && return 0; done
  return 1
}

# Read lines on stdin; print a line only if it still holds a match of $1 whose
# value is NOT declared synthetic. A line whose every match is an allowed value
# is dropped — the same per-value suppression the hook applies.
_filter_unallowed() {
  local pat="$1" line v keep
  while IFS= read -r line; do
    keep=0
    while IFS= read -r v; do
      [ -z "$v" ] && continue
      _is_allowed "$v" || { keep=1; break; }
    done < <(printf '%s\n' "$line" | grep -Eo -- "$pat" 2>/dev/null)
    [ "$keep" -eq 1 ] && printf '%s\n' "$line"
  done
}

hits=0
for pat in "${ALL_PATTERNS[@]}"; do
  # Step 1: check the current tree. Findings here have a different fix path
  # (edit the file + commit) than history-only findings. git grep scans only
  # TRACKED files (so vendored trees like node_modules are skipped) and honors
  # the same EXCLUDE_PATHS pathspecs as the history scan below — including
  # whatever .privacy-allow declared.
  current_matches="$(git grep -nE -e "$pat" -- "${EXCLUDE_PATHS[@]}" 2>/dev/null | _filter_unallowed "$pat" || true)"

  # Step 2: scan history.
  if [ -n "$range" ]; then
    history_matches="$(git log "$range" -p --pickaxe-regex -S "$pat" --pretty=format:'%n--- commit %h ---' -- "${EXCLUDE_PATHS[@]}" 2>/dev/null | grep -E -- "$pat" | _filter_unallowed "$pat" || true)"
  else
    history_matches="$(git log --all -p --pickaxe-regex -S "$pat" --pretty=format:'%n--- commit %h ---' -- "${EXCLUDE_PATHS[@]}" 2>/dev/null | grep -E -- "$pat" | _filter_unallowed "$pat" || true)"
  fi

  if [ -n "$current_matches" ] || [ -n "$history_matches" ]; then
    echo ""
    echo "${RED}Pattern: ${pat}${RESET}"
    if [ -n "$current_matches" ]; then
      echo "${YELLOW}  in current source (fix: edit the file + commit):${RESET}"
      printf '%s\n' "$current_matches" | head -10 | sed 's/^/    /'
    fi
    if [ -n "$history_matches" ]; then
      if [ -n "$current_matches" ]; then
        echo "${YELLOW}  also in history:${RESET}"
      else
        echo "${YELLOW}  in history only (fix: git filter-branch + force-push):${RESET}"
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
else
  echo "${RED}gitleaks not installed — full-history secret scan skipped. Install it:${RESET}"
  echo "  CachyOS / Arch: paru -S gitleaks   (or: sudo pacman -S gitleaks)"
  echo "  Mint / Debian:  https://github.com/gitleaks/gitleaks/releases (linux_x64.tar.gz)"
  hits=$((hits + 1))
fi

echo ""
if [ "$hits" -eq 0 ]; then
  echo "${GREEN}audit-privacy: clean — no patterns matched in scanned range.${RESET}"
  exit 0
else
  echo "${RED}audit-privacy: ${hits} issue(s) found. Review above. If real, scrub via:${RESET}"
  echo "  pip install --user git-filter-repo"
  echo "  echo 'OFFENDING_STRING==>[redacted]' > /tmp/scrub.txt"
  echo "  ~/.local/bin/git-filter-repo --replace-text /tmp/scrub.txt --replace-message /tmp/scrub.txt --force"
  echo "  # re-add origin remote (filter-repo strips it) and force-push"
  exit 1
fi
