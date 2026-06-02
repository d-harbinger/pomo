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
shopt -s nocasematch

fail_closed() {
    cat >&2 <<EOF
[probe-guard] blocked: $1.

The probe-guard needs a JSON parser (jq, node, or python3) to read the
command reliably. Without one it cannot tell a hardware probe from an
ordinary command, so it blocks rather than risk leaking serials, MACs, or
LAN addresses into the transcript. Install jq (or put node/python3 on PATH)
and retry.
EOF
    exit 2
}

INPUT="$(cat)"

# Extract the command string. Robust JSON parsing is load-bearing: a naive
# grep of "command":"..." stops at the first embedded quote, so
# `echo "x"; adb devices` parses as just `echo \` and the probe slips through.
# Prefer jq; fall back to node, then python3; FAIL CLOSED if none can parse —
# never fall through to a grep that mishandles escaped quotes or newlines.
# python3 is added ahead of the fail-closed branch because it is near-universal
# on Linux/macOS, so the hard block becomes a true last resort rather than a
# routine annoyance on a box that happens to lack jq and node. All three
# branches parse JSON correctly (escaped quotes, multi-line values); the choice
# between them is purely availability.
if command -v jq >/dev/null 2>&1; then
    if ! CMD="$(printf '%s' "$INPUT" | jq -re '.tool_input.command // ""')"; then
        fail_closed "jq could not parse the hook payload"
    fi
elif command -v node >/dev/null 2>&1; then
    if ! CMD="$(printf '%s' "$INPUT" | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>{try{const c=JSON.parse(s).tool_input?.command;process.stdout.write(typeof c==="string"?c:"")}catch(e){process.exit(3)}})')"; then
        fail_closed "node could not parse the hook payload"
    fi
elif command -v python3 >/dev/null 2>&1; then
    if ! CMD="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; c=json.load(sys.stdin).get("tool_input",{}).get("command"); sys.stdout.write(c if isinstance(c,str) else "")')"; then
        fail_closed "python3 could not parse the hook payload"
    fi
else
    fail_closed "no JSON parser (jq, node, or python3) is available to parse the command safely"
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

# Escape hatch, applied PER SEGMENT. The command is split on shell separators
# (; && || | and newline) into segments; a segment that itself invokes
# probe-scrub is trusted (its output gets scrubbed) and skipped. Every OTHER
# segment is still checked against the probe patterns. This closes the old
# whole-command substring escape hatch, where any mention of "probe-scrub"
# anywhere (an echo, a comment, or one scrubbed probe chained with a raw one —
# `probe-scrub.sh lsusb && adb devices`) suppressed the entire scan and let the
# raw probe leak. Splitting on separators is not a full shell parser, but it
# fails toward blocking: a raw probe in any non-scrub segment still trips.
# Replace separators with newlines, then iterate segment by segment.
SEGMENTS="${CMD//&&/$'\n'}"
SEGMENTS="${SEGMENTS//||/$'\n'}"
SEGMENTS="${SEGMENTS//;/$'\n'}"
SEGMENTS="${SEGMENTS//|/$'\n'}"

while IFS= read -r seg; do
    # Strip a trailing comment before deciding whether the segment is trusted,
    # so `adb devices # probe-scrub` cannot earn the exemption from a comment
    # the shell never executes. The exemption test runs on the executable code
    # only; the probe scan below still runs on the full segment.
    code="${seg%%#*}"
    # A segment whose executable code invokes the scrub wrapper is trusted —
    # its output is masked before it reaches the transcript.
    if [[ "$code" == *probe-scrub* ]]; then
        continue
    fi
    for pat in "${PROBE_PATTERNS[@]}"; do
        if [[ "$code" =~ $pat ]]; then
            # Trim leading whitespace from the executable code for a cleaner hint.
            hint="${code#"${code%%[![:space:]]*}"}"
            cat >&2 <<EOF
[probe-guard] blocked: command matches probe-pattern \`$pat\`.

Raw output from this command leaks hardware serials, MAC addresses, LAN
IPs, or DMI identifiers into the Claude Code transcript (Anthropic
server-side store). Re-run through the scrub wrapper:

    bash scripts/probe-scrub.sh $hint

The wrapper masks the identifiers before output. If the raw value is
genuinely needed for diagnostic context, write it to a gitignored
.dev-logs/ file instead of echoing to chat.
EOF
            exit 2
        fi
    done
done <<< "$SEGMENTS"

exit 0
