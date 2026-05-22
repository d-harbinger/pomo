#!/usr/bin/env bash
# Claude Code PreToolUse hook for the Bash tool.
#
# Rejects raw identifier-leaking system probes (adb devices, lsusb,
# ip addr, …) with a message pointing at scripts/probe-scrub.sh.
# If the command already pipes through probe-scrub.sh anywhere, it's
# allowed through.
#
# Wired up by .claude/settings.json. Exit code 2 = block the tool
# call and show stderr to the model; exit code 0 = allow.
set -euo pipefail

INPUT="$(cat)"

# jq is the cleanest extractor; fall back to a grep+cut shape if jq is
# missing so the hook never fails open on an environment with no jq.
if command -v jq >/dev/null 2>&1; then
    CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')"
else
    CMD="$(printf '%s' "$INPUT" \
        | grep -oE '"command"[[:space:]]*:[[:space:]]*"[^"]*"' \
        | head -1 \
        | sed -E 's/.*"command"[[:space:]]*:[[:space:]]*"//; s/"$//')"
fi

# Escape hatch: if the command already routes through probe-scrub.sh,
# trust the wrapper's scrubbing and let it through.
if [[ "$CMD" == *probe-scrub* ]]; then
    exit 0
fi

# Patterns are ERE. Each one names a probe that prints hardware
# serials, MACs, internal IPs, or DMI identifiers by default.
PROBE_PATTERNS=(
    '\badb[[:space:]]+devices\b'
    '\blsusb\b'
    '\bdmidecode\b'
    '\bifconfig\b'
    '\bip[[:space:]]+(addr|a\b|link\b)'
    '\biw[[:space:]]+(dev|list)\b'
    '\bnmcli[[:space:]]+(dev|connection|radio)\b'
    'cat[[:space:]]+/proc/cpuinfo'
    'cat[[:space:]]+/sys/class/dmi/'
    'cat[[:space:]]+/sys/class/net/[^[:space:]]+/address'
)

for pat in "${PROBE_PATTERNS[@]}"; do
    if [[ "$CMD" =~ $pat ]]; then
        cat >&2 <<EOF
[probe-guard] blocked: command matches probe-pattern \`$pat\`.

Raw output from this command leaks hardware serials, MAC addresses, LAN
IPs, or DMI identifiers into the Claude Code transcript (Anthropic
server-side store). Re-run through the scrub wrapper:

    bash scripts/probe-scrub.sh $CMD

The wrapper masks the identifiers before output. If the raw value is
genuinely needed for diagnostic context, write it to a gitignored
.gsd-logs/ file instead of echoing to chat.
EOF
        exit 2
    fi
done

exit 0
