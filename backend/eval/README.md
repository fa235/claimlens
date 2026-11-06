# Evaluation

Harnesses that measure ClaimLens. These are **not** part of the running
application (`app/`); they import `app.*` and run the real pipeline, then write
inputs/ground truth to `data/` and generated results to `reports/`.

Two kinds of evaluation:

- `detection/` — **accuracy**: how well damage detection matches the CarDD
  dataset's human-labeled ground truth.
- `cost/` — **cost estimates**: how ClaimLens's OpenAI repair-cost estimates
  compare against a Claude reference run (agreement, not real-price accuracy —
  CarDD has no cost labels).

All scripts resolve paths relative to the backend root, so run them from the
`backend/` directory:

```bash
cd backend
```

## detection/ — CarDD damage-detection evaluation

```bash
python eval/detection/build_gt.py   # build ground truth  -> data/eval_cardd_gt.json
python eval/detection/run.py        # run pipeline vs GT   -> reports/eval_cardd_results.json, reports/eval_cardd_report.md
```

`build_gt.py` reads the raw CarDD dataset from the path hard-coded at the top of
the file (download CarDD separately — see the root `README.md`).

## cost/ — LLM cost benchmark

```bash
python eval/cost/build_inputs.py   # reports/eval_cardd_results.json -> data/cost_inputs.json
python eval/cost/run_openai.py     # data/cost_inputs.json           -> reports/openai_cost_results.json
python eval/cost/compare.py        # openai + claude benchmarks      -> reports/cost_comparison.json, reports/cost_benchmark_report.md
```

## Pipeline order

```
detection/build_gt.py  ->  detection/run.py  ->  cost/build_inputs.py  ->  cost/run_openai.py  ->  cost/compare.py
```
