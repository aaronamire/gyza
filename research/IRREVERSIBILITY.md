# C-2 — an irreversibility measure, and what it can honestly claim

**Built 2026-08-24.** Until today `gyza_model.UNMODELLED` said plainly that *"no
function in `gyza/` computes an irreversibility measure"*, so the guard could
not distinguish computing a sum from issuing a command that cannot be taken
back. Both were one signed envelope, and every bound the system did enforce —
authority, storage, egress rate — was a **proxy** for the thing anyone actually
cares about.

## The measurand is the signed enforcement record

An action's reversibility is not a property of its intent, its prompt or its
output text. Those are the agent's own words about itself and no verifier can
check them. It is a property of **what the action was permitted to touch**,
which the sandbox stamps and the envelope's `output_hash` commits to.

| verdict | condition | counted |
|---|---|---|
| `REVERSIBLE` | no network, no writes outside an append-only store | no |
| `DESTRUCTIVE` | a writable path outside any append-only store | yes |
| `IRREVERSIBLE` | the sandbox granted the network | yes |
| `UNPROVEN` | no enforcement record at all | **yes** |

`UNPROVEN` counts with the irreversible and never with the reversible: *"I did
not say"* must not read as *"nothing left the system"*, which is the rule the
signing gate already applies to an absent record.

Three consequences follow from choosing this measurand, and they are the reason
for it: the quantity is computed from state and never from guard state
(discipline #5); a **third party can recompute it from a bundle alone**, because
the record is already in the signed bytes; and it cannot be argued with, because
nothing is being asked, only looked up.

## The result: soundness is a property of the GRANT, not of the agent

R-EVID Part C decides whether a level on an accumulating quantity is a **bound**
or a **timer** by the sign of the benign drift. For irreversibility that sign is
fixed by the grant, which is exactly what makes it checkable:

- **No network, no writes outside an append-only store → `b = 0` exactly.**
  A compliant agent *cannot* increment the quantity however it behaves, so no
  level can false-alarm and a bound of **0 is a real bound**. Sound-by-silence,
  and the condition is definitional rather than measured.
- **Any other grant → `b > 0`, one per action.** Every action consumes budget,
  so by `THEOREMS_C.md` any cumulative level over it is a **timer** that refuses
  the agent at `⌈L/b⌉` whatever it did.

> **Containment over irreversible effect is claimable exactly for agents that
> were never given the means.**

That is a narrower claim than "we bound irreversible harm", and it is the one
the architecture can support. `benign_rate_is_zero` is the predicate that says
which case a given deployment is in.

## What this does NOT measure, stated so nobody infers more

It does not measure **how bad** an irreversible action was, and it never will:
severity is a judgement about consequences in the world, and this program
measured that class of judgement as not cheaply verifiable.

It measures whether an action **could** have left modelled state. An agent
granted the network that sends nothing counts the same as one that exfiltrates,
because `bwrap`'s network control is all-or-nothing and the substrate cannot
tell them apart (`research/H3_BLIND_CHANNEL.md`). **The measure is an upper
bound on irreversible effect, and an upper bound is the only side of this a
verifier can be sound about.**

## Registering it flipped `can_claim_containment` to FALSE, and that is correct

H7 is registered with **no bound**, because bound levels are a user decision
that must be loaded and never invented (BUILD_PLAN D1). `readiness()` therefore
reports:

```
unbounded                  ['H7_irreversible_actions']
can_claim_containment      False
```

**This cannot be fixed from this machine, and that is the point.** Installing a
bound needs a signed guard configuration, and the authority key was moved
off-host precisely so that the constrained system cannot rewrite the policy it
is constrained by. The induction has a base case again only when the owner signs
v4.

`gyza/containment/guard_bounds.v4.draft.json` carries the proposed configuration
— v3's bounds plus `H7_irreversible_actions: 0.0` — **unsigned**. Signing it is
one command with the key present:

```
python scripts/sign_guard_config.py gyza/containment/guard_bounds.v4.draft.json
```

**0 is the recommended level and the reasoning is above:** it is the only level
that is a bound rather than a timer, and it is satisfiable by exactly the agents
that were never granted the means. A deployment that grants its agents the
network cannot hold H7 at 0, and should read that as the measure doing its job
rather than as a level to raise.
