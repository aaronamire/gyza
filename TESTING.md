# Trying Gyza — a tester's guide

Thanks for testing this. Gyza gives an AI agent — or any command — a
**seatbelt and a flight recorder**: it runs inside a real sandbox that
can only touch what you allow, and it produces a **signed receipt** of
exactly what it did and that it stayed inside those limits. Anyone can
check that receipt later, with no trust in you and no account.

There are two parts. **Part 1 (5 minutes, one machine)** is the core and
the one I most want feedback on. **Part 2** shows the same thing across
two machines and is optional / more involved.

Please note what's confusing, what breaks, and whether the idea lands.
Honest "I didn't get it" is the most useful thing you can tell me.

---

## Before you start

- **Linux**, x86_64 or aarch64. (Not macOS/Windows yet — sorry.)
- **Python 3.10+**.
- **bubblewrap** — the sandbox. Install it:
  - Debian/Ubuntu: `sudo apt install bubblewrap`
  - Fedora: `sudo dnf install bubblewrap`
  - Arch: `sudo pacman -S bubblewrap`
- Gyza isn't on PyPI yet, so you'll install the wheel I send you (or
  from a source checkout). It is **not** `pip install gyza`.

---

## Part 1 — the seatbelt (one machine, ~5 minutes)

### 1. Install

Using the wheel I sent you (recommended):

```bash
python3 -m venv gyza-env
./gyza-env/bin/pip install gyza-0.1.1-py3-none-any.whl
# put it on your PATH for this shell:
source gyza-env/bin/activate
```

Or from a source checkout:

```bash
git clone <repo-url> gyza && cd gyza
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Check it:

```bash
gyza --help
```

### 2. Set up your identity

```bash
gyza init
```

This makes `~/.gyza/` and a signing key. One line of output ending in
`ready.` — that's it.

### 3. Run one of YOUR commands, sandboxed and recorded

```bash
gyza exec --allow-read . -- ls -la
```

**What you're looking at:** that `ls` ran inside a sandbox that could
see *only* the current directory (because you granted `--allow-read .`)
— not your home, not your SSH keys, nothing else. Gyza signed the
result and printed an `intent:` id and `audit: VALID`. Try a command
that reads something you did *not* grant (e.g. `gyza exec -- cat
~/.ssh/id_rsa`) and watch it be unable to.

### 4. Turn the run into a receipt anyone can check

Use the `intent:` id from the last step:

```bash
gyza bundle <intent-id> -o receipt.json
gyza verify receipt.json
```

**What you're looking at:** `receipt.json` is a self-contained file. `gyza
verify` re-checks it from scratch — signatures, that the recorded output
matches, that the run stayed in bounds — and prints `VERDICT: VALID`.
The important part: **`verify` needs no key, no account, and no trust in
whoever made the receipt.** Send `receipt.json` to someone else with
Gyza installed and they get the same verdict. That's the whole point —
provable, portable accountability.

### 5. (Optional) see the guarantees stress-tested

```bash
gyza demo bounds
```

Runs a sandboxed task, then an adversary tries to forge the record
(caught), then tries to run wider than allowed (refused). ~2 seconds, no
network.

**What I'd love to know after Part 1:** Did it install cleanly? Did the
receipt idea make sense? Would you actually use this for the agents you
run?

---

## Part 2 — the network loop (two machines, optional)

This shows the real aim: you delegate a bounded task to *someone else's*
machine, and your machine **audits their work before "paying" for it**.
It needs the Go network daemon, which isn't in the pip package.

**Extra prerequisites:** the `gyza-netd` binary on PATH (I can send you
one, or build it from source with `make -C netd build`, which needs Go
1.22+), and two machines that can reach each other (same Wi-Fi is
easiest).

On the **host** machine:

```bash
gyza demo loop-host
```

It prints one or more addresses. Copy the one on your local network
(usually a `192.168.x.x` address).

On the **other** machine:

```bash
gyza demo loop-join /ip4/192.168.x.x/udp/<port>/quic-v1/p2p/<peer-id>
```

**What you're looking at:** the host delegates a task with a memory
limit; the joiner runs it in a real sandbox and sends back the result
plus proof; the host independently audits that proof and only then
settles a credit. The host prints its own audit (`VERDICT: VALID`,
"contained") and the balance; the joiner shows the work it ran. Neither
side trusts the other — the payment is the output of a check.

To see the whole thing on one machine first: `gyza demo loop`.

---

## What this does and doesn't promise (so I'm not overselling)

- It proves **who did what and that it stayed in the bounds you granted**
  — accountability and containment.
- It does **not** judge whether the output is *correct*. That's still a
  human call.
- Today's honest limit: if someone runs a *modified* Gyza on a machine
  they fully control, they could lie in the record. The signature makes
  them **undeniably on the hook** for that lie (like a signed invoice),
  but hardware-backed proof against a malicious host is future work.
- The public network isn't live yet — Part 2 connects your machines
  directly, not through a shared network.

## Reporting back

Anything at all, but especially: install friction, confusing output, the
moment (if any) where it "clicked" or didn't, and whether you'd reach for
this on your own. Thank you.
