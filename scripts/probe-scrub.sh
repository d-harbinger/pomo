#!/usr/bin/env bash
# Wrap an identifier-leaking system probe (adb devices, lsusb, ip addr, …)
# and scrub PII from its output before printing. Use this in place of the
# bare command whenever you want to see device or network state.
#
# Usage:
#   bash scripts/probe-scrub.sh adb devices -l
#   bash scripts/probe-scrub.sh lsusb
#   bash scripts/probe-scrub.sh ip addr show
#
# Also accepts piped input:
#   adb devices -l | bash scripts/probe-scrub.sh
#   cat some-log.txt | bash scripts/probe-scrub.sh
#
# Why this exists:
#   `adb devices` and friends print hardware serials, MAC addresses,
#   internal LAN IPs, and similar identifiers as their default output.
#   In a normal terminal that lands in scrollback; under Claude Code
#   it also lands in the conversation transcript on the Anthropic
#   server. The patterns below mirror scripts/audit-privacy.sh +
#   scripts/hooks/pre-commit; if you tweak one, mirror the others.
set -euo pipefail

PG_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/patterns.sh"
if [ ! -f "$PG_LIB" ]; then
  printf '%s\n' "privacy-guard: pattern library missing at $PG_LIB — install incomplete; re-run install.sh --force" >&2
  exit 1
fi
# shellcheck source=lib/patterns.sh
. "$PG_LIB"

SCRUB_SED="$(pg_sed_program)"

if [[ $# -gt 0 ]]; then
    # Run the supplied command; merge stderr into stdout so probe errors
    # also get scrubbed (e.g. "no permissions; see [URL] for udev rules").
    "$@" 2>&1 | sed -E "$SCRUB_SED"
    # Preserve the wrapped command's exit code. `set -o pipefail` above
    # makes the sed pipeline carry the upstream exit through.
    exit "${PIPESTATUS[0]}"
else
    sed -E "$SCRUB_SED"
fi
