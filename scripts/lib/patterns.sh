#!/usr/bin/env bash
# privacy-guard pattern registry — THE single source of truth.
# Sourced by scripts/hooks/pre-commit, scripts/audit-privacy.sh,
# scripts/probe-scrub.sh (and their templates/ equivalents).
# Edit a pattern HERE and every consumer picks it up; no second copy exists.
#
# Requires bash 4+ (associative arrays). All install targets are Linux bash 5.x.
#
# Each pattern has: a detection regex (POSIX ERE, valid for grep -E AND sed -E),
# an optional scrub replacement (used by probe-scrub), and a scope:
#   commit -> grep consumers only (block at commit / find in history)
#   probe  -> sed consumer only   (scrub from command output)
#   both   -> all three
#
# ORDER MATTERS for the sed program: substitutions run sequentially, so
# vendor_serial must precede generic_serial. PG_PATTERN_NAMES is ordered so the
# probe-scoped slice reproduces the historical SCRUB_SED order exactly.

# Ordered names. Probe/both slice == historical SCRUB_SED order.
PG_PATTERN_NAMES=(
  mac rfc1918_ip imei vendor_serial generic_serial home_path users_path local_hostname
  adb_serial github_pat aws_key anthropic_key openai_key slack_token stripe_key jwt
  pem_key openssh_key pgp_key ssn email phone
)

declare -A PG_REGEX=(
  [mac]='\b([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b'
  [rfc1918_ip]='\b(192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b'
  [imei]='\bIMEI[: ]*[0-9]{15}\b'
  [vendor_serial]='(Samsung|Galaxy|Pixel|Google)([[:space:]]+)[A-Z][A-Z0-9]{6,}\b'
  [generic_serial]='\b[A-Z][0-9A-Z]{9,11}\b'
  [home_path]='/home/[a-z][a-z0-9_-]*/'
  [users_path]='/Users/[A-Za-z][A-Za-z0-9_-]*/'
  [local_hostname]='\b([a-z][a-z0-9-]*)\.local\b'
  [adb_serial]='^[A-Z0-9]{8,16}[[:space:]]+device([[:space:]]|$)'
  [github_pat]='(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})'
  [aws_key]='\bAKIA[0-9A-Z]{16}\b'
  [anthropic_key]='sk-ant-[A-Za-z0-9_-]{32,}'
  [openai_key]='sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}'
  [slack_token]='xox[baprs]-[0-9A-Za-z-]{10,}'
  [stripe_key]='sk_live_[A-Za-z0-9]{24,}'
  [jwt]='eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
  [pem_key]='-----BEGIN [A-Z ]*PRIVATE KEY-----'
  [openssh_key]='-----BEGIN OPENSSH PRIVATE KEY-----'
  [pgp_key]='-----BEGIN PGP PRIVATE KEY BLOCK-----'
  [ssn]='\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b'
  [email]='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
  [phone]='\b[0-9]{3}-[0-9]{3}-[0-9]{4}\b'
)

declare -A PG_REPLACE=(
  [mac]='<mac>'
  [rfc1918_ip]='<lan-ip>'
  [imei]='IMEI:<imei>'
  [vendor_serial]='\1\2<serial>'
  [generic_serial]='<serial>'
  [home_path]='/home/<user>/'
  [users_path]='/Users/<user>/'
  [local_hostname]='<hostname>.local'
  [phone]='<phone>'
)

declare -A PG_SCOPE=(
  [mac]=both [rfc1918_ip]=both [imei]=both [vendor_serial]=both
  [home_path]=both [users_path]=both
  [generic_serial]=probe [local_hostname]=probe
  [adb_serial]=commit [github_pat]=commit [aws_key]=commit [anthropic_key]=commit
  [openai_key]=commit [slack_token]=commit [stripe_key]=commit [jwt]=commit
  [pem_key]=commit [openssh_key]=commit [pgp_key]=commit [ssn]=commit
  [email]=commit [phone]=both
)

# Unified self-match exclude list (union of the two historical lists + the new
# lib files, which now hold the literal regex/PEM definitions). Recursively
# excludes templates/ via a directory pathspec to avoid the `*`-matches-`/`
# footgun the old enumerated list dodged.
PG_EXCLUDE_PATHS=(
  ':(exclude)scripts/hooks/*'
  ':(exclude)scripts/audit-privacy.sh'
  ':(exclude)scripts/lib/patterns.sh'
  ':(exclude).privacy-patterns.example'
  ':(exclude).privacy-allow'
  ':(exclude).privacy-allow.example'
  ':(exclude).gitleaks.toml'
  ':(exclude)templates/'
)

# Print one detection regex per line for grep consumers (scope commit|both).
pg_grep_patterns() {
  local n
  for n in "${PG_PATTERN_NAMES[@]}"; do
    case "${PG_SCOPE[$n]}" in commit|both) printf '%s\n' "${PG_REGEX[$n]}";; esac
  done
}

# Print a sed -E program (s@re@rep@g; per line) for the scrubber (scope probe|both).
# '@' is the delimiter — verified absent from every regex and replacement.
pg_sed_program() {
  local n
  for n in "${PG_PATTERN_NAMES[@]}"; do
    case "${PG_SCOPE[$n]}" in
      probe|both) printf 's@%s@%s@g;\n' "${PG_REGEX[$n]}" "${PG_REPLACE[$n]}";;
    esac
  done
}
