"""Arena 1 — RTT sweep of the post-heal silent-loss window, using tc netem.

Preregistered in PREREGISTRATION_NETEM.md
(sha256 1b667ed63785b3aa86cba64297505d47b228e1c0b4a45947be1af8e1ed13fe8d,
written 2026-08-29 10:50:02, BEFORE this file existed).

WHAT THIS MEASURES. HEAL_WINDOW.md established, on loopback, that an item
published after `connect_peer` reports success but before the gossip mesh
re-GRAFTs is PERMANENTLY lost. Its width was unknown. This sweeps RTT as an
independent variable and measures the width at each point, which tests the WAN
preregistration's P3 and P4 -- both of which are RTT-DEPENDENCE claims -- for
$0 instead of $4.32.

WHAT IT DOES NOT MEASURE. Real WAN. netem gives controlled delay, not route
flap, BGP reconvergence, MTU discovery or bursty jitter. The WAN run still
has to happen; this makes it test a point prediction instead of reporting
three unanchored numbers.

TWO INSTRUMENT PROPERTIES THAT MAKE IT SOUND:
  - netd control-plane calls go over a UNIX SOCKET, which does not traverse
    lo's qdisc. Only the QUIC data plane is delayed, so a slowed harness
    cannot be mistaken for a slowed mesh.
  - The RTT/delay ratio is MEASURED (N0), never assumed. On loopback the
    egress qdisc is traversed once per direction, so RTT should be 2x delay --
    but that is a claim about the apparatus, and this program's most frequent
    artifact is a curve plotted against a mis-stated x-axis.

WARNING: netem on `lo` slows ALL loopback traffic on this host for the
duration. Nothing else should be running against 127.0.0.1.

Usage:  sudo -v && python netem_sweep.py /tmp/arena1_netem [repeats]
"""
from __future__ import annotations
import json, os, re, secrets, statistics, subprocess, sys, time, uuid
from pathlib import Path

os.environ.setdefault("GYZA_EMBEDDER", "stub")
import numpy as np
sys.path.insert(0, "/home/xan/dev/gyza")

from gyza.network.netd_client import GossipClient, NetdClient
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.schema import EMBEDDING_DIM, WorkItem

BIN = "/home/xan/dev/gyza/netd/bin/gyza-netd"
PROJECT = "arena1-netem"

# APPARATUS: a veth pair across a network namespace, NOT loopback.
# netem on `lo` applies the delay correctly (ping confirms it to 3 decimals)
# and SILENTLY DESTROYS the QUIC data plane above ~2 ms RTT -- delivery works
# at 0 and 1 ms and is lost from 5 ms up, which no real mesh exhibits at 10 ms.
# MTU was tested and ruled out. veth behaves like a real NIC and carries QUIC
# intact under netem. See APPARATUS_NETEM_LO.md.
NS = "gz1"
VETH_H, VETH_N = "veth-h", "veth-n"
IP_H, IP_N = "10.99.0.1", "10.99.0.2"

DELAYS_MS = [0, 40, 100, 140, 250]      # -> RTT 0, 80, 200, 280, 500 if N0 holds
PROBE_SPACING_S = 0.100                  # C1: window resolution
TRAIN_S = 10.0                           # C2: 2x the top of the predicted range
SETTLE_S = 30.0                          # C4: >= 60x the largest RTT
N_PROBES = int(TRAIN_S / PROBE_SPACING_S)

EMB = np.zeros(EMBEDDING_DIM, dtype=np.float32); EMB[0] = 1.0


