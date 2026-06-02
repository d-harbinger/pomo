#!/usr/bin/env bash
# privacy-guard / lan-guard — refuse to expose a dev server on an untrusted
# network. Wrap your LAN-exposing dev command with it:
#
#   scripts/lan-guard.sh vite dev --host
#   scripts/lan-guard.sh npm run dev -- --host
#   scripts/lan-guard.sh python -m http.server --bind 0.0.0.0 8000
#
# It runs the wrapped command ONLY when the current Wi-Fi SSID appears in the
# gitignored .lan-allow file (copy .lan-allow.example to create it). On any
# OTHER network — including wired, Wi-Fi off, or SSID undetectable — it
# HARD-ABORTS and the command never starts.
#
# Why fail-closed: binding a dev server to all interfaces (--host / 0.0.0.0) on
# a shared or work network exposes an unauthenticated, source-serving process
# (open HMR socket, your filesystem) to every other device on that LAN — a
# coworker or guest can connect straight into it. Localhost-only binding (plain
# `npm run dev`) has no such exposure; this guard makes the --host path opt-in
# per trusted network.
#
# Scope + limits:
#   - Guards the WRAPPED path only. Running the dev command directly bypasses
#     it. The durable backstop is a host firewall rule limiting the dev port to
#     a trusted subnet.
#   - SSIDs are network identifiers (workspace privacy policy). .lan-allow is
#     gitignored; never commit it. The detected SSID is printed only to your
#     own terminal so you can decide whether to allowlist it.

set -u

err() { printf 'lan-guard: %s\n' "$*" >&2; }

if [ "$#" -eq 0 ]; then
  err "no command given. Usage: lan-guard.sh <dev-command> [args...]"
  exit 2
fi

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
allow="$root/.lan-allow"

if [ ! -f "$allow" ]; then
  err "REFUSING to run: $*"
  err "  no trusted-SSID allowlist at: $allow"
  err "  create it:   cp .lan-allow.example .lan-allow"
  err "  then add the Wi-Fi SSID(s) you trust for dev-server LAN exposure."
  exit 1
fi

# Try the common Linux SSID sources in order; first non-empty wins. iwgetid
# prints the raw SSID; nmcli's -t output prefixes 'yes:' for the active AP; iw
# prints an indented 'ssid <name>' line when connected.
detect_ssid() {
  local s=""
  if command -v iwgetid >/dev/null 2>&1; then
    s="$(iwgetid -r 2>/dev/null || true)"
  fi
  if [ -z "$s" ] && command -v nmcli >/dev/null 2>&1; then
    s="$(nmcli -t -f active,ssid dev wifi 2>/dev/null | sed -n 's/^yes://p' | head -n1 || true)"
  fi
  if [ -z "$s" ] && command -v iw >/dev/null 2>&1; then
    s="$(iw dev 2>/dev/null | sed -n 's/^[[:space:]]*ssid //p' | head -n1 || true)"
  fi
  printf '%s' "$s"
}

ssid="$(detect_ssid)"

if [ -z "$ssid" ]; then
  err "REFUSING to run: $*"
  err "  could not determine a Wi-Fi SSID (wired link, Wi-Fi off, or none of"
  err "  iwgetid/nmcli/iw available). Fail-closed: not exposing the dev server."
  err "  Use plain localhost-only dev instead, or connect to a trusted Wi-Fi."
  exit 1
fi

# Exact-line match against the allowlist; skip blanks and # comments.
matched=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  if [ "$line" = "$ssid" ]; then matched=1; break; fi
done < "$allow"

if [ "$matched" -eq 1 ]; then
  exec "$@"
fi

err "REFUSING to run: $*"
err "  current Wi-Fi network \"$ssid\" is not in your trusted allowlist."
err "  if you trust THIS network for dev-server LAN exposure, add this line to"
err "  $allow :"
err "      $ssid"
exit 1
