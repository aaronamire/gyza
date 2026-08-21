"""What H3 rate level does a benign node actually need?

Not a preregistered route -- an ENGINEERING measurement to turn "pick a number"
into "pick from this range". It reuses R-EVID Part B's measured per-action byte
figures (research/evidence/evidence.json) and combines them with the measured
sandbox throughput ceiling.

THE FIGURES IT COMBINES ARE FROM DIFFERENT MEASUREMENTS, and artifact #17 was
bought by plotting a curve through two numbers that did not measure the same
thing. So each input is named with its source and its population, and the
output is explicitly a CONSTRUCTION rather than an observation of any node that
has actually run for an hour.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

#: Measured by research/scale/FINDINGS_COORDINATION_CEILING.md: bubblewrap costs
#: 305 ms per action, so one core sustains 3.3 actions/s. This is the CEILING --
#: a node cannot exceed it, so a level set from it cannot be too tight.
SANDBOX_ACTIONS_PER_SEC = 1.0 / 0.305


def main() -> int:
    ev = json.loads((HERE / "evidence.json").read_text())
    by_id = {c["class"]: c for c in ev["classes"]}
    benign_bpa = by_id["H3_mesh_exit_bytes"]["benign_rate"]
    adv_bpa = by_id["H3_mesh_exit_bytes"]["adversary_rate"]

    saturated_actions_per_hour = SANDBOX_ACTIONS_PER_SEC * 3600
    benign_bph = benign_bpa * saturated_actions_per_hour

    print(f"benign bytes/action      : {benign_bpa:,.0f}   "
          f"(R-EVID Part B, production _executor)")
    print(f"adversary bytes/action   : {adv_bpa:,.0f}   (100-artifact exfil)")
    print(f"actions/hour, saturated  : {saturated_actions_per_hour:,.0f}   "
          f"(305 ms/action sandbox ceiling, 1 core)")
    print(f"benign bytes/hour, SATURATED: {benign_bph/1e6:,.1f} MB\n")

    print("A level L MB/hour. 'headroom' is how far above a FULLY SATURATED")
    print("benign node it sits; 'catches' is the per-action disclosure above")
    print("which a same-speed adversary trips it.\n")
    print(f"  {'L (MB/h)':>9} {'headroom':>9} {'catches above':>16} "
          f"{'= x benign':>11}")
    for mb in (16, 25, 50, 100, 250, 500, 1000):
        L = mb * 1e6
        headroom = L / benign_bph
        catches_bpa = L / saturated_actions_per_hour
        print(f"  {mb:>9,} {headroom:>8.1f}x {catches_bpa:>14,.0f} B "
              f"{catches_bpa/benign_bpa:>10.1f}x")

    print("\nNOTES, because these numbers are a construction:")
    print("  * SATURATED is the worst case for a benign node -- one core doing")
    print("    nothing but sandboxed work for a full hour. Real nodes idle, so")
    print("    a level chosen here is loose in practice, which is the safe")
    print("    direction for LIVENESS and the unsafe one for CONTAINMENT.")
    print("  * Byte figures are LOWER BOUNDS: the stub does not model SDK")
    print("    framing, headers or system prompt.")
    print("  * attested_peers has no production source, so every peer send")
    print("    counts as exit. Real exit is LOWER than this, so a level set")
    print("    here errs loose again.")
    print("  * Multi-core nodes scale the saturated figure linearly; the level")
    print("    is PER NODE, so a 4-core node needs 4x or it throttles itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
