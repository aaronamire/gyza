# Route 12 — GATE 0 report: PASS

All four sub-gates pass. Execution proceeded.

## 0a — preregistration precedes the analyzer and every result: **PASS**

`PREREGISTRATION_R12.md` committed at **`88a72b0`**. That commit contains **only**
the preregistration — no analyzer, no extended environment, no result artifact.

| artifact | commit | after `88a72b0`? |
|---|---|---|
| `channel_analyzer.py`, `extended_env.py`, `test_channels.py`, `_b1.json`, `_b2.json` | `5d522cb` | yes |
| `r12_result.json`, write-ups | this commit | yes |

The criterion (verbatim), the extended action vocabulary with hand-declared
`WRITES`, the hand-derived `READS(g)` table, the per-(action, guard, harm) BLIND
predictions, the two declared analyzer variants, the decision rule, and the point
predictions were all on record before any code that produces a result. The file
has not been edited since; deviations are disclosed in `FINDINGS_R12.md` §6.

## 0b — NON-CIRCULARITY: **PASS**

`channel_analyzer` reads **source text only**. It never opens `r9_result.json`,
`_scripted.json`, `_redteam.json`, `FINDINGS_R9.md`, `rt_cache/`, or
`r12_result.json` (`CA.FORBIDDEN`).

Enforced three ways, not asserted:

1. `CA.Module.__init__` refuses a forbidden path (`test_module_loader_refuses_forbidden_paths`).
2. `test_non_circularity_analyzer_never_reads_r9_results` installs a
   `sys.addaudithook` `open` monitor and runs the **full** analysis, asserting no
   forbidden file was opened.
3. **Negative control** — `test_non_circularity_negative_control` deliberately
   opens `r9_result.json` under the same hook and asserts the hook fires. Without
   it the first test would have no power.

Ground truth lives strictly on the evaluator side: `run_r12.py` loads R9's
committed results to *score* the analyzer, and hands the analyzer nothing but
source paths.

## 0c — NO LLM IN THE ANALYSIS PATH: **PASS**

Extraction is `ast` only. `test_no_llm_on_analysis_path` asserts the analyzer
source contains no model-client token (`openai`, `anthropic`, `openrouter`,
`groq`, `requests`, `urllib`, `http`, `api_key`, `apibackend`, `generate(`) and
that `import ast` is present.

This gate exists because **R5 died here**: an LLM extraction stage re-imported the
competence bound, and a strong vs weak extractor produced opposite-sign J on
identical traces. R12 has no such stage, so its negative result cannot be an
extractor artifact.

## 0d — CREDITS: **PASS (zero spend)**

Zero model calls. Static analysis plus deterministic simulation throughout —
analyzer, both variants, B1, B2, all adversary runs, the BFS validation, and the
Gyza source audit. No step required a model, so no STOP was triggered.

## Test gate

`test_channels.py`: **17 passed**, including the non-circularity negative control
and `test_criterion_is_one_sided_guard_reads_but_ignores`, which pins the
criterion's soundness direction by constructing a guard that reads a field,
ignores it entirely, and must still be classified NOT-BLIND.