# ---------------------------------------------------------------- tc / netem
def _tc(*args: str) -> subprocess.CompletedProcess:
    """Only `tc` elevates. Running the whole harness as root would give
    root-owned daemons and different rlimits, either of which could
    contaminate the thing being measured."""
    if os.geteuid() == 0:
        cmd = list(args)
    elif os.environ.get("SUDO_ASKPASS"):
        cmd = ["sudo", "-A", *args]          # sudo's timestamp is TTY-bound
    else:
        cmd = ["sudo", "-n", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def tc_clear() -> None:
    _tc("tc", "qdisc", "del", "dev", VETH_H, "root")
    _tc("ip", "netns", "exec", NS, "tc", "qdisc", "del", "dev", VETH_N, "root")


def tc_apply(delay_ms: int) -> None:
    """Delay on BOTH ends: one traversal each way, so RTT = 2 x delay."""
    tc_clear()
    if delay_ms <= 0:
        return
    for cmd in (("tc", "qdisc", "add", "dev", VETH_H, "root",
                 "netem", "delay", f"{delay_ms}ms"),
                ("ip", "netns", "exec", NS, "tc", "qdisc", "add", "dev",
                 VETH_N, "root", "netem", "delay", f"{delay_ms}ms")):
        r = _tc(*cmd)
        if r.returncode != 0:
            raise RuntimeError(f"tc failed: {r.stderr.strip()}")


def veth_up() -> None:
    veth_down()
    for cmd in (("ip", "netns", "add", NS),
                ("ip", "link", "add", VETH_H, "type", "veth", "peer",
                 "name", VETH_N),
                ("ip", "link", "set", VETH_N, "netns", NS),
                ("ip", "addr", "add", f"{IP_H}/24", "dev", VETH_H),
                ("ip", "link", "set", VETH_H, "up"),
                ("ip", "-n", NS, "addr", "add", f"{IP_N}/24", "dev", VETH_N),
                ("ip", "-n", NS, "link", "set", VETH_N, "up"),
                ("ip", "-n", NS, "link", "set", "lo", "up")):
        r = _tc(*cmd)
        if r.returncode != 0:
            raise RuntimeError(f"veth setup failed at {cmd}: {r.stderr.strip()}")


def veth_down() -> None:
    _tc("ip", "netns", "del", NS)
    _tc("ip", "link", "del", VETH_H)


def ping_rtt_ms(n: int = 10) -> float:
    """Measured, never assumed -- this is the x-axis of every plot below."""
    r = subprocess.run(["ping", "-c", str(n), "-i", "0.2", "-q", IP_N],
                       capture_output=True, text=True)
    m = re.search(r"= [\d.]+/([\d.]+)/", r.stdout)
    if not m:
        raise RuntimeError(f"could not parse ping: {r.stdout}")
    return float(m.group(1))


def calibrate() -> tuple[float, dict]:
    """N0. Falsified outside [1.8, 2.2] or if the ratio is not constant.
    If N0 fails the sweep does not run -- that is the preregistered rule."""
    base = ping_rtt_ms()
    rows, ratios = [], []
    for d in (40, 100, 250):
        tc_apply(d)
        time.sleep(0.3)
        rtt = ping_rtt_ms()
        ratio = (rtt - base) / d
        rows.append({"delay_ms": d, "rtt_ms": rtt, "ratio": ratio})
        ratios.append(ratio)
        print(f"    delay {d:>3} ms -> RTT {rtt:7.2f} ms   ratio {ratio:.3f}")
    tc_clear()
    spread = max(ratios) - min(ratios)
    mean = statistics.fmean(ratios)
    ok = all(1.8 <= r <= 2.2 for r in ratios) and spread < 0.2
    return mean, {"baseline_rtt_ms": base, "rows": rows,
                  "mean_ratio": mean, "spread": spread, "N0_holds": ok}


# ---------------------------------------------------------------- daemons
def boot(base: Path, i: int, port: int, netns: str | None = None):
    d = base / f"n{i}"; d.mkdir(parents=True, exist_ok=True)
    k = d / "node.key"
    if not k.exists():
        k.write_bytes(secrets.token_bytes(32)); k.chmod(0o600)
    sock = str(d / "netd.sock")
    c = NetdClient(socket_path=sock)
    # start_daemon RETURNS the Popen. close() shuts only the gRPC channel and
    # leaves the process running -- discarding this handle leaked two daemons
    # per run, and the leaked pair stayed joined to the gossip topic and
    # polluted every subsequent measurement.
    if netns is None:
        proc = c.start_daemon(socket_path=sock, binary_path=BIN,
                              listen_port=port, key_path=str(k), mdns=False,
                              dht_mode="server", isolated=True)
    else:
        # `ip netns exec` needs root, but a root-owned socket is unreachable
        # by the non-root client -- so enter the namespace as root and drop
        # straight back to the invoking user.
        argv = ["sudo", "-A", "ip", "netns", "exec", netns,
                "sudo", "-u", os.environ.get("USER", "xan"), BIN,
                "--socket-path", sock, "--listen-port", str(port),
                "--key-path", str(k), "--log-level", "info",
                "--bootstrap-domain=", "--no-fallback-peers",
                "--mdns=false", "--dht-mode", "server"]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        try:
            return c, sock, c.get_node_info(), d, proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"node {i} never came up")


