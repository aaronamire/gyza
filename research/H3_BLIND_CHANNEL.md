# H3 has a blind channel, and the sandbox already documented it

`research/H3_MESH_EXIT.md` §7 declared a gap: `OUTSIDE_PROTOCOL` had a recorder
and no production caller, with sandbox egress named as "the largest real hole."
Closing it turned the gap into a **limit**, and the limit is worth more than the
instrumentation.

---

## 1. The finding

`SandboxConfig`'s own enforcement-honesty note (`gyza/sandbox/config.py:231-238`)
has said this since it was written:

> *"network: PARTIAL. bwrap's network control is **all-or-nothing** (a fresh net
> namespace with loopback only, or full host networking). It **CANNOT** enforce
> a per-host allowlist. So a manifest that lists `network.allowed_hosts` only
> gets the namespace toggled on; the specific host allowlist is **DECLARED, not
> enforced**."*

Every clause is true, was already written down, and nobody connected it to H3.
Connected, it says:

> **Once `--share-net` is passed, the sandboxee may send anywhere, any number of
> times, in a subprocess this process cannot observe. H3's send count is
> structurally BLIND to all of it.**

That is a blind channel in R12's sense — an unmodelled path that moves the very
quantity a guard reads. R12 concluded that finding blind channels by static
analysis is **UNSOUND** (recall 0.5). This one was not found by analysis. It was
found by reading a docstring that had disclosed it all along, which is the
`AN UNENFORCED INVARIANT IS AN ASSUMPTION` species one step further along: not a
promise without a mechanism, but a **disclosed limitation with nothing connecting
it to the measure that depends on it.**

## 2. What was built, and the unit that made it honest

The recordable quantity is the **grant**, not the send. A new class
`UNBOUNDED_GRANT` is recorded at the one place it is visible —
`run_sandboxed`, when `requires_network` causes `--share-net`.

**It is deliberately excluded from `EgressClass.MESH_EXIT`.** Folding a grant
into a send count would report **1** for a capability permitting arbitrarily
many sends. Two different units summed into one number, failing in the
reassuring direction — the species already recorded at artifact #17 and in both
of this program's failed closed forms. Grants are read through a separate
accessor, `Blackboard.count_grants_since`, so no caller can add them to H3.

`byte_count` is stored as **SQL NULL**, not 0. Zero would claim nothing left the
machine; NULL says *unknown*, which is what is actually true of a shared network
namespace. This is `AN ERROR IS NOT A VALUE` applied to a measurement gap rather
than to an exception.

## 3. What this means for any future H3 bound

**A declared H3 level would not cover the largest real egress surface.** It would
bound the countable channel (protocol sends) while the uncountable one
(`--share-net`) stays open beside it. Declaring a level without saying so would
produce exactly the reassuring arithmetic this program keeps catching.

So the bound, when declared, must be stated as **two quantities**:

1. `H3_mesh_exit_sends` — countable protocol sends, boundable.
2. `unbounded_egress_grants` — capability grants whose consequence is
   **unmeasurable by construction**, and for which the only honest bound is
   *how many are issued at all*, never how much left through them.

`SandboxConfig` already names the two ways to close it — *"a filtering proxy or a
TEE-attested runtime"* — and both are outside the current architecture. Until one
exists, **granting network to a sandboxed agent is an unbounded action**, and the
containment claim must say so rather than imply the send count covers it.

## 4. What did NOT change

`artifact_client.py`'s `httpx` fetch is **not** `OUTSIDE_PROTOCOL`: its
destinations are Gyza peer URLs, so it classifies as a peer send
(attested/unattested by the same rule as everything else). It is still
uninstrumented, and is recorded here as a known remaining caller rather than
silently closed.

So `OUTSIDE_PROTOCOL` **still has no production caller** — and that is now a
finding rather than an omission: Gyza has no production path that makes a
*countable* send outside the protocol. Its only real outside-protocol egress is
the sandbox, and that one is uncountable.
