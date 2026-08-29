# A bundle commits to what it contains, not to what it omits

**Found 2026-08-23** while building a reviewer-verifiable evidence bundle. It
is a limit on `gyza verify`'s central claim and it is stated here rather than
discovered by someone else.

## The measurement

Four actions, produced by two sandboxed agents running a real
`/usr/bin/uname -a` under bubblewrap, exported with `create_bundle` and checked
with `gyza verify` from a shell with a fake `HOME`, no config, no keys, no
daemon. Baseline: **VERDICT: VALID**, 4 actions.

Then each single-envelope deletion, verified independently:

| dropped | role in the DAG | verdict |
|---|---|---|
| envelope 0 | referenced as a parent | **INVALID** |
| envelope 1 | referenced as a parent | **INVALID** |
| envelope 2 | **leaf** | **VALID** — 3 actions |
| envelope 3 | **leaf** | **VALID** — 3 actions |

Two content tamperings were also run as controls and both were caught: editing
an artifact's bytes (`[coord] FAIL`) and widening a manifest's memory limit
after the fact (`[exec ] FAIL`).

## The property

**Tampering is caught. Omission is not.** A child's `parent_envelope_hash` is
what makes a deletion visible, so deleting a *referenced* envelope breaks the
chain and is detected. **Nothing references a leaf.** A producer can therefore
remove any leaf action — including every unfavourable one — and the result
verifies as VALID with a smaller action count that the reviewer has no
independent expectation for.

This is not a bug in `verify_bundle`, which does exactly what it says: it fails
closed on anything *missing that something else points at*. The gap is that the
format carries **no commitment to the complete action set**. `create_bundle`'s
own docstring says collection is "permissive — whatever evidence resolves is
included"; that is the right behaviour for exporting a broken workflow, and it
is also what makes selective export invisible.

## What the claim must therefore say

`gyza verify` establishes, without trusting the producer, that **every action
present** is signed, attributable, within its granted bounds, and correctly
chained to its parents. It does **not** establish that the bundle is a complete
record of the workflow. The honest sentence is:

> Nothing in this bundle has been altered. Whether something has been left out
> is not a question this bundle can answer.

## Why no cheap fix works

- **Count the work items** — a lying producer edits the count too.
- **Have the intent declare its actions** — intents are not signed by the agent.
- **`require_closed=True`** — closure means every parent reference resolves,
  which is true of a leaf-pruned bundle.

The real remedy is a **signed closure record**: the producing agent signs a
statement committing to the set of leaves at export time, so a missing leaf
becomes a broken signature rather than a smaller number. That changes the signed
payload and therefore the Rust parity fixtures, so it is a design change, not an
afternoon's work.

**It is the right shape for a Phase 1 task**, and it is a genuine open problem in
provenance rather than an oversight: every append-only provenance structure that
does not commit to its frontier has this property.
