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
  mac rfc1918_ip imei vendor_serial generic_serial home_path users_path ws_mount vbox_sf
  local_hostname
  adb_serial github_pat aws_key anthropic_key openai_key slack_token stripe_key jwt
  pem_key openssh_key pgp_key ssn email phone
)

declare -A PG_REGEX=(
  [mac]='\b([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b'
  [rfc1918_ip]='\b(192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b'
  [imei]='\bIMEI[: ]*[0-9]{15}\b'
  [vendor_serial]='(Samsung|Galaxy|Pixel|Google)([[:space:]]+)[A-Z][A-Z0-9]{6,}\b'
  # 10-12 char uppercase-alnum run that contains >=1 DIGIT, starting with a
  # letter. The digit requirement is what makes this value-shaped: a real device
  # serial always carries digits, but an all-uppercase path/route/constant token
  # (e.g. a route file named GETSESSIONS) has none. The old form '[A-Z][0-9A-Z]{9,11}'
  # had no digit anchor and scrubbed such filenames, denying legitimate file reads
  # while protecting nothing. ERE cannot express "fixed length AND contains a digit"
  # compactly, so this is the exact union over the first-digit position for each
  # tail length 9-11 (machine-generated; brute-force-verified equivalent to the
  # spec). It mirrors the commit-side bare-serial filter's "must contain a digit".
  [generic_serial]='\b[A-Z]([0-9][0-9A-Z]{8}|[A-Z]{1}[0-9][0-9A-Z]{7}|[A-Z]{2}[0-9][0-9A-Z]{6}|[A-Z]{3}[0-9][0-9A-Z]{5}|[A-Z]{4}[0-9][0-9A-Z]{4}|[A-Z]{5}[0-9][0-9A-Z]{3}|[A-Z]{6}[0-9][0-9A-Z]{2}|[A-Z]{7}[0-9][0-9A-Z]{1}|[A-Z]{8}[0-9]|[0-9][0-9A-Z]{9}|[A-Z]{1}[0-9][0-9A-Z]{8}|[A-Z]{2}[0-9][0-9A-Z]{7}|[A-Z]{3}[0-9][0-9A-Z]{6}|[A-Z]{4}[0-9][0-9A-Z]{5}|[A-Z]{5}[0-9][0-9A-Z]{4}|[A-Z]{6}[0-9][0-9A-Z]{3}|[A-Z]{7}[0-9][0-9A-Z]{2}|[A-Z]{8}[0-9][0-9A-Z]{1}|[A-Z]{9}[0-9]|[0-9][0-9A-Z]{10}|[A-Z]{1}[0-9][0-9A-Z]{9}|[A-Z]{2}[0-9][0-9A-Z]{8}|[A-Z]{3}[0-9][0-9A-Z]{7}|[A-Z]{4}[0-9][0-9A-Z]{6}|[A-Z]{5}[0-9][0-9A-Z]{5}|[A-Z]{6}[0-9][0-9A-Z]{4}|[A-Z]{7}[0-9][0-9A-Z]{3}|[A-Z]{8}[0-9][0-9A-Z]{2}|[A-Z]{9}[0-9][0-9A-Z]{1}|[A-Z]{10}[0-9])\b'
  [home_path]='/home/[a-z][a-z0-9_-]*/'
  [users_path]='/Users/[A-Za-z][A-Za-z0-9_-]*/'
  # Workspace mount points. Deliberately narrow (named mounts, not all of
  # /mnt/) so container-internal paths like /mnt/storage in compose files
  # don't false-positive; add per-clone mount names to .privacy-patterns.
  [ws_mount]='/mnt/(Projects|shared)\b'
  [vbox_sf]='/media/sf_[A-Za-z0-9_-]+'
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
  [ws_mount]='<workspace>'
  [vbox_sf]='<shared-folder>'
  [local_hostname]='<hostname>.local'
  [phone]='<phone>'
)

declare -A PG_SCOPE=(
  [mac]=both [rfc1918_ip]=both [imei]=both [vendor_serial]=both
  [home_path]=both [users_path]=both [ws_mount]=both [vbox_sf]=both
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
  ':(exclude).egress-allow'
  ':(exclude).egress-allow.example'
  ':(exclude).gitleaks.toml'
  ':(exclude)templates/'

  # Dependency lockfiles: their integrity digests (npm sha512 base64, etc.) contain
  # substrings that false-positive the bare-serial pattern, and lockfiles never carry
  # device/host identifiers. Excluded from the BASH scan only — gitleaks still scans
  # them for real secrets (it does not consult this list). `*` matches `/` in git
  # pathspec, so each entry matches the file at any depth (root + subdirs).
  ':(exclude)*package-lock.json'
  ':(exclude)*pnpm-lock.yaml'
  ':(exclude)*yarn.lock'
  ':(exclude)*npm-shrinkwrap.json'
  ':(exclude)*Cargo.lock'
  ':(exclude)*go.sum'
  ':(exclude)*composer.lock'
  ':(exclude)*poetry.lock'
  ':(exclude)*Gemfile.lock'
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

# ── Egress guard (commit-stage) ──────────────────────────────────────────────
# Third-party network egress is the parallel leak class to device identifiers:
# a memory can't stop an author — or an AI agent — from wiring in a data broker,
# but a commit-side block can. The hook (below) extracts external hostnames from
# staged CODE (http(s):// literals) and blocks any host that is neither a
# universal safe-default (here) nor declared in the repo's committed
# `.egress-allow`. Same posture as the identifier scan: trust a VALUE (an exact
# host or its dot-boundary parent domain), never a path. The origin was a live
# leak — a dashboard widget shipped every bookmarked hostname to google.com's
# favicon service on each load; a memory hadn't stopped it, a gate would have.

# Hosts that are never real egress: reserved / documentation names (RFC 2606 +
# 6761) and XML / SVG / RDF namespace identifiers (a browser never fetches an
# xmlns URI — `http://www.w3.org/2000/svg` is an identifier, not a request).
# Matched by exact host OR dot-boundary suffix, case-insensitive.
PG_EGRESS_SAFE=(
  localhost 127.0.0.1 0.0.0.0 ::1
  local test invalid example
  example.com example.org example.net example.edu
  w3.org schema.org purl.org xmlns.com ns.adobe.com
  sodipodi.sourceforge.net inkscape.org creativecommons.org
)

# 0 if $1 (a host) equals $2, or is a dot-boundary subdomain of $2. A leading
# dot on the pattern is tolerated (".local" and "local" behave the same). The
# dot boundary is what keeps "evil-w3.org" from matching an allowed "w3.org".
pg_host_matches() {
  local host="$1" pat="${2#.}"
  [ "$host" = "$pat" ] && return 0
  case "$host" in *".$pat") return 0;; esac
  return 1
}

# 0 if $1 is a universal safe-default host (exact or dot-boundary suffix).
pg_egress_safe_host() {
  local host="$1" s
  for s in "${PG_EGRESS_SAFE[@]}"; do
    pg_host_matches "$host" "$s" && return 0
  done
  return 1
}

# Read stdin, print one lowercased external hostname per http(s):// URL found.
# Scheme-relative //host is deliberately NOT matched — `//` is too common in
# code and comments to flag without an explicit scheme.
pg_egress_extract() {
  grep -Eoi 'https?://[A-Za-z0-9._~%-]+' \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's#^https?://##' \
    | sort -u
}
