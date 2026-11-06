# data/

Committed inputs and ground truth for the eval/cost scripts in `scripts/`.

| File | Produced by | Consumed by |
|---|---|---|
| `eval_cardd_gt.json` | `scripts/eval/build_gt.py` | `scripts/eval/run.py` |
| `cost_inputs.json` | `scripts/cost/build_inputs.py` | `scripts/cost/run_openai.py` |
| `claude_cost_benchmark.json` | external (Claude benchmark run) | `scripts/cost/compare.py` |

Local-only files (e.g. `*.db`) are git-ignored.