def mk_item(desc: str) -> WorkItem:
    return WorkItem(
        id=str(uuid.uuid7()), lineage_root=PROJECT, parent_id=None,
        description=desc, desc_embedding=EMB, reward=0.1,
        reward_updated_ns=time.time_ns(), required_tier=3, input_hashes=[],
        output_spec={"kind": "probe"}, streaming_ok=False, claimed_by=None,
        claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9)


def wait_cut(ca, cb, timeout=15.0) -> bool:
    """Truth predicate is the PEER COUNT reaching 0 on BOTH sides."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if len(ca.list_peers()) == 0 and len(cb.list_peers()) == 0:
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- one run
def one_run(base: Path, delay_ms: int, port: int) -> dict:
    ca = cb = None
    procs: list = []
    try:
        ca, sa, ia, da, pa = boot(base, 1, port)
        cb, sb, ib, db, pb = boot(base, 2, port + 1, netns=NS)
        procs = [pa, pb]
        bbA = NetworkBlackboard(str(da / "bb.db"))
        bbB = NetworkBlackboard(str(db / "bb.db"))
        ga, gb = GossipClient(sa), GossipClient(sb)
        wan = next(m for m in ib.listen_addrs if f"/ip4/{IP_N}/" in m)
        addr = wan if "/p2p/" in wan else f"{wan}/p2p/{ib.peer_id}"
        if not ca.connect_peer(addr).success:
            return {"error": "initial connect failed"}
        ga.join_project(PROJECT); gb.join_project(PROJECT)
        bbA.attach_gossip(ga, PROJECT, node_id=ia.compositor_pubkey)
        bbB.attach_gossip(gb, PROJECT, node_id=ib.compositor_pubkey)
        intent = {"intent_id": PROJECT, "natural_text": "p",
                  "category": "system_task", "actions": [],
                  "authorization": {"resources": [], "preview_required": False,
                                    "reversible": True}}
        bbA.post_intent(intent)
        # Waits must scale with RTT or the apparatus, not the system, decides
        # the outcome. QUIC handshake ~2 RTT, then GRAFT rounds on a 1 s
        # heartbeat. Rule #4: compute the ceiling for BOTH sides.
        rtt_s = 2.0 * delay_ms / 1000.0
        mesh_wait = 8.0 + 30.0 * rtt_s
        steady_timeout = 20.0 + 80.0 * rtt_s
        time.sleep(mesh_wait)

        # -- steady-state control: delivery MUST work before we cut, or the
        #    window measurement below is measuring a broken mesh.
        # RETRY. Gossip does not resend, so a single probe published into an
        # unformed mesh is lost forever and reads as "the mesh never formed".
        # HEAL_WINDOW.md records exactly this error producing a false
        # "TIMEOUT in 5/5 trials"; CLAUDE.md puts re-meshing at 10-15 s on
        # loopback, which is longer than any fixed pre-wait worth using.
        t0 = time.monotonic(); steady = None
        while time.monotonic() - t0 < steady_timeout and steady is None:
            # RE-POST THE INTENT TOO. work_items has a foreign key to the
            # intent row; an intent published into a mesh that has not
            # finished GRAFTing is lost forever, and every later work item
            # then fails its FK on the receiving board -- silently, because
            # the delta DOES arrive and is rejected at insert. This is the
            # HEAL_WINDOW.md trap applied to the intent rather than the probe.
            bbA.post_intent(intent)
            probe = mk_item("steady")
            bbA.post_work_item(probe)
            t1 = time.monotonic()
            while time.monotonic() - t1 < 2.0:
                if any(x.id == probe.id for x in bbB.get_by_lineage(PROJECT)):
                    steady = time.monotonic() - t0; break
                time.sleep(0.02)
        if steady is None:
            return {"error": "steady-state delivery failed; mesh never formed",
                    "mesh_wait_s": mesh_wait, "steady_timeout_s": steady_timeout}

        # -- cut
        ca.disconnect_peer(ib.peer_id)
        if not wait_cut(ca, cb):
            return {"error": "cut is cosmetic (peers != 0 both sides)"}

        # -- heal, then a DENSE probe train at known offsets
        heal = time.monotonic()
        ca.connect_peer(addr)
        train = []
        for i in range(N_PROBES):
            target = heal + i * PROBE_SPACING_S
            sleep = target - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            w = mk_item(f"probe-{i}")
            off = time.monotonic() - heal
            bbA.post_work_item(w)
            train.append({"i": i, "offset_s": off, "id": w.id})

        time.sleep(SETTLE_S)
        seen = {x.id for x in bbB.get_by_lineage(PROJECT)}
        for p in train:
            p["arrived"] = p["id"] in seen

        arrived = [p["arrived"] for p in train]
        first_ok = next((p["offset_s"] for p in train if p["arrived"]), None)
        last_lost = next((p["offset_s"] for p in reversed(train)
                          if not p["arrived"]), None)
        # N3: monotone means no True strictly before a False.
        inversions = 0
        seen_true = False
        for a in arrived:
            if a:
                seen_true = True
            elif seen_true:
                inversions += 1
        return {
            "delay_ms": delay_ms,
            "mesh_wait_s": mesh_wait,
            "steady_delivery_s": steady,
            "n_probes": len(train),
            "n_arrived": sum(arrived),
            "n_lost": len(arrived) - sum(arrived),
            "first_arrived_offset_s": first_ok,
            "last_lost_offset_s": last_lost,
            "boundary_s": first_ok,
            "inversions": inversions,
            "monotone": inversions == 0,
            "no_boundary": first_ok is None,
            "train": train,
        }
    finally:
        for c in (ca, cb):
            if c is not None:
                try: c.close()
                except Exception: pass
        for pr in procs:                     # the channel is not the process
            try:
                pr.terminate(); pr.wait(timeout=10)
            except Exception:
                try: pr.kill()
                except Exception: pass


# ---------------------------------------------------------------- main
def main() -> int:
    base = Path(sys.argv[1]); base.mkdir(parents=True, exist_ok=True)
    repeats = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    delays = ([int(x) for x in sys.argv[3].split(",")]
              if len(sys.argv) > 3 else DELAYS_MS)

    # Probe the WRITE we actually need, not the read that always works:
    # `tc qdisc show` succeeds unprivileged, so gating on it would pass here
    # and fail at the first tc_apply with the qdisc half-configured.
    probe = _tc("ip", "netns", "list")
    if probe.returncode != 0:
        print("ERROR: cannot manage network namespaces (need root via sudo).")
        print(f"       {probe.stderr.strip()}")
        print("       Run `sudo -v` in this shell first, then re-run.")
        return 2
    tc_clear()

    out = {
        "delays_run": delays,
        "prereg_sha256":
            "1b667ed63785b3aa86cba64297505d47b228e1c0b4a45947be1af8e1ed13fe8d",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "delays_ms": DELAYS_MS, "probe_spacing_s": PROBE_SPACING_S,
        "train_s": TRAIN_S, "settle_s": SETTLE_S, "runs": []}
    try:
        veth_up()
        print(f"== apparatus: veth pair {IP_H} <-> {IP_N} (netns {NS}) ==")
        print("== N0 calibration: is RTT = 2 x delay? ==")
        ratio, cal = calibrate()
        out["calibration"] = cal
        print(f"  mean ratio {ratio:.3f}  spread {cal['spread']:.3f}  "
              f"-> N0 {'HOLDS' if cal['N0_holds'] else 'FALSIFIED'}")
        if not cal["N0_holds"]:
            print("\n  N0 FALSIFIED. Per the preregistration the sweep does NOT"
                  " run.\n  Recorded as an apparatus finding.")
            out["aborted"] = "N0 falsified"
            return 1

        port = 7900
        for d in delays:
            rtt = d * ratio
            print(f"\n== delay {d} ms  (RTT ~{rtt:.0f} ms) ==")
            tc_apply(d)
            for r in range(repeats):
                res = one_run(base / f"d{d}_r{r}", d, port)
                port += 2
                res["repeat"] = r
                res["rtt_ms"] = rtt
                out["runs"].append(res)
                if "error" in res:
                    print(f"  run {r}: ERROR {res['error']}")
                elif res["no_boundary"]:
                    print(f"  run {r}: NO BOUNDARY inside {TRAIN_S}s "
                          f"({res['n_lost']}/{res['n_probes']} lost)")
                else:
                    tag = ("monotone" if res["monotone"]
                           else f"INVERSIONS={res['inversions']}")
                    print(f"  run {r}: boundary {res['boundary_s']:.2f}s  "
                          f"lost {res['n_lost']}/{res['n_probes']}  "
                          f"steady {res['steady_delivery_s']*1000:.0f}ms  {tag}")
            tc_clear()
    finally:
        tc_clear()
        veth_down()

    p = base / "netem_sweep_results.json"
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {p}")

    # ---- verdicts against the preregistered predictions -------------
    print("\n== PREREGISTERED VERDICTS ==")
    ok = [r for r in out["runs"] if "error" not in r and not r["no_boundary"]]
    by_d: dict[int, list] = {}
    for r in ok:
        by_d.setdefault(r["delay_ms"], []).append(r["boundary_s"])
    for d in sorted(by_d):
        v = by_d[d]
        print(f"  delay {d:>3} ms (RTT {d*ratio:>5.0f}): boundary median "
              f"{statistics.median(v):.2f}s  n={len(v)}  "
              f"range {min(v):.2f}-{max(v):.2f}")
    if 0 in by_d and max(by_d) != 0:
        top = max(by_d)
        lo_, hi_ = statistics.median(by_d[0]), statistics.median(by_d[top])
        print(f"\n  N1  TTR(500ms) - TTR(0) = {hi_-lo_:+.2f}s  "
              f"-> {'HOLDS' if hi_-lo_ < 2.0 else 'FALSIFIED'} (bar: < 2.0s)")
        print(f"  N5  width(top)/width(0) = {hi_/lo_ if lo_ else float('nan'):.2f}x "
              f"-> {'HOLDS' if lo_ and hi_ < 3*lo_ else 'FALSIFIED'} (bar: < 3x)")
    zero_arrived = [r for r in ok if r["train"] and r["train"][0]["arrived"]]
    print(f"  N2  offset-0 probe arrived in {len(zero_arrived)}/{len(ok)} runs "
          f"-> {'HOLDS' if not zero_arrived else 'FALSIFIED'} (bar: 0)")
    nonmono = [r for r in ok if not r["monotone"]]
    print(f"  N3  non-monotone runs: {len(nonmono)}/{len(ok)} "
          f"-> {'HOLDS' if not nonmono else 'CHECK'} "
          f"(single adjacent inversions are allowed)")
    if nonmono:
        print(f"      inversion counts: {[r['inversions'] for r in nonmono]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
