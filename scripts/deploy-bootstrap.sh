#!/usr/bin/env bash
# deploy-bootstrap.sh — provision a fresh Ubuntu VPS as a Gyza bootstrap
# peer. Idempotent: re-running upgrades the binary and restarts the
# daemon without losing the identity key.
#
# Usage:
#   ./scripts/deploy-bootstrap.sh <ssh-target> <node-name>
#
# Example:
#   ./scripts/deploy-bootstrap.sh root@198.51.100.42 eu-bootstrap-1
#
# Prerequisites on the target VPS:
#   * Ubuntu 22.04 or 24.04
#   * Root SSH access (or a user with passwordless sudo)
#   * UDP port 7749 reachable from the public internet
#
# What this script does on the VPS:
#   1. apt update + install Go 1.22+ and build deps
#   2. Clone (or pull) https://github.com/<TBD>/gyza-rs into /opt/gyza
#      — for now uses local rsync until the repo is public.
#   3. Build gyza-netd into /usr/local/bin/gyza-netd
#   4. Create a gyza system user with $HOME=/var/lib/gyza
#   5. Generate ~/.gyza/compositor.key if it doesn't exist (32 bytes
#      from /dev/urandom, mode 0600)
#   6. Compute the peer ID via `gyza-netd --print-peer-id`
#   7. Install a systemd unit and enable it
#   8. Open UDP 7749 in ufw
#   9. Print the multiaddr to add to _dnsaddr.gyza.network TXT records
#
# What this script does NOT do:
#   * Configure DNS — that's a manual step at your DNS provider, using
#     the multiaddr this script prints at the end.
#   * Install TLS certs — bootstrap peers don't serve HTTP.
#   * Mutual auth between peers — handled by libp2p Noise.

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <ssh-target> <node-name>" >&2
    echo "Example: $0 root@198.51.100.42 eu-bootstrap-1" >&2
    exit 2
fi

SSH_TARGET="$1"
NODE_NAME="$2"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Sanity-check the local repo before we ship anything to the VPS.
if [[ ! -f "$REPO_ROOT/netd/cmd/gyza-netd/main.go" ]]; then
    echo "ERROR: $REPO_ROOT/netd/cmd/gyza-netd/main.go not found." >&2
    echo "Run this script from the gyza repo root." >&2
    exit 2
fi

echo "==> Deploying $NODE_NAME to $SSH_TARGET"

# -----------------------------------------------------------------------
# Step 1: rsync the source tree to the VPS.
# We build on the VPS rather than cross-compiling so the binary matches
# the target glibc / kernel. The /opt/gyza directory is owned by root;
# the gyza user only needs read access to the binary.
# -----------------------------------------------------------------------
echo "==> Copying source to /opt/gyza on target"
ssh "$SSH_TARGET" "mkdir -p /opt/gyza"
rsync -az --delete \
    --exclude='/.git' \
    --exclude='/gyza-rs/target' \
    --exclude='/netd/bin' \
    --exclude='/__pycache__' \
    --exclude='*.pyc' \
    --exclude='/.gyza' \
    --exclude='/spec/states' \
    --exclude='/.pytest_cache' \
    --exclude='/.ruff_cache' \
    --exclude='/.mypy_cache' \
    --exclude='/.cache' \
    --exclude='/node_modules' \
    "$REPO_ROOT/" "$SSH_TARGET:/opt/gyza/"

# -----------------------------------------------------------------------
# Step 2: install Go (if needed), build the daemon, set up systemd.
# We POST a heredoc script to the VPS rather than running each command
# in a separate SSH invocation — fewer round-trips, atomic execution,
# easier error handling.
# -----------------------------------------------------------------------
echo "==> Provisioning on target"
ssh "$SSH_TARGET" "NODE_NAME=$NODE_NAME bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

# Ensure we have apt updates + base tools.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq rsync ufw curl ca-certificates >/dev/null

