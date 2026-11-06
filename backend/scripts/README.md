# Backend scripts

One-off tooling for evaluation and cost benchmarking. These are **not** part of
the running application (`app/`); they produce the artifacts under `data/`
(inputs / ground truth) and `reports/` (generated results).

All scripts resolve paths relative to the backend root, so run them from the
`backend/` directory:

```bash
cd backend
```

## eval/ — CarDD damage-detection evaluation

```bash
python scripts/eval/build_gt.py   # build ground truth  -> data/eval_cardd_gt.json
python scripts/eval/run.py        # run pipeline vs GT   -> reports/eval_cardd_results.json, reports/eval_cardd_report.md
```

`build_gt.py` reads the raw CarDD dataset from the path hard-coded at the top of
the file (download CarDD separately — see the root `README.md`).

## cost/ — LLM cost benchmark

```bash
python scripts/cost/build_inputs.py   # reports/eval_cardd_results.json -> data/cost_inputs.json
python scripts/cost/run_openai.py     # data/cost_inputs.json           -> reports/openai_cost_results.json
python scripts/cost/compare.py        # openai + claude benchmarks      -> reports/cost_comparison.json, reports/cost_benchmark_report.md
```

## Pipeline order

```
eval/build_gt.py  ->  eval/run.py  ->  cost/build_inputs.py  ->  cost/run_openai.py  ->  cost/compare.py
```
