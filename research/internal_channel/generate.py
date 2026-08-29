"""Generate MBPP solutions with a LOCAL model and capture its internal states.

THE POINT OF THIS ROUTE, and the reason it needs local weights: every prior
mechanism in this program read the OUTPUT DISTRIBUTION. Prior corpora carry
correctness labels produced by OpenRouter models whose internals are
unavailable; local models have accessible internals but nobody labelled them.
This script produces BOTH from the SAME model in ONE pass, which is the only
way the two can be paired.

TWO PASSES PER PROBLEM, and they are separated deliberately:

  1. GENERATION -- batched, greedy. Batching is a ~3x throughput win on CPU
     because decode becomes a GEMM rather than a GEMV, and this machine has no
     GPU. Left-padded.
  2. RE-FORWARD -- UNBATCHED, on the unpadded prompt+completion sequence, to
     read hidden states and per-token logprobs. Unbatched on purpose: with
     left padding, "the last real token" is a different index in every row and
     a per-row off-by-one would silently probe a PAD position. Greedy decoding
     makes the re-forward exact -- the teacher-forced pass reproduces the same
     activations the generation produced.

WHAT IS STORED, and why it is not everything. Per-token hidden states for 25
layers over ~250 tokens is ~35 MB per problem, which is 17 GB over the task
set and does not fit. Stored instead, per layer: the FINAL-token state and the
MEAN over generated tokens only. Those are the two standard probe substrates,
and taking one vector per problem also makes the problem-level split of the
probe hold BY CONSTRUCTION rather than by discipline (see probe.py).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import pyarrow.parquet as pq
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

HERE = Path(__file__).resolve().parent
MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
MAX_NEW = 320
# batch_size x longest-prompt-in-batch ceiling, in tokens. Bounds the padded
# KV cache so one long prompt cannot force a large batch to carry it.
TOKEN_BUDGET = 3200
MBPP_GLOB = ("/home/xan/.cache/huggingface/hub/"
             "datasets--google-research-datasets--mbpp/snapshots/*/full/*.parquet")

# Calibration problems are used ONLY for the Gate-0 pass-rate estimate and the
# prompt format. They are EXCLUDED from the probe experiment, so no threshold
# is ever fixed against a problem the probe is later scored on.
CALIB_MAX_TASK_ID = 60


def load_mbpp() -> list[dict]:
    path = sorted(glob.glob(MBPP_GLOB))[0]
    return sorted(pq.read_table(path).to_pylist(), key=lambda r: r["task_id"])


def build_prompt(tok, row: dict) -> str:
    # The asserts go in the prompt because they carry the function signature,
    # which is not otherwise recoverable from the MBPP text. This is the
    # standard instruct-MBPP setup; it is disclosed because it means the model
    # has SEEN the tests it is scored against.
    tests = "\n".join(row["test_list"])
    user = (f"{row['text']}\nYour code should pass these tests:\n{tests}\n\n"
            "Write the function inside a single ```python code block. "
            "No explanation.")
    return tok.apply_chat_template([{"role": "user", "content": user}],
                                   tokenize=False, add_generation_prompt=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("calib", "experiment"), required=True)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    torch.set_num_threads(4)
    tok = AutoTokenizer.from_pretrained(MODEL)
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.float32)
    model.eval()

    # GREEDY MUST MEAN GREEDY. Qwen ships generation_config with
    # repetition_penalty 1.1, which applies even when do_sample=False -- the
    # emitted token would then not be the argmax of the raw logits, and the
    # teacher-forced re-forward below (which has no penalty) would report
    # logprobs for a decode that never happened. Neutralised explicitly.
    model.generation_config.repetition_penalty = 1.0
    model.generation_config.temperature = None
    model.generation_config.top_p = None
    model.generation_config.top_k = None

    # generate() halts on ANY id in generation_config.eos_token_id -- for Qwen
    # that is BOTH <|im_end|> (151645) and <|endoftext|> (151643), while
    # tok.eos_token_id is only the first. Truncating on the tokenizer's single
    # id would let a sequence that ended on the other one keep its PAD TAIL,
    # counting padding as generated tokens and corrupting n_gen, the logprobs
    # and the mean-pooled hidden state. Take the union, plus pad.
    _eos = model.generation_config.eos_token_id
    stop_ids = set(_eos if isinstance(_eos, (list, tuple)) else [_eos])
    stop_ids |= {tok.eos_token_id, tok.pad_token_id}
    stop_ids.discard(None)
    print(f"stop ids: {sorted(stop_ids)}", flush=True)

    rows = load_mbpp()
    rows = [r for r in rows
            if (r["task_id"] <= CALIB_MAX_TASK_ID) == (args.split == "calib")]
    if args.limit:
        rows = rows[:args.limit]

    out_dir = Path(args.out) if args.out else HERE / f"gen_{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "meta.jsonl"
    done = set()
    if meta_path.exists():
        done = {json.loads(l)["task_id"] for l in meta_path.open() if l.strip()}
    rows = [r for r in rows if r["task_id"] not in done]
    print(f"{args.split}: {len(rows)} to generate ({len(done)} already done), "
          f"layers={model.config.num_hidden_layers}", flush=True)

    # LENGTH-AWARE BATCHING. Left padding pads every row in a chunk up to the
    # LONGEST prompt in it, so a single outlier inflates the whole batch's KV
    # cache: task 493's 3743-token prompt would pad seven ~150-token prompts to
    # 3743 and cost ~800 MB of cache for nothing. Sorting by length makes
    # chunks homogeneous and capping batch x max_len bounds the worst case.
    # Sorting cannot change any result -- with left padding and an attention
    # mask, each sequence's greedy decode is independent of its batch-mates,
    # and outputs are keyed by task_id, not position.
    lens = {r["task_id"]: len(tok(build_prompt(tok, r)).input_ids) for r in rows}
    rows.sort(key=lambda r: lens[r["task_id"]])
    chunks, cur = [], []
    for r in rows:
        trial = cur + [r]
        if cur and (len(trial) > args.batch
                    or len(trial) * max(lens[x["task_id"]] for x in trial) > TOKEN_BUDGET):
            chunks.append(cur)
            cur = [r]
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    print(f"  {len(chunks)} chunks, sizes {sorted({len(c) for c in chunks})}, "
          f"longest prompt {max(lens.values()) if lens else 0} tokens", flush=True)

    t_start = time.time()
    n_done = 0
    for chunk in chunks:
        prompts = [build_prompt(tok, r) for r in chunk]
        enc = tok(prompts, return_tensors="pt", padding=True)
        t0 = time.time()
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=MAX_NEW, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        gen_dt = time.time() - t0
        n_prompt = enc.input_ids.shape[1]

        for j, row in enumerate(chunk):
            # Strip left padding from the prompt, and trailing pads that
            # generate() appends to rows which hit EOS before the batch did.
            keep = enc.attention_mask[j].bool()
            prompt_ids = enc.input_ids[j][keep]
            gen_ids = out[j][n_prompt:]
            stop = [k for k, t in enumerate(gen_ids.tolist()) if t in stop_ids]
            n_gen = stop[0] if stop else len(gen_ids)
            gen_ids = gen_ids[:n_gen]
            if n_gen == 0:                      # empty completion: nothing to probe
                _write(meta_path, row, "", 0, None, None, None)
                continue

            seq = torch.cat([prompt_ids, gen_ids]).unsqueeze(0)
            n_p = len(prompt_ids)
            with torch.no_grad():
                # logits_to_keep bounds the logit tensor to the last n_gen+1
                # positions -- exactly those that predict a generated token.
                # WITHOUT IT the model materialises (T, 151936) float32 over the
                # WHOLE sequence. MBPP task 493 carries a 3743-token prompt (25x
                # the median), which is a 2.47 GB single allocation on top of a
                # 2.4 GB model, and it OOM-killed this run TWICE at exactly that
                # task_id -- silently, with no traceback, which is what made it
                # look like a memory-pressure coincidence rather than one
                # problem. Hidden states are unaffected: they are returned for
                # every position either way.
                res = model(seq, output_hidden_states=True, logits_to_keep=n_gen + 1)

            # Position t predicts token t+1, so the distribution over generated
            # token k sits at index n_p + k - 1. With logits_to_keep the kept
            # window already BEGINS at n_p - 1, so the offset is applied here
            # and must not be applied twice.
            # Chunked over positions, because the vocabulary is 151936 wide:
            # log_softmax and its exp over ~320 positions at once is ~600 MB of
            # transient float32 on a machine with ~1.5 GB free.
            lg = res.logits[0, :-1]
            lps, ents = [], []
            for a in range(0, lg.shape[0], 32):
                blk = lg[a:a + 32].float()
                lsm = torch.log_softmax(blk, dim=-1)
                lps.append(lsm.gather(1, gen_ids[a:a + 32].unsqueeze(1)).squeeze(1))
                ents.append(-(lsm.exp() * lsm).sum(-1))
                del blk, lsm
            tok_lp = torch.cat(lps)
            ent = torch.cat(ents)

            # Layer 0 is the embedding output; 1..N are the transformer blocks.
            hs = res.hidden_states
            final = np.stack([h[0, -1].float().numpy() for h in hs]).astype(np.float16)
            mean = np.stack([h[0, n_p:].float().mean(0).numpy() for h in hs]
                            ).astype(np.float16)
            np.savez_compressed(out_dir / f"act_{row['task_id']}.npz",
                                final=final, mean=mean)

            _write(meta_path, row, tok.decode(gen_ids, skip_special_tokens=True),
                   n_gen,
                   {"mean_logprob": float(tok_lp.mean()),
                    "min_logprob": float(tok_lp.min()),
                    "sum_logprob": float(tok_lp.sum()),
                    "mean_entropy": float(ent.mean()),
                    "max_entropy": float(ent.max())},
                   int(n_p), list(hs[0].shape[-1:]))

        n_done += len(chunk)
        el = time.time() - t_start
        print(f"  {n_done}/{len(rows)}  bs={len(chunk)} gen={gen_dt:.0f}s  "
              f"elapsed={el / 60:.1f}m  "
              f"eta={(el / n_done) * (len(rows) - n_done) / 60:.0f}m", flush=True)


def _write(path, row, completion, n_gen, dist, n_prompt, hdim):
    with path.open("a") as f:
        f.write(json.dumps({
            "task_id": row["task_id"], "text": row["text"],
            "test_list": list(row["test_list"]),
            "test_setup_code": row["test_setup_code"],
            "reference_code": row["code"],
            "completion": completion, "n_gen_tokens": n_gen,
            "dist": dist, "n_prompt_tokens": n_prompt, "hidden_dim": hdim,
        }) + "\n")


if __name__ == "__main__":
    main()