# Go 1.22+ — Ubuntu's default is too old; install from the upstream
# tarball pinned to a known version.
GO_VERSION=1.23.4
if ! command -v go &>/dev/null || ! go version | grep -q "go${GO_VERSION}"; then
    echo "    installing Go ${GO_VERSION}"
    cd /tmp
    curl -sSL -o "go${GO_VERSION}.tar.gz" \
        "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
    rm -rf /usr/local/go
    tar -C /usr/local -xzf "go${GO_VERSION}.tar.gz"
    rm -f "go${GO_VERSION}.tar.gz"
fi
export PATH=/usr/local/go/bin:$PATH

# Build the daemon.
echo "    building gyza-netd"
cd /opt/gyza/netd
/usr/local/go/bin/go build -o /usr/local/bin/gyza-netd ./cmd/gyza-netd/
chmod 0755 /usr/local/bin/gyza-netd

# System user.
if ! id gyza &>/dev/null; then
    echo "    creating gyza user"
    useradd --system --create-home --home-dir /var/lib/gyza \
        --shell /usr/sbin/nologin gyza
fi

# Key generation (idempotent — preserves existing key).
KEY_PATH=/var/lib/gyza/.gyza/compositor.key
SOCKET_DIR=/var/lib/gyza/.gyza
mkdir -p "$SOCKET_DIR"
chown gyza:gyza "$SOCKET_DIR"
chmod 0700 "$SOCKET_DIR"
if [[ ! -f "$KEY_PATH" ]]; then
    echo "    generating new compositor key"
    head -c 32 /dev/urandom > "$KEY_PATH"
    chmod 0600 "$KEY_PATH"
    chown gyza:gyza "$KEY_PATH"
else
    echo "    keeping existing compositor key"
fi

# Compute peer ID for the DNS record. Runs as the gyza user so it can
# read the key under that ownership.
PEER_ID=$(sudo -u gyza /usr/local/bin/gyza-netd \
    --print-peer-id --key-path="$KEY_PATH")
echo "    peer_id = $PEER_ID"
echo "$PEER_ID" > /var/lib/gyza/peer_id.txt
chown gyza:gyza /var/lib/gyza/peer_id.txt

# Public IP (best effort — fall back to hostname -I if curl fails).
PUBLIC_IP=$(curl -4 -sSf https://api.ipify.org 2>/dev/null \
    || hostname -I | awk '{print $1}')
echo "    public_ip = $PUBLIC_IP"
echo "$PUBLIC_IP" > /var/lib/gyza/public_ip.txt

# Systemd unit. Bootstrap nodes run with --dht-mode=server so they
# actively participate in routing (rather than waiting for AutoNAT to
# promote them), and with --enable-relay-service so NATed peers can
# circuit-relay through them.
cat > /etc/systemd/system/gyza-netd.service <<UNIT
[Unit]
Description=Gyza network daemon ($NODE_NAME)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=gyza
Group=gyza
ExecStart=/usr/local/bin/gyza-netd \
    --socket-path=/var/lib/gyza/.gyza/netd.sock \
    --key-path=/var/lib/gyza/.gyza/compositor.key \
    --listen-port=7749 \
    --dht-mode=server \
    --enable-relay-service \
    --bootstrap-domain=gyza.network \
    --log-level=info
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/gyza
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
chmod 0644 /etc/systemd/system/gyza-netd.service

systemctl daemon-reload
systemctl enable gyza-netd.service
systemctl restart gyza-netd.service

# Firewall.
ufw allow 7749/udp comment 'gyza-netd libp2p QUIC' >/dev/null
ufw allow 22/tcp comment 'ssh' >/dev/null
# Don't force-enable ufw — that can lock the user out if they're
# managing the box over ssh and the SSH rule didn't take. They can run
# `ufw enable` manually after verifying SSH stays open.

