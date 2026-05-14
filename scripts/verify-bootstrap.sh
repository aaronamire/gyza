#!/usr/bin/env bash
# verify-bootstrap.sh — sanity-check that _dnsaddr.<domain> TXT
# records exist and parse, and that each advertised peer is reachable
# at the UDP/QUIC layer.
#
# Usage:
#   ./scripts/verify-bootstrap.sh [domain]
#
# Default domain: gyza.network
#
# What this script does:
#   1. dig +short _dnsaddr.<domain> TXT
#   2. Parse each "dnsaddr=..." entry, extract /ip4/.../udp/PORT
#   3. nc -uzv each one (UDP probe — won't get a reply from QUIC but
#      will surface a "no route to host" if the IP is wrong)
#
# This is best-effort: QUIC over UDP doesn't respond to nc probes
# cleanly, so a "no reply" is normal. We're checking for routability
# (no ICMP unreachable), not service liveness.
#
# For real liveness, run a daemon locally with --bootstrap-domain=<domain>
# and watch the logs for "connected to <peer-id>".

set -euo pipefail

DOMAIN="${1:-gyza.network}"
TARGET="_dnsaddr.$DOMAIN"

echo "==> Querying $TARGET TXT records"
TXT_RAW=$(dig +short "$TARGET" TXT 2>/dev/null || true)
if [[ -z "$TXT_RAW" ]]; then
    echo "ERROR: no TXT records at $TARGET" >&2
    echo "Hint: confirm at your DNS provider that the record was saved." >&2
    exit 1
fi

count=0
while IFS= read -r line; do
    # dig wraps TXT values in double quotes; strip them.
    line=${line%\"}
    line=${line#\"}
    if [[ "$line" != dnsaddr=* ]]; then
        echo "    skip (not dnsaddr=): $line"
        continue
    fi
    multiaddr="${line#dnsaddr=}"
    echo "    found: $multiaddr"

    # Parse /ip4/X.X.X.X/udp/PORT — best effort.
    ip=$(echo "$multiaddr" | awk -F/ '$2=="ip4"{print $3}')
    port=$(echo "$multiaddr" | awk -F/ '{for(i=1;i<=NF;i++) if($i=="udp") print $(i+1)}')

    if [[ -z "$ip" || -z "$port" ]]; then
        echo "    WARN: could not extract /ip4/PORT from $multiaddr"
        continue
    fi

    # UDP probe. The "echo | nc -u -w 2" form sends an empty datagram and
    # waits 2s; QUIC won't reply, but a network-unreachable host will
    # surface immediately.
    if echo "" | nc -u -w 2 "$ip" "$port" >/dev/null 2>&1; then
        echo "    OK   $ip:$port (UDP packet accepted)"
    else
        echo "    FAIL $ip:$port (UDP unreachable — check firewall + IP)"
    fi
    count=$((count+1))
done <<< "$TXT_RAW"

echo
echo "==> $count bootstrap peer(s) advertised at $TARGET"

if [[ $count -eq 0 ]]; then
    echo "ERROR: no parseable dnsaddr= entries found" >&2
    exit 1
fi

echo
echo "Next: start a local daemon and watch for live connection:"
echo "  gyza-netd --bootstrap-domain=$DOMAIN --log-level=info 2>&1 | grep bootstrap"
