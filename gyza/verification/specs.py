"""
V-5 spec evaluation engine.

"The verifier accepted it" is NOT a measurement. The dominant failure mode is
VERIFIABLE-BUT-VACUOUS: `lambda inp, out: True` is perfectly valid and worth
nothing, and validity is precisely the metric that hides it. So strength is
measured as a MUTATION KILL RATE, and never reported bare -- always as a
position between a TYPE-ONLY floor and a hand-written reference-spec ceiling,
because a kill rate of 0.3 is uninterpretable without both.

Mutant classification follows R14's discipline exactly:
  WRONG       fails the reference behaviour  -> the kill-rate denominator
  EQUIVALENT  still matches the reference    -> EXCLUDED, not counted as a miss
              (no sound spec can reject it)
  DISCARDED   raises on construction/import  -> excluded entirely
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass
class SpecStrength:
    validity: bool
    killed: int
    denom: int
    equivalent: int
    discarded: int
    kill_rate: float | None
    floor: float | None
    ceiling: float | None

    @property
    def position(self) -> str:
        """Strength as a POSITION, never a bare number."""
        if self.kill_rate is None:
            return "not scorable (spec invalid or no WRONG mutants)"
        if self.floor is None or self.ceiling is None:
            return f"kill {self.kill_rate:.3f} (no floor/ceiling — uninterpretable)"
        if self.ceiling <= self.floor:
            return f"kill {self.kill_rate:.3f} (degenerate floor/ceiling)"
        frac = (self.kill_rate - self.floor) / (self.ceiling - self.floor)
        return (f"kill {self.kill_rate:.3f} — floor {self.floor:.3f}, "
                f"ceiling {self.ceiling:.3f}, {frac:+.0%} of the way up")


def _apply(fn, inp):
    try:
        return ("OK", fn(*inp) if isinstance(inp, tuple) else fn(inp))
    except Exception:
        return ("ERR", None)


def evaluate_spec_strength(
    spec: Callable, ref: Callable, mutants: Sequence[Callable],
    inputs: Sequence, *,
    floor_spec: Callable | None = None,
    ceiling_spec: Callable | None = None,
) -> SpecStrength:
    ref_out = [_apply(ref, i) for i in inputs]

    def score(sp) -> tuple[bool, int, int, int, int]:
        # VALIDITY: must accept the reference on every input.
        for i, (st, v) in zip(inputs, ref_out):
            if st != "OK":
                continue
            try:
                if sp(i, v) is not True:
                    return (False, 0, 0, 0, 0)
            except Exception:
                return (False, 0, 0, 0, 0)
        killed = denom = equiv = disc = 0
        for m in mutants:
            outs = [_apply(m, i) for i in inputs]
            if all(s == "ERR" for s, _ in outs):
                disc += 1
                continue
            if all(a == b for a, b in zip(outs, ref_out)):
                equiv += 1               # EXCLUDED, never a miss
                continue
            denom += 1
            hit = False
            for i, (st, v) in zip(inputs, outs):
                if st != "OK":
                    continue
                try:
                    if sp(i, v) is False:
                        hit = True
                        break
                except Exception:
                    continue
            killed += 1 if hit else 0
        return (True, killed, denom, equiv, disc)

    valid, killed, denom, equiv, disc = score(spec)
    kr = (killed / denom) if (valid and denom) else None

    def rate(sp):
        if sp is None:
            return None
        v, k, d, _e, _x = score(sp)
        return (k / d) if (v and d) else None

    return SpecStrength(valid, killed, denom, equiv, disc, kr,
                        rate(floor_spec), rate(ceiling_spec))