# Sanity check: did the daemon actually come up?
sleep 2
if ! systemctl is-active --quiet gyza-netd.service; then
    echo "ERROR: gyza-netd.service failed to start" >&2
    journalctl -u gyza-netd.service --since="1 minute ago" --no-pager | tail -30 >&2
    exit 1
fi

# -----------------------------------------------------------------------
# Hosted demo agent (Python). Runs as a sidecar service that claims
# free-text work items submitted to gyza-demo-public-v1 via `gyza
# submit ...`. Deterministic executor in v0.1 — no LLM, no shell exec.
# Installed into a dedicated venv so we don't touch system Python.
# -----------------------------------------------------------------------
echo "    installing gyza Python package for demo agent"
apt-get install -y -qq python3-venv python3-pip build-essential python3-dev >/dev/null

# Re-create the venv idempotently. ``--system-site-packages`` is
# avoided so the venv pins its own dependency versions.
if [[ ! -x /opt/gyza/agent-venv/bin/python ]]; then
    python3 -m venv /opt/gyza/agent-venv
fi
# Upgrade pip first — old pip versions choke on modern wheels.
/opt/gyza/agent-venv/bin/pip install -q --upgrade pip >/dev/null

# Install gyza editable. Skip the [embeddings] extra — the demo
# agent uses a stub specialization vector and doesn't need
# sentence-transformers (~500 MB RAM). Skip [dev] for the same
# reason.
/opt/gyza/agent-venv/bin/pip install -q -e /opt/gyza >/dev/null

chown -R gyza:gyza /opt/gyza/agent-venv

# Systemd unit for the demo agent. Depends on gyza-netd.service
# (the agent connects to the daemon's Unix socket). Restart=always
# so a transient daemon hiccup doesn't permanently take the agent
# down.
cat > /etc/systemd/system/gyza-demo-agent.service <<UNIT
[Unit]
Description=Gyza demo agent ($NODE_NAME) — claims public demo work items
Requires=gyza-netd.service
After=gyza-netd.service

[Service]
Type=simple
User=gyza
Group=gyza
Environment=HOME=/var/lib/gyza
WorkingDirectory=/var/lib/gyza
ExecStart=/opt/gyza/agent-venv/bin/gyza demo-agent --socket-path=/var/lib/gyza/.gyza/netd.sock
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/gyza
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
chmod 0644 /etc/systemd/system/gyza-demo-agent.service

systemctl daemon-reload
systemctl enable gyza-demo-agent.service
systemctl restart gyza-demo-agent.service

# Give it a moment to boot up before sanity-checking. The agent
# imports take a few seconds (numpy + cryptography + grpcio).
sleep 8
if ! systemctl is-active --quiet gyza-demo-agent.service; then
    echo "WARN: gyza-demo-agent.service did not start cleanly" >&2
    journalctl -u gyza-demo-agent.service --since="1 minute ago" --no-pager | tail -20 >&2
    echo "(continuing — bootstrap node is still functional without the agent)" >&2
fi

# Output the multiaddr the operator needs to add to DNS.
MULTIADDR="/ip4/$PUBLIC_IP/udp/7749/quic-v1/p2p/$PEER_ID"
echo
echo "==================================================================="
echo " Deployment of $NODE_NAME complete."
echo "==================================================================="
echo
echo " Add this TXT record to your DNS provider for gyza.network:"
echo
echo "   Name:  _dnsaddr.gyza.network"
echo "   Type:  TXT"
echo "   Value: dnsaddr=$MULTIADDR"
echo
echo " (Repeat for each bootstrap node — multiple TXT records on the"
echo "  same _dnsaddr.<domain> are merged by the libp2p resolver.)"
echo
echo " Daemon status: $(systemctl is-active gyza-netd.service)"
echo " Logs:          journalctl -u gyza-netd.service -f"
echo "==================================================================="
REMOTE_SCRIPT

echo
echo "==> $NODE_NAME deployed."
