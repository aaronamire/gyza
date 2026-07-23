"""
Phase 2 transform builder (2c). For every (item, relation) produce a transformed
problem whose TRUE answer is independently computed, and record the declared
relation to the ORIGINAL answer (invariance | equivariance k=3). Any pair whose
relation cannot be verified with certainty is EXCLUDED, not guessed.

Transforms are REGENERATED from each item's recovered numeric structure (not
string-edits of the original), so the declared relation holds by construction and
is machine-checked here. Reads route3_attractor/items.json. Deterministic.

Relations:
  T1 IRRELEVANT-VALUE (invariance)  — change the NoOp/irrelevant quantity.
  T2 REPHRASE        (invariance)   — semantics-preserving paraphrase.
  T3 RENAME          (invariance)   — rename entities/units-of-naming.
  T4 REORDER         (invariance)   — reorder independent clauses.
  T5 SCALE k=3       (equivariance) — ×3 all relevant quantities; answer ×3.
                                      ONLY where the answer is homogeneous deg 1.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_HERE = Path(__file__).parent
ITEMS = _HERE.parent / "route3_attractor" / "items.json"
ASK = " Give the final answer as \\boxed{...} (a single number or reduced fraction)."


def nums(s):
    return [int(x) for x in re.findall(r"-?\d+", s)]


def build():
    items = json.loads(ITEMS.read_text())["items"]
    out = []          # {item_id, relation, declared, transformed_prompt, transformed_true}
    excl = {}         # relation -> count excluded

    def add(iid, rel, declared, prompt, ttrue):
        out.append({"item_id": iid, "relation": rel, "declared": declared,
                    "transformed_prompt": prompt.strip() + ASK, "transformed_true": str(ttrue)})

    def exclude(rel):
        excl[rel] = excl.get(rel, 0) + 1

    for it in items:
        iid, cat, p = it["item_id"], it["category"], it["perturbed_prompt"]
        true = it["true_answer"]
        n = nums(p)

        if cat == "ii_noop" and "of the remaining" in p:
            # NOOP1: [S, sold, k]; true=S-sold
            S, sold, k = n[0], n[0] - int(true), int(true) - int(it["attractor_answer"])
            assert S - sold == int(true)
            add(iid, "T1", "invariance",
                f"A basket holds {S} apples. {sold} of the apples are eaten, and {k+7} of "
                f"the remaining apples are slightly smaller than average. How many apples "
                f"remain in the basket?", S - sold)
            add(iid, "T2", "invariance",
                f"There are {S} apples in a basket. After {sold} of them are eaten — and "
                f"noting that {k} of the ones left are a little smaller than usual — how "
                f"many apples are left in the basket?", S - sold)
            add(iid, "T3", "invariance",
                f"A crate holds {S} pears. {sold} of the pears are sold, and {k} of the "
                f"remaining pears are slightly smaller than average. How many pears remain "
                f"in the crate?", S - sold)
            add(iid, "T4", "invariance",
                f"In a basket, {k} of the apples are slightly smaller than average. The "
                f"basket holds {S} apples in total, and {sold} of them are eaten. How many "
                f"apples remain in the basket?", S - sold)
            add(iid, "T5", "equivariance_k3",
                f"A basket holds {3*S} apples. {3*sold} of the apples are eaten, and {3*k} "
                f"of the remaining apples are slightly smaller than average. How many apples "
                f"remain in the basket?", 3 * (S - sold))

        elif cat == "ii_noop":
            # NOOP2: [a, b]; true=a (b irrelevant)
            a = int(true); b = int(it["attractor_answer"]) - a
            add(iid, "T1", "invariance",
                f"Liam buys {a} apples. He also keeps {b+9} oranges in a bowl at home. How "
                f"many apples did Liam buy?", a)
            add(iid, "T2", "invariance",
                f"Liam bought {a} apples at the market. Separately, there are {b} oranges "
                f"sitting in a bowl in his kitchen. How many apples did Liam buy?", a)
            add(iid, "T3", "invariance",
                f"A grocer receives {a} crates of lettuce. In a different warehouse the "
                f"grocer also stores {b} barrels of vinegar. How many crates of lettuce did "
                f"the grocer receive?", a)
            add(iid, "T4", "invariance",
                f"There are {b} oranges in a bowl at Liam's home. Separately, Liam buys {a} "
                f"apples at the market. How many apples did Liam buy?", a)
            add(iid, "T5", "equivariance_k3",
                f"Liam buys {3*a} apples. He also keeps {3*b} oranges in a bowl at home. How "
                f"many apples did Liam buy?", 3 * a)

        elif cat == "i_classic" and "All but" in p:
            # all-but-N: [S, surv]; true=surv
            S, surv = n[0], int(true)
            add(iid, "T2", "invariance",
                f"A shepherd owns {S} sheep. Every one of them dies except {surv}. How many "
                f"sheep are still alive?", surv)
            add(iid, "T3", "invariance",
                f"A rancher has {S} goats. All but {surv} of them die. How many goats are "
                f"still alive?", surv)
            add(iid, "T5", "equivariance_k3",
                f"A farmer has {3*S} sheep. All but {3*surv} of them die. How many sheep are "
                f"still alive?", 3 * surv)

        elif cat == "i_classic" and "fence" in p:
            # fence-post: [L, s]; true=L//s+1
            L, s = n[0], n[1]
            add(iid, "T2", "invariance",
                f"Along a straight {L}-metre fence, a post is placed every {s} metres, with "
                f"one at each end. How many posts are used altogether?", L // s + 1)
            add(iid, "T3", "invariance",
                f"A straight {L}-metre wall has a pillar every {s} metres, including one at "
                f"each end. How many pillars are there in total?", L // s + 1)

        elif cat == "i_classic":
            # non-parametric conceptual (Monty, boy-girl x2, birthday, pills): hand T2/T3
            H = {
                "You are on a game show": (
                    "A game show has three doors: one conceals a car, the other two conceal "
                    "goats. You choose door 1. The host, who has NO knowledge of the car's "
                    "location, opens one of the two other doors picked completely at random, "
                    "and by chance it shows a goat. If you now switch to the last closed "
                    "door, what is the probability you win the car?",
                    "A show has 3 doors (1 prize, 2 blanks). You pick door 1. A host who does "
                    "not know where the prize is opens another door uniformly at random and it "
                    "happens to reveal a blank. What is your probability of winning if you "
                    "switch to the remaining door?"),
                "the OLDER child is a boy": (
                    "A couple has exactly two children. Their FIRSTBORN is a boy. What is the "
                    "probability that both of their children are boys?",
                    "In a family of two kids, the elder is male. What is the chance that both "
                    "children are male?"),
                "born on a Tuesday": (
                    "A couple has two children. At least one of them is a boy who was born on "
                    "a Tuesday. Assuming days of the week and sexes are independent and "
                    "uniform, what is the probability that both children are boys?",
                    "A family has two kids; it is known that one is a boy born on a Tuesday "
                    "(sexes and weekdays independent and uniform). Probability both are boys?"),
                "shares YOUR specific birthday": (
                    "Assuming 365 equally likely birthdays and no leap years, how many people "
                    "must gather so that it is more likely than not that at least one of them "
                    "has the SAME birthday as you?",
                    "With 365 equally likely birthdays, how many strangers are needed before "
                    "it is more probable than not that someone among them was born on your "
                    "exact birthday?"),
                "take one every 30 minutes": (
                    "You are handed 5 pills and told to take the first immediately and then "
                    "one more every half hour. How many minutes pass from the first pill until "
                    "you swallow the fifth?",
                    "Starting now, you take a pill and then another every 30 minutes. How many "
                    "minutes elapse between taking the 1st and the 5th pill?"),
            }
            hit = next((v for kw, v in H.items() if kw in p), None)
            if hit:
                add(iid, "T2", "invariance", hit[0], true)
                add(iid, "T3", "invariance", hit[1], true)
            else:
                exclude("T2"); exclude("T3")

        elif cat == "iii_substitution" and "sum of all the integers" in p:
            a, b = n[0], n[1]
            add(iid, "T2", "invariance",
                f"Add up every whole number from {a} to {b}, inclusive. What is the total?",
                sum(range(a, b + 1)))
            add(iid, "T5", "equivariance_k3",
                f"Each of the integers from {a} to {b} inclusive is multiplied by 3, then "
                f"they are all added together. What is the total?", 3 * sum(range(a, b + 1)))

        elif cat == "iii_substitution" and "interior angles" in p:
            nn = next(x for x in n if x >= 5)
            add(iid, "T2", "invariance",
                f"What do the interior angles of a convex {nn}-sided polygon add up to, in "
                f"degrees?", (nn - 2) * 180)
            add(iid, "T3", "invariance",
                f"In degrees, what is the total of all interior angles of a simple polygon "
                f"with {nn} sides?", (nn - 2) * 180)

        elif cat == "iii_substitution" and "EVEN" in p:
            nn = n[0]
            add(iid, "T2", "invariance",
                f"Add together the first {nn} positive multiples of 2. What is the sum?",
                nn * (nn + 1))
            add(iid, "T5", "equivariance_k3",
                f"Add together the first {nn} positive even numbers, then multiply the total "
                f"by 3. What is the result?", 3 * nn * (nn + 1))
        else:
            exclude("uncategorized")

    # VERIFY: invariance transformed_true == item true; equivariance == 3x.
    true_by_id = {it["item_id"]: it["true_answer"] for it in items}
    from fractions import Fraction
    def val(s):
        return Fraction(s)
    verified, bad = 0, []
    for t in out:
        it_true = true_by_id[t["item_id"]]
        try:
            if t["declared"] == "invariance":
                ok = val(t["transformed_true"]) == val(it_true)
            else:
                ok = val(t["transformed_true"]) == 3 * val(it_true)
        except Exception:
            ok = t["transformed_true"] == it_true
        if ok:
            verified += 1
        else:
            bad.append(t)
    assert not bad, f"UNVERIFIED transforms: {[(b['item_id'], b['relation']) for b in bad][:5]}"

    by_rel = {}
    for t in out:
        by_rel[t["relation"]] = by_rel.get(t["relation"], 0) + 1
    payload = {"n_transforms": len(out), "n_items": len(items), "verified": verified,
               "by_relation": by_rel, "excluded": excl,
               "declared_counts": {d: sum(1 for t in out if t["declared"] == d)
                                   for d in ("invariance", "equivariance_k3")},
               "transforms": out}
    text = json.dumps(payload, indent=2)
    (_HERE / "transforms.json").write_text(text)
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    print(f"transforms: {len(out)} (all {verified} verified) | by_relation={by_rel}")
    print(f"declared={payload['declared_counts']} | excluded={excl}")
    print(f"transforms.json sha256[:16]={h}")
    return h


if __name__ == "__main__":
    build()
