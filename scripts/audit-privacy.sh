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

BUILTIN_PATTERNS=(
  # Host / device identifiers
  '\b([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b'
  '\b(192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b'
  '/home/[a-z][a-z0-9_-]*/'
  '/Users/[A-Za-z][A-Za-z0-9_-]*/'
  '\bIMEI[: ]*[0-9]{15}\b'
  # ADB-listing-style device serial (token 8-16 chars then "device"). Scanned
  # against file content here (no diff prefix), so the ^ anchor is correct.
  '^[A-Z0-9]{8,16}[[:space:]]+device([[:space:]]|$)'
  '(Samsung|Galaxy|Pixel|Google)[[:space:]]+[A-Z][A-Z0-9]{6,}\b'
  # API keys / tokens
  '(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})'
  '\bAKIA[0-9A-Z]{16}\b'
  'sk-ant-[A-Za-z0-9_-]{32,}'
  'sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}'
  'xox[baprs]-[0-9A-Za-z-]{10,}'
  'sk_live_[A-Za-z0-9]{24,}'
  'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
  # Crypto / signing material
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  '-----BEGIN OPENSSH PRIVATE KEY-----'
  '-----BEGIN PGP PRIVATE KEY BLOCK-----'
  # Personal identifiers
  '\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b'
)

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

# Exclude the scanner sources from the bash-layer scan: their bodies contain
# the regex pattern *definitions* (e.g. `-----BEGIN ... PRIVATE KEY-----`),
# which would self-match. The pre-commit hook applies the same exclusion;
# gitleaks handles it via the `[allowlist]` block in .gitleaks.toml.
#
# templates/* paths are the canonical-source layout for the privacy-guard
# repo itself at <privacy-guard>/. Inert in normal consuming
# projects (no templates/ dir); prevents self-match in the guard repo.
EXCLUDE_PATHS=(
  ':(exclude)scripts/hooks/*'
  ':(exclude)scripts/audit-privacy.sh'
  ':(exclude).privacy-patterns.example'
  ':(exclude).privacy-allow'
  ':(exclude).privacy-allow.example'
  ':(exclude).gitleaks.toml'
  ':(exclude)templates/pre-commit'
  ':(exclude)templates/audit-privacy.sh'
  ':(exclude)templates/gitleaks.toml'
  ':(exclude)templates/privacy-patterns.example'
)

# Demo / synthetic data declared in .privacy-allow (committed, one path-glob
# per line; `#` comments and blank lines ignored). Realistic fixtures —
# sample LAN IPs, demo MACs, seed CSVs — are indistinguishable from a real
# leak to a regex, so the repo declares them once here and the scanner trusts
# the declaration. Unlike .privacy-patterns (per-clone, gitignored, ADDS
# patterns) this is a property of the repo and is committed so every clone
# agrees on what's intentional. Globs use git's :(glob) magic, so write the
# `**` explicitly: `public/samples/**`, `tests/fixtures/**`, `**/*.seed.ts`.
# Both scans below feed off EXCLUDE_PATHS, so these declarations are honored
# in the current tree and in history alike. For a gitleaks-detected match
# inside demo data, add the path to [allowlist].paths in .gitleaks.toml.
allow_file="$repo_root/.privacy-allow"
if [ -f "$allow_file" ]; then
  while IFS= read -r raw; do
    line="${raw%%#*}"                          # strip inline comment
    line="${line#"${line%%[![:space:]]*}"}"    # ltrim
    line="${line%"${line##*[![:space:]]}"}"    # rtrim
    [ -z "$line" ] && continue
    EXCLUDE_PATHS+=(":(exclude,glob)$line")
  done < "$allow_file"
fi

hits=0
for pat in "${ALL_PATTERNS[@]}"; do
  # Step 1: check the current tree. Findings here have a different fix path
  # (edit the file + commit) than history-only findings. git grep scans only
  # TRACKED files (so vendored trees like node_modules are skipped) and honors
  # the same EXCLUDE_PATHS pathspecs as the history scan below — including
  # whatever .privacy-allow declared.
  current_matches="$(git grep -nE -e "$pat" -- "${EXCLUDE_PATHS[@]}" 2>/dev/null || true)"

  # Step 2: scan history.
  if [ -n "$range" ]; then
    history_matches="$(git log "$range" -p --pickaxe-regex -S "$pat" --pretty=format:'%n--- commit %h ---' -- "${EXCLUDE_PATHS[@]}" 2>/dev/null | grep -E -- "$pat" || true)"
  else
    history_matches="$(git log --all -p --pickaxe-regex -S "$pat" --pretty=format:'%n--- commit %h ---' -- "${EXCLUDE_PATHS[@]}" 2>/dev/null | grep -E -- "$pat" || true)"
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
