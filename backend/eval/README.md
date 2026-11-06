# Evaluation

Harnesses that measure ClaimLens. These are **not** part of the running
application (`app/`) and never run in production — they are on-demand scripts
that import `app.*`, run the real pipeline, and write inputs/ground truth to
`data/` and generated results to `reports/`.

Two kinds of evaluation:

- `damage_detection/` — **accuracy**: how well damage detection matches the
  CarDD dataset's human-labeled ground truth.
- `cost_estimation/` — **cost estimates**: how ClaimLens's OpenAI repair-cost
  estimates compare against a Claude reference run (agreement, not real-price
  accuracy — CarDD has no cost labels).

---

## Prerequisites

1. **Backend dependencies installed** (the scripts import `app.*`):

   ```bash
   cd backend
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **An OpenAI API key** — the evals make real `gpt-4o` calls, which cost money.
   Set it in `backend/.env` (see `.env.example`) or export it:

   ```bash
   export OPENAI_API_KEY=sk-...
   ```

3. **The CarDD dataset** (only needed for `damage_detection/`). It is ~several GB
   and is **not** in this repo. Download it from
   [CarDD](https://cardd-ustc.github.io/), extract it, and point `CARDD_ROOT` at
   the extracted `CarDD_release` directory:

   ```bash
   export CARDD_ROOT=~/Downloads/CarDD_release
   ```

   Defaults to `~/Downloads/CarDD_release` if unset. The scripts expect
   `$CARDD_ROOT/CarDD_COCO/val2017` and the matching `annotations/`.

No database is required — the scripts point `DATABASE_URL` at a throwaway
SQLite file so importing `app.*` never touches Postgres.

All scripts resolve their paths relative to the backend root, so **run them from
`backend/`**:

```bash
cd backend
```

---

## damage_detection/ — CarDD damage-detection evaluation

```bash
# 1. Build ground truth from the CarDD annotations (needs CARDD_ROOT)
python eval/damage_detection/build_gt.py   # -> data/eval_cardd_gt.json

# 2. Run the real pipeline over those images and score it
python eval/damage_detection/run.py        # -> reports/eval_cardd_results.json
                                           #    reports/eval_cardd_report.md
```

Step 1 is optional: `data/eval_cardd_gt.json` is already committed, so you can
run step 2 directly as long as the CarDD images are available under
`CARDD_ROOT`. Re-run step 1 only to change the sample (`N = 25` in the script).

Reports precision / recall / F1 per damage category, micro-averaged F1,
exact-set-match rate, and any-damage detection rate.

## cost_estimation/ — LLM cost benchmark

Does **not** need the CarDD dataset; it reuses the damage items from the
detection run.

```bash
python eval/cost_estimation/build_inputs.py   # reports/eval_cardd_results.json -> data/cost_inputs.json
python eval/cost_estimation/run_openai.py     # data/cost_inputs.json           -> reports/openai_cost_results.json
python eval/cost_estimation/compare.py        # openai + claude reference       -> reports/cost_comparison.json
                                              #                                    reports/cost_benchmark_report.md
```

`compare.py` treats the committed `data/claude_cost_benchmark.json` as the
reference. It measures OpenAI-vs-Claude **agreement** (MAE, MAPE, correlation),
not accuracy against real repair prices.

---

## Full pipeline order

```
damage_detection/build_gt.py
      -> damage_detection/run.py
            -> cost_estimation/build_inputs.py
                  -> cost_estimation/run_openai.py
                        -> cost_estimation/compare.py
```

Results are written to `../reports/`; see `../reports/README.md`. Published
findings and methodology live in `../../docs/EVALUATION.md`.
