"""
Build the attractor battery (Phase B2). N=80 perturbed items; each has a
machine-computed / hand-verified TRUE answer and an explicitly-defined
ATTRACTOR (the memorized/salient answer that is now WRONG).

Two control modes — the rigorous reading of B3, whose control must show the item
is a valid fixture (not a test of ignorance):
  - MEMORIZED (i_classic conceptual, iii_substitution): the attractor IS the
    correct answer to the famous ORIGINAL, so the B3 control (original_prompt)
    must elicit the ATTRACTOR; the perturbation moves the true answer away.
  - COMPETENCE (ii_noop, and the misreading traps): an added
    irrelevant/misdirecting clause leaves the true answer unchanged; the
    attractor is a wrong incorporation of the extra number. The B3 control is the
    clause-free BASE and must elicit the TRUE answer (models can solve it), so a
    perturbed failure is attractor-induced, not incompetence.

Every arithmetic true/attractor is computed here; conceptual items are
hand-verified (reasoning in `note`). Deterministic (seed 1). Writes items.json.
Only items with certain ground truth are included.
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
SEED = 1
items: list[dict] = []


def _f(x) -> str:
    if isinstance(x, Fraction):
        return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"
    return str(x)


def add(cat, mode, perturbed, true, attractor, original, note=""):
    assert _f(true) != _f(attractor), f"true==attractor @ {perturbed[:70]}"
    items.append({"item_id": f"{cat}_{sum(1 for i in items if i['category']==cat):02d}",
                  "category": cat, "control_mode": mode,
                  "perturbed_prompt": perturbed.strip(), "true_answer": _f(true),
                  "attractor_answer": _f(attractor), "original_prompt": original.strip(),
                  "note": note})


ASK = " Give the final answer as \\boxed{...} (a single number or reduced fraction)."

# ===========================================================================
# (i) CLASSIC-PUZZLE PERTURBATIONS
# ===========================================================================
add("i_classic", "memorized",
    "You are on a game show with 3 doors; one hides a car, two hide goats. You pick "
    "door 1. The host, who does NOT know where the car is, opens one of the other two "
    "doors CHOSEN UNIFORMLY AT RANDOM, and it happens to reveal a goat. You may switch "
    "to the remaining unopened door. Given that a goat was revealed, what is the "
    "probability you win the car if you SWITCH?" + ASK,
    Fraction(1, 2), Fraction(2, 3),
    "You are on a game show with 3 doors; one hides a car, two hide goats. You pick "
    "door 1. The host, who KNOWS where the car is, deliberately opens another door "
    "revealing a goat and offers you the chance to switch. What is the probability you "
    "win the car if you SWITCH?" + ASK,
    "Random-host Monty Hall: conditioning on a randomly-revealed goat gives 1/2, not 2/3.")

add("i_classic", "memorized",
    "A family has two children. You are told that the OLDER child is a boy. What is the "
    "probability that BOTH children are boys?" + ASK,
    Fraction(1, 2), Fraction(1, 3),
    "A family has two children. You are told that AT LEAST ONE of them is a boy. What is "
    "the probability that BOTH children are boys?" + ASK,
    "Fixing the older child removes the ambiguity: 1/2, not the famous 1/3.")

add("i_classic", "memorized",
    "A family has two children. At least one is a boy born on a Tuesday. What is the "
    "probability both are boys? Assume births are independent and uniform over 7 days "
    "and 2 sexes." + ASK,
    Fraction(13, 27), Fraction(1, 3),
    "A family has two children. At least one is a boy. What is the probability that both "
    "are boys?" + ASK,
    "Tuesday-boy problem: 13/27, famously not 1/3.")

add("i_classic", "memorized",
    "Ignoring leap years (365 equally likely birthdays), how many people must be in a "
    "room so that it is more likely than not that at least one shares YOUR specific "
    "birthday?" + ASK,
    253, 23,
    "Ignoring leap years (365 equally likely birthdays), how many people must be in a "
    "room so that it is more likely than not that some two of them share a birthday?" + ASK,
    "Matching a SPECIFIC date needs 253 (1-(364/365)^n>1/2), not the famous 23.")

add("i_classic", "competence",
    "A doctor gives you 5 pills and tells you to take one every 30 minutes, starting "
    "now. How many minutes until you have taken all 5 pills?" + ASK,
    120, 150,
    "You take 1 pill now, then one more every 30 minutes. After how many minutes have "
    "you taken 5 pills in total?" + ASK,
    "4 intervals of 30 = 120; the attractor 5*30=150 counts one interval too many.")

# all-but-N misreading (competence): base is the plain-arithmetic version.
for (S, surv) in [(17, 8), (23, 6), (30, 7), (11, 4), (40, 9), (25, 3), (14, 5), (33, 8)]:
    assert S != 2 * surv
    add("i_classic", "competence",
        f"A farmer has {S} sheep. All but {surv} of them die. How many sheep are still "
        f"alive?" + ASK,
        surv, S - surv,
        f"A farmer has {S} sheep. {S - surv} of them die. How many sheep are still "
        f"alive?" + ASK,
        "'All but N die' => N survive; the attractor S-N misreads it as 'N die'.")

# fence-post (competence): base counts segments, perturbed asks posts (off-by-one).
for (L, s) in [(20, 2), (30, 3), (100, 5), (48, 4), (36, 6), (60, 10), (21, 3)]:
    true = L // s + 1
    add("i_classic", "competence",
        f"A straight fence is {L} metres long, with a post every {s} metres, including "
        f"one at each end. How many posts are there in total?" + ASK,
        true, L // s,
        f"A straight {L}-metre path is divided into equal sections {s} metres long. How "
        f"many sections are there?" + ASK,
        "Posts = segments + 1 (fence-post error); attractor drops the final post.")

# ===========================================================================
# (iii) NUMERIC SUBSTITUTION into famous problems (memorized answer now wrong).
# ===========================================================================
for (a, b) in [(1, 99), (2, 100), (1, 101), (1, 50), (1, 200), (3, 100), (1, 49)]:
    true = sum(range(a, b + 1))
    assert true != 5050
    add("iii_substitution", "memorized",
        f"What is the sum of all the integers from {a} to {b}, inclusive?" + ASK,
        true, 5050,
        "What is the sum of all the integers from 1 to 100, inclusive?" + ASK,
        "Famous 1..100=5050; a shifted range breaks the memorized total.")

POLY = {5: "pentagon", 6: "hexagon", 7: "heptagon", 8: "octagon", 9: "nonagon",
        10: "decagon", 12: "dodecagon"}
for n, name in POLY.items():
    add("iii_substitution", "memorized",
        f"What is the sum, in degrees, of the interior angles of a {name} (a {n}-sided "
        f"polygon)?" + ASK,
        (n - 2) * 180, 180,
        "What is the sum, in degrees, of the interior angles of a triangle?" + ASK,
        "(n-2)*180; the attractor 180 is the memorized triangle answer.")

for n in [4, 6, 7, 9, 11, 15]:
    add("iii_substitution", "memorized",
        f"What is the sum of the first {n} positive EVEN numbers "
        f"(2 + 4 + ... )?" + ASK,
        n * (n + 1), n * n,
        f"What is the sum of the first {n} positive ODD numbers (1 + 3 + ... )?" + ASK,
        "Sum of first n even = n(n+1); the attractor n^2 is the memorized odd-sum.")

# ===========================================================================
# (ii) NoOp — irrelevant-clause insertion. true unchanged; attractor incorporates
#      the irrelevant number. control_mode = COMPETENCE (clause-free base).
# ===========================================================================
NOOP1 = [
    ("A basket holds {S} apples.", "{sold} of the apples are eaten",
     "{k} of the remaining apples are slightly smaller than average", "How many apples remain in the basket?"),
    ("A shelf holds {S} books.", "{sold} of the books are borrowed",
     "{k} of the remaining books have slightly torn covers", "How many books are still on the shelf?"),
    ("A garden has {S} rose bushes.", "{sold} of the bushes are dug up and removed",
     "{k} of the remaining bushes bloom slightly later than the others", "How many rose bushes are still in the garden?"),
    ("A pond contains {S} fish.", "{sold} of the fish are caught and taken away",
     "{k} of the remaining fish are a bit smaller than the rest", "How many fish are still in the pond?"),
    ("A box contains {S} pens.", "{sold} of the pens are given away",
     "{k} of the remaining pens write in slightly lighter ink", "How many pens are still in the box?"),
    ("A parking lot has {S} cars.", "{sold} of the cars drive away",
     "{k} of the remaining cars are older models", "How many cars are still in the lot?"),
    ("A crate holds {S} oranges.", "{sold} of the oranges are sold",
     "{k} of the remaining oranges are slightly less ripe", "How many oranges are still in the crate?"),
]
rng = np.random.default_rng(SEED)
seen = set()
made = 0
while made < 28:
    S = int(rng.integers(30, 121))
    sold = int(rng.integers(5, S // 2))
    k = int(rng.integers(3, max(4, (S - sold) // 2)))
    key = (S, sold, k)
    if key in seen or (S - sold - k) < 1:
        continue
    seen.add(key)
    s0, s1, noop, q = NOOP1[made % len(NOOP1)]
    perturbed = f"{s0.format(S=S)} {s1.format(sold=sold)}, and {noop.format(k=k)}. {q}"
    base = f"{s0.format(S=S)} {s1.format(sold=sold)}. {q}"
    add("ii_noop", "competence", perturbed + ASK, S - sold, S - sold - k, base + ASK,
        "'slightly smaller/later' is a no-op; the attractor wrongly subtracts it.")
    made += 1

NOOP2 = [
    ("Liam buys {a} apples.", "He also keeps {b} oranges in a bowl at home.",
     "How many apples did Liam buy?"),
    ("A library adds {a} new novels this week.", "It already owns {b} maps in a separate archive.",
     "How many novels did the library add this week?"),
    ("A baker makes {a} loaves of bread this morning.", "The bakery also has {b} chairs for customers.",
     "How many loaves of bread did the baker make?"),
    ("Maria plants {a} tomato seedlings.", "Her neighbour separately owns {b} chickens.",
     "How many tomato seedlings did Maria plant?"),
    ("A cyclist rides {a} kilometres on Monday.", "She owns {b} pairs of running shoes.",
     "How many kilometres did the cyclist ride on Monday?"),
    ("A theatre sells {a} tickets for the evening show.", "The building has {b} fire exits.",
     "How many tickets were sold for the evening show?"),
]
made = 0
seen = set()
while made < 12:
    a = int(rng.integers(6, 60))
    b = int(rng.integers(3, 40))
    if (a, b) in seen:
        continue
    seen.add((a, b))
    s0, noise, q = NOOP2[made % len(NOOP2)]
    perturbed = f"{s0.format(a=a)} {noise.format(b=b)} {q}"
    base = f"{s0.format(a=a)} {q}"
    add("ii_noop", "competence", perturbed + ASK, a, a + b, base + ASK,
        "the second quantity is unrelated; the attractor wrongly adds it (a+b).")
    made += 1


def main():
    assert len({it["item_id"] for it in items}) == len(items)
    by_cat = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    payload = {"seed": SEED, "n": len(items), "by_category": by_cat,
               "control_modes": {m: sum(1 for it in items if it["control_mode"] == m)
                                 for m in ("memorized", "competence")},
               "items": items}
    text = json.dumps(payload, indent=2)
    (_HERE / "items.json").write_text(text)
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    print(f"N={len(items)}  by_category={by_cat}  modes={payload['control_modes']}")
    print(f"items.json sha256[:16]={h}\n")
    for it in items:
        print(f"[{it['item_id']}] ({it['control_mode'][:4]}) T={it['true_answer']:>7} "
              f"A={it['attractor_answer']:>7} :: {it['perturbed_prompt'][:82]}")
    return h


if __name__ == "__main__":
    main()
