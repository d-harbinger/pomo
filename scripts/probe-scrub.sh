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

SCRUB_SED='
    s/\b([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b/<mac>/g;
    s/\b(192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b/<lan-ip>/g;
    s/\bIMEI[: ]*[0-9]{15}\b/IMEI:<imei>/g;
    s/(Samsung|Galaxy|Pixel|Google)([[:space:]]+)[A-Z][A-Z0-9]{6,}\b/\1\2<serial>/g;
    s/\b[A-Z][0-9A-Z]{9,11}\b/<serial>/g;
    s|/home/[a-z][a-z0-9_-]*/|/home/<user>/|g;
    s|/Users/[A-Za-z][A-Za-z0-9_-]*/|/Users/<user>/|g;
    s/\b([a-z][a-z0-9-]*)\.local\b/<hostname>.local/g;
'

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
