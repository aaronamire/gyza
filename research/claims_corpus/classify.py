"""B2 -- classification of the FROZEN corpus. AUTHORED, then tabulated.

MECHANICAL: the tabulation, the joint distribution, f, the single-issue-cell
check, the vagueness count, the judgement/UNSURE counts.
AUTHORED: every (act, det) pair below. The criterion narrows the choice; it
does not remove it. Each carries its basis: `i` = followed by inspection,
`j` = required judgement.

Criterion applied verbatim from research/census/PREREGISTRATION_CENSUS.md 2
via PREREGISTRATION_CLAIMS_CENSUS.md. "The system" = the repository plus its
test suite and CI, fixed in the preregistration before classification.

Corpus sha256 c5928b3d6e121e9ae7655023d46896ff1125940e437d9ae13cfad334ff6fa941
frozen at 9ab33b1; this file postdates it.

A = ASSERTIVE, D = DIRECTIVE, C = COMMISSIVE, L = DECLARATIVE
I = INTERNAL, U = UNDERDETERMINED, X = EXOGENOUS, T = CONTESTED, ? = UNSURE
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# index: (speech_act, determinacy, basis)
CLS: dict[int, tuple[str, str, str]] = {
    0: ("A", "I", "i"),   1: ("D", "I", "i"),   2: ("A", "I", "i"),
    3: ("D", "X", "j"),   4: ("A", "X", "j"),   5: ("A", "T", "j"),
    6: ("A", "I", "j"),   7: ("A", "I", "i"),   8: ("A", "X", "j"),
    9: ("D", "X", "j"),  10: ("A", "U", "j"),  11: ("D", "U", "j"),
    12: ("A", "I", "i"), 13: ("D", "I", "i"),  14: ("A", "U", "j"),
    15: ("A", "X", "j"), 16: ("A", "I", "j"),  17: ("D", "I", "i"),
    18: ("A", "X", "i"), 19: ("A", "U", "j"),  20: ("A", "U", "j"),
    21: ("A", "U", "j"), 22: ("D", "U", "j"),  23: ("A", "I", "i"),
    24: ("A", "X", "j"), 25: ("A", "U", "j"),  26: ("D", "I", "j"),
    27: ("A", "I", "i"), 28: ("A", "U", "j"),  29: ("A", "T", "j"),
    30: ("A", "I", "i"), 31: ("D", "I", "i"),  32: ("A", "I", "i"),
    33: ("A", "U", "j"), 34: ("D", "I", "i"),  35: ("D", "I", "j"),
    36: ("A", "I", "j"), 37: ("A", "X", "i"),  38: ("D", "I", "i"),
    39: ("A", "X", "i"), 40: ("A", "I", "j"),  41: ("A", "I", "j"),
    42: ("A", "U", "j"), 43: ("A", "I", "i"),  44: ("A", "I", "i"),
    45: ("A", "I", "i"), 46: ("A", "I", "i"),  47: ("A", "U", "j"),
    48: ("A", "I", "j"), 49: ("A", "I", "i"),  50: ("D", "U", "j"),
    51: ("D", "U", "j"), 52: ("A", "I", "i"),  53: ("A", "I", "i"),
    54: ("A", "I", "i"), 55: ("A", "I", "i"),  56: ("A", "I", "i"),
    57: ("D", "I", "i"), 58: ("A", "T", "j"),  59: ("A", "U", "j"),
    60: ("A", "T", "j"), 61: ("A", "I", "i"),  62: ("A", "I", "i"),
    63: ("A", "I", "i"), 64: ("A", "U", "j"),  65: ("A", "U", "j"),
    66: ("D", "U", "j"), 67: ("D", "I", "i"),  68: ("A", "I", "i"),
    69: ("A", "U", "j"), 70: ("D", "I", "j"),  71: ("A", "I", "i"),
    72: ("A", "I", "j"), 73: ("A", "U", "j"),  74: ("A", "I", "i"),
    75: ("A", "I", "i"), 76: ("A", "I", "j"),  77: ("A", "I", "i"),
    78: ("D", "I", "i"), 79: ("A", "I", "i"),  80: ("A", "I", "i"),
    81: ("A", "I", "i"), 82: ("A", "U", "j"),  83: ("D", "U", "j"),
    84: ("A", "I", "i"), 85: ("D", "U", "j"),  86: ("A", "I", "i"),
    87: ("A", "T", "j"), 88: ("D", "I", "i"),  89: ("A", "X", "i"),
    90: ("A", "T", "j"), 91: ("D", "U", "j"),  92: ("A", "I", "i"),
    93: ("A", "I", "i"), 94: ("A", "I", "i"),  95: ("D", "I", "i"),
    96: ("A", "I", "i"), 97: ("D", "I", "j"),  98: ("D", "I", "i"),
    99: ("A", "I", "i"), 100: ("A", "I", "i"), 101: ("D", "I", "i"),
    102: ("A", "I", "i"), 103: ("A", "U", "j"), 104: ("A", "I", "j"),
    105: ("A", "I", "i"), 106: ("A", "I", "i"), 107: ("A", "U", "j"),
    108: ("A", "I", "i"), 109: ("A", "I", "i"), 110: ("D", "I", "i"),
    111: ("A", "I", "i"), 112: ("A", "U", "j"), 113: ("A", "I", "i"),
    114: ("A", "I", "i"), 115: ("A", "I", "i"), 116: ("A", "I", "i"),
    117: ("D", "X", "j"), 118: ("A", "T", "j"), 119: ("A", "T", "j"),
    120: ("A", "X", "j"), 121: ("A", "X", "j"), 122: ("D", "U", "j"),
    123: ("A", "I", "i"), 124: ("A", "U", "j"), 125: ("A", "X", "j"),
    126: ("A", "I", "i"), 127: ("A", "T", "j"), 128: ("D", "I", "i"),
    129: ("A", "X", "i"), 130: ("A", "T", "j"), 131: ("A", "I", "i"),
    132: ("D", "I", "i"), 133: ("A", "I", "i"), 134: ("A", "U", "j"),
    135: ("A", "I", "j"), 136: ("A", "I", "i"), 137: ("A", "I", "i"),
    138: ("A", "I", "i"), 139: ("A", "I", "i"), 140: ("A", "U", "j"),
    141: ("D", "I", "i"), 142: ("A", "I", "i"), 143: ("A", "I", "i"),
    144: ("A", "T", "j"), 145: ("A", "I", "i"), 146: ("A", "U", "j"),
    147: ("A", "U", "j"), 148: ("A", "I", "i"), 149: ("A", "X", "j"),
    150: ("A", "X", "j"), 151: ("D", "U", "j"), 152: ("A", "U", "j"),
    153: ("A", "I", "i"), 154: ("D", "I", "i"), 155: ("D", "I", "i"),
    156: ("A", "I", "i"), 157: ("A", "I", "i"), 158: ("A", "I", "i"),
    159: ("D", "I", "i"), 160: ("A", "I", "i"), 161: ("A", "U", "j"),
    162: ("A", "X", "i"), 163: ("A", "I", "j"), 164: ("D", "U", "j"),
    165: ("A", "X", "j"), 166: ("A", "U", "j"), 167: ("A", "X", "j"),
    168: ("A", "I", "i"), 169: ("A", "I", "j"), 170: ("D", "I", "i"),
    171: ("A", "I", "i"), 172: ("A", "I", "i"), 173: ("A", "I", "i"),
    174: ("A", "I", "i"), 175: ("D", "I", "i"), 176: ("D", "U", "j"),
    177: ("A", "U", "j"), 178: ("D", "I", "i"), 179: ("A", "I", "i"),
    180: ("A", "I", "i"), 181: ("A", "X", "j"), 182: ("D", "U", "j"),
    183: ("A", "I", "j"), 184: ("A", "T", "j"), 185: ("A", "X", "i"),
    186: ("A", "I", "i"), 187: ("A", "U", "j"), 188: ("A", "X", "j"),
    189: ("D", "I", "i"), 190: ("A", "I", "i"), 191: ("A", "U", "j"),
    192: ("A", "U", "j"), 193: ("A", "U", "j"), 194: ("A", "I", "i"),
    195: ("A", "I", "i"), 196: ("D", "I", "i"), 197: ("A", "X", "j"),
    198: ("A", "I", "i"), 199: ("A", "X", "j"), 200: ("A", "I", "j"),
    201: ("A", "U", "j"), 202: ("A", "I", "i"), 203: ("A", "I", "i"),
    204: ("A", "U", "j"), 205: ("D", "I", "i"), 206: ("A", "I", "i"),
    207: ("A", "I", "j"), 208: ("A", "I", "i"), 209: ("A", "X", "i"),
    210: ("A", "I", "j"), 211: ("A", "U", "j"), 212: ("A", "I", "i"),
    213: ("A", "I", "i"), 214: ("A", "I", "i"),
}

ACTS = {"L": "DECLARATIVE", "C": "COMMISSIVE", "D": "DIRECTIVE", "A": "ASSERTIVE"}
DETS = {"I": "INTERNAL", "U": "UNDERDETERMINED", "X": "EXOGENOUS",
        "T": "CONTESTED", "?": "UNSURE"}

# B4, preregistered before data: terms whose referent the claim does not fix.
VAGUE = re.compile(
    r"\b(slow|slowness|wrong|unexpected|broken|should|vague|suboptimal|unclear|"
    r"surprising|confusing|complex|limited|some cases|not sure|likely|probably|"
    r"seems|sees to|hunch|guess|often|difficult|ideal|better|meaningful|"
    r"error-prone|notoriously)\b", re.I)


def main() -> None:
    claims = json.loads((HERE / "claims_hand.json").read_text())
    assert len(claims) == len(CLS), f"{len(claims)} claims vs {len(CLS)} classified"

    tbl = {a: Counter() for a in ACTS.values()}
    for i, c in enumerate(claims):
        a, d, _ = CLS[i]
        tbl[ACTS[a]][DETS[d]] += 1

    print("=" * 78)
    print("B2 -- JOINT DISTRIBUTION (n=%d)" % len(claims))
    print("=" * 78)
    hdr = f"{'':14}" + "".join(f"{d:>17}" for d in DETS.values())
    print(hdr)
    for a in ACTS.values():
        if sum(tbl[a].values()) == 0:
            continue
        print(f"{a:14}" + "".join(f"{tbl[a][d]:>17}" for d in DETS.values())
              + f"   | {sum(tbl[a].values())}")
    col = {d: sum(tbl[a][d] for a in ACTS.values()) for d in DETS.values()}
    print(f"{'TOTAL':14}" + "".join(f"{col[d]:>17}" for d in DETS.values()))

    row = tbl["ASSERTIVE"]
    exo = row["EXOGENOUS"] + row["CONTESTED"]
    tot = sum(row[d] for d in ("INTERNAL", "UNDERDETERMINED", "EXOGENOUS", "CONTESTED"))
    f = exo / tot
    print(f"\nB3  f = ({row['EXOGENOUS']} EXOGENOUS + {row['CONTESTED']} CONTESTED)"
          f" / {tot} ASSERTIVE = {f:.4f}")
    verdict = ("CENSUS-FAVOURABLE" if f < 0.50 else
               "CENSUS-UNFAVOURABLE" if f >= 0.80 else "CENSUS-INTERMEDIATE")
    print(f"    -> {verdict}")

    print(f"\nB4  UNDERDETERMINED total = {col['UNDERDETERMINED']}"
          f"  ({col['UNDERDETERMINED']/len(claims):.4f} of corpus)")
    vague = [i for i, c in enumerate(claims) if VAGUE.search(c["text"])]
    vu = sum(1 for i in vague if CLS[i][1] == "U")
    print(f"    claims containing an unfixed-referent term: {len(vague)}"
          f" ({len(vague)/len(claims):.4f})")
    print(f"    of those, classified UNDERDETERMINED: {vu} ({vu/len(vague):.4f})")
    nonvague_u = col["UNDERDETERMINED"] - vu
    print(f"    UNDERDETERMINED without such a term: {nonvague_u}")

    b = Counter(CLS[i][2] for i in range(len(claims)))
    print(f"\nB5  basis: inspection {b['i']}, judgement {b['j']}"
          f"  -> judgement fraction {b['j']/len(claims):.4f}")
    print(f"    UNSURE: {sum(1 for i in CLS if CLS[i][1] == '?')}"
          "  (reported separately from EXOGENOUS)")

    # single-ISSUE cell check (cap is 3/issue, so checked at issue granularity)
    print("\n    cells whose claims come from a single ISSUE -> INCONCLUSIVE:")
    cell_issues: dict[tuple, set] = {}
    for i, c in enumerate(claims):
        a, d, _ = CLS[i]
        cell_issues.setdefault((ACTS[a], DETS[d]), set()).add(c["issue"])
    flagged = False
    for (a, d), iss in sorted(cell_issues.items()):
        n = sum(1 for i, c in enumerate(claims)
                if ACTS[CLS[i][0]] == a and DETS[CLS[i][1]] == d)
        if len(iss) == 1:
            print(f"      {a} x {d}: n={n} from 1 issue -> INCONCLUSIVE")
            flagged = True
    if not flagged:
        print("      none")

    (HERE / "census_result.json").write_text(json.dumps({
        "n": len(claims),
        "joint": {a: dict(tbl[a]) for a in ACTS.values()},
        "f": f, "verdict": verdict,
        "underdetermined_total": col["UNDERDETERMINED"],
        "vague_terms": len(vague), "vague_and_underdetermined": vu,
        "basis": dict(b),
    }, indent=1))


if __name__ == "__main__":
    main()
