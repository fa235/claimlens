# ClaimLens — Evaluation Report

This document consolidates two evaluations run against the **CarDD** car-damage
dataset:

1. **Damage detection** — ClaimLens (OpenAI gpt-4o vision) vs. CarDD ground-truth
   damage categories.
2. **Cost estimation** — ClaimLens OpenAI cost estimator vs. a Claude-generated
   cost benchmark.

- **Dataset:** CarDD (`CarDD_COCO/val2017`), 25 images sampled deterministically
  by filename, spanning all 6 damage categories. The dataset is not bundled with
  this repo — download it from the official source:
  [CarDD](https://cardd-ustc.github.io/) ([paper](https://arxiv.org/abs/2211.00945)).
- **Pipeline under test:** the real ClaimLens services (`app.services.vision`,
  `app.services.cost_estimator`), provider `openai` / `gpt-4o`.
- **Categories:** dent, scratch, crack, glass shatter, lamp broken, tire flat.

> **Important caveat.** CarDD is a damage *detection/segmentation* dataset. It
> has damage-category labels (used in Eval 1) but **no repair-cost labels**.
> Eval 2 therefore measures **agreement between two LLMs** (OpenAI vs Claude),
> not accuracy against real repair prices.

---

## Eval 1 — Damage Detection (vs. CarDD ground truth)

Multi-label task: for each image, does the model's reported damage set match the
CarDD category set? ClaimLens free-text damage types were mapped onto the 6 fixed
categories via a keyword mapper.

### Aggregate metrics

| Metric | Value |
|---|---|
| Micro precision | 0.789 |
| Micro recall | 0.667 |
| Micro F1 | 0.723 |
| Exact set-match rate | 0.44 |
| Any-damage detection rate | 1.00 |
| TP / FP / FN | 30 / 8 / 15 |

### Per-category metrics

| Category | Support | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| dent | 8 | 7 | 4 | 1 | 0.636 | 0.875 | 0.737 |
| scratch | 13 | 10 | 2 | 3 | 0.833 | 0.769 | 0.800 |
| crack | 7 | 0 | 0 | 7 | 0.000 | 0.000 | 0.000 |
| glass shatter | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| lamp broken | 8 | 6 | 2 | 2 | 0.750 | 0.750 | 0.750 |
| tire flat | 6 | 4 | 0 | 2 | 1.000 | 0.667 | 0.800 |

### Per-image results

| Image | Ground truth | Predicted | Exact match |
|---|---|---|---|
| 000013.jpg | crack, glass shatter, tire flat | glass shatter, tire flat | no |
| 000016.jpg | dent, scratch | scratch | no |
| 000017.jpg | scratch | scratch | yes |
| 000024.jpg | scratch | scratch | yes |
| 000025.jpg | scratch | scratch | yes |
| 000034.jpg | crack, dent, lamp broken, scratch | dent, lamp broken | no |
| 000035.jpg | crack, dent, lamp broken, scratch | dent, lamp broken | no |
| 000038.jpg | dent, lamp broken | dent, lamp broken | yes |
| 000047.jpg | dent, lamp broken | dent, lamp broken | yes |
| 000054.jpg | lamp broken, scratch, tire flat | dent, scratch | no |
| 000058.jpg | tire flat | tire flat | yes |
| 000059.jpg | tire flat | lamp broken | no |
| 000060.jpg | tire flat | tire flat | yes |
| 000080.jpg | dent, lamp broken, tire flat | dent, tire flat | no |
| 000083.jpg | lamp broken, scratch | dent, lamp broken, scratch | no |
| 000084.jpg | crack | scratch | no |
| 000086.jpg | crack, dent, scratch | dent, scratch | no |
| 000089.jpg | crack | dent, scratch | no |
| 000091.jpg | glass shatter | glass shatter | yes |
| 000097.jpg | scratch | lamp broken | no |
| 000102.jpg | crack, lamp broken | lamp broken | no |
| 000103.jpg | dent, glass shatter | dent, glass shatter | yes |
| 000105.jpg | scratch | dent, scratch | no |
| 000107.jpg | scratch | scratch | yes |
| 000109.jpg | scratch | scratch | yes |

### Findings

- **Detection of *some* damage is perfect (100%)** — but every CarDD image
  contains damage, so there are no clean-car negatives to test false alarms.
  This number is optimistic until undamaged cars are added to the set.
- **Strong on visually distinct damage:** glass shatter (F1 1.00), scratch and
  tire flat (0.80), lamp broken (0.75), dent (0.74).
- **Crack is the key failure: 0/7 recall.** gpt-4o never outputs the word
  "crack." Inspection of raw output shows it usually *sees* the damage but labels
  it "bumper damage", "hole", or folds it into dent/scratch. This is part model
  vocabulary and part taxonomy mismatch (CarDD "crack" = cracked body/bumper).
- **Most non-exact matches are single-label near-misses**, not missed damage.
- **Measurement note:** the free-text→category mapper is an approximation; a few
  "misses" (e.g. "wheel damage" not matched to tire flat) are mapper artifacts,
  not model failures.

---

## Eval 2 — Cost Estimation (OpenAI vs. Claude benchmark)

Both models received the **identical** 52 damage items (type/severity/location,
vehicle fixed to "Unknown") produced by the vision step. Claude's per-item
estimate is the reference; OpenAI's deviation from it is measured.

### Item-level agreement (n = 52)

| Metric | Value |
|---|---|
| Mean absolute error (MAE) | $123 |
| Median absolute error | $100 |
| MAPE (mean abs % error) | 22.8% |
| Median abs % error | 20.0% |
| Mean signed bias (OpenAI − Claude) | −$63 |
| Pearson correlation r | 0.896 |
| Mean cost — Claude / OpenAI | $542 / $480 |
| Items within 10% of Claude | 21% |
| Items within 25% of Claude | 58% |

### Claim-total agreement (n = 25 images)

| Metric | Value |
|---|---|
| Mean abs error on claim total | $218 |
| MAPE on claim total | 19.1% |
| Grand total — Claude | $28,210 |
| Grand total — OpenAI | $24,950 |

### Per-damage-type breakdown

| Damage type | n | Mean Claude | Mean OpenAI | MAE |
|---|---|---|---|---|
| scratch | 12 | $342 | $258 | $83 |
| dent | 9 | $639 | $567 | $161 |
| broken headlight | 6 | $650 | $458 | $192 |
| bumper damage | 5 | $700 | $690 | $170 |
| flat tire | 4 | $250 | $200 | $50 |
| scuff | 2 | $180 | $175 | $25 |
| shattered glass | 2 | $450 | $400 | $50 |
| rust | 1 | $800 | $600 | $200 |
| broken windshield | 1 | $450 | $400 | $50 |
| paint transfer | 1 | $200 | $200 | $0 |
| crumpled fender | 1 | $1200 | $1200 | $0 |
| fender damage | 1 | $1000 | $1200 | $200 |
| wheel damage | 1 | $600 | $700 | $100 |
| crumpled bodywork | 1 | $1500 | $1500 | $0 |
| broken taillight | 1 | $450 | $250 | $200 |
| hole | 1 | $900 | $600 | $300 |
| scratches | 1 | $500 | $400 | $100 |
| missing part | 1 | $800 | $1200 | $400 |
| paint peeling | 1 | $300 | $350 | $50 |

### Per-item detail

| Image | Item | Severity | Claude | OpenAI | Abs err | % err |
|---|---|---|---|---|---|---|
| 000013.jpg | rust | high | $800 | $600 | $200 | −25% |
| 000013.jpg | flat tire | high | $250 | $200 | $50 | −20% |
| 000013.jpg | broken windshield | high | $450 | $400 | $50 | −11% |
| 000016.jpg | scratch | medium | $350 | $250 | $100 | −29% |
| 000017.jpg | scratch | medium | $300 | $300 | $0 | +0% |
| 000024.jpg | scratch | medium | $350 | $250 | $100 | −29% |
| 000024.jpg | paint transfer | medium | $200 | $200 | $0 | +0% |
| 000025.jpg | scratch | medium | $350 | $250 | $100 | −29% |
| 000025.jpg | scuff | medium | $180 | $200 | $20 | +11% |
| 000034.jpg | crumpled fender | high | $1200 | $1200 | $0 | +0% |
| 000034.jpg | broken headlight | high | $650 | $400 | $250 | −38% |
| 000035.jpg | dent | high | $900 | $750 | $150 | −17% |
| 000035.jpg | broken headlight | high | $650 | $400 | $250 | −38% |
| 000038.jpg | dent | high | $900 | $750 | $150 | −17% |
| 000038.jpg | broken headlight | high | $650 | $600 | $50 | −8% |
| 000038.jpg | bumper damage | high | $850 | $900 | $50 | +6% |
| 000047.jpg | broken headlight | high | $650 | $450 | $200 | −31% |
| 000047.jpg | bumper damage | medium | $600 | $350 | $250 | −42% |
| 000047.jpg | dent | medium | $500 | $300 | $200 | −40% |
| 000054.jpg | dent | medium | $500 | $450 | $50 | −10% |
| 000054.jpg | scratch | medium | $350 | $150 | $200 | −57% |
| 000058.jpg | fender damage | high | $1000 | $1200 | $200 | +20% |
| 000058.jpg | flat tire | high | $250 | $250 | $0 | +0% |
| 000059.jpg | bumper damage | high | $850 | $1200 | $350 | +41% |
| 000059.jpg | wheel damage | high | $600 | $700 | $100 | +17% |
| 000059.jpg | broken headlight | high | $650 | $450 | $200 | −31% |
| 000060.jpg | flat tire | high | $250 | $150 | $100 | −40% |
| 000060.jpg | bumper damage | medium | $600 | $400 | $200 | −33% |
| 000080.jpg | crumpled bodywork | high | $1500 | $1500 | $0 | +0% |
| 000080.jpg | flat tire | high | $250 | $200 | $50 | −20% |
| 000083.jpg | scratch | medium | $350 | $300 | $50 | −14% |
| 000083.jpg | dent | medium | $500 | $450 | $50 | −10% |
| 000083.jpg | broken taillight | high | $450 | $250 | $200 | −44% |
| 000084.jpg | hole | high | $900 | $600 | $300 | −33% |
| 000084.jpg | scratch | medium | $350 | $250 | $100 | −29% |
| 000086.jpg | dent | high | $900 | $1200 | $300 | +33% |
| 000086.jpg | scratch | medium | $350 | $300 | $50 | −14% |
| 000089.jpg | scratches | high | $500 | $400 | $100 | −20% |
| 000089.jpg | dent | medium | $500 | $600 | $100 | +20% |
| 000089.jpg | missing part | high | $800 | $1200 | $400 | +50% |
| 000091.jpg | shattered glass | high | $450 | $400 | $50 | −11% |
| 000097.jpg | scratch | medium | $350 | $300 | $50 | −14% |
| 000097.jpg | scuff | medium | $180 | $150 | $30 | −17% |
| 000102.jpg | broken headlight | high | $650 | $450 | $200 | −31% |
| 000102.jpg | bumper damage | medium | $600 | $600 | $0 | +0% |
| 000103.jpg | shattered glass | high | $450 | $400 | $50 | −11% |
| 000103.jpg | dent | medium | $550 | $300 | $250 | −45% |
| 000105.jpg | scratch | medium | $350 | $150 | $200 | −57% |
| 000105.jpg | dent | medium | $500 | $300 | $200 | −40% |
| 000107.jpg | scratch | medium | $350 | $300 | $50 | −14% |
| 000107.jpg | paint peeling | medium | $300 | $350 | $50 | +17% |
| 000109.jpg | scratch | medium | $300 | $300 | $0 | +0% |

### Findings

- **Strong directional agreement (r = 0.896):** the two models rank damage cost
  very similarly, and agree almost exactly on structural/crumple damage, glass,
  and tires.
- **OpenAI runs consistently cheaper** — ~12% below Claude overall (−$63/item
  bias; grand total $24,950 vs $28,210). For an insurer, a systematically low
  estimator risks under-reserving.
- **Largest disagreements** are on lighting (OpenAI prices headlights/taillights
  ~30–44% below Claude) and some scratches; the biggest single over-estimate was
  "missing part" (+50%).
- **Claim-total % error (19%) is lower than per-item % error (23%)** because
  over/under-estimates partly cancel within a claim.

---

## Overall assessment

| Dimension | Verdict |
|---|---|
| Finds that damage exists | Excellent on this set (but no clean-car negatives tested) |
| Classifies damage type | Fair — strong except "crack" (0 recall) |
| Cost vs. a second model | Well-correlated (r 0.90), but ~12% low with a consistent downward bias |
| Ready for unsupervised claim decisions | No — keep human-in-the-loop |

### Caveats & limitations

1. **n = 25 is small** — metrics carry wide error bars; a 100+ image run would be
   more reliable.
2. **No real cost ground truth** — Eval 2 is model-vs-model agreement, not price
   accuracy.
3. **Claude benchmark was generated in-session** (not a re-runnable script). Plug
   an Anthropic/Bedrock credential into the same harness to automate it.
4. **Detection uses a keyword mapper** from free text to the 6 categories; some
   misses are mapping artifacts rather than model errors.

### Reproduction

Eval scripts live in `backend/eval/` (`damage_detection/` for damage accuracy,
`cost_estimation/` for the cost benchmark); inputs/ground truth in
`backend/data/`; generated results in `backend/reports/`. Run everything from
`backend/`:

Requires the backend dependencies, an `OPENAI_API_KEY`, and — for the detection
eval only — the CarDD dataset, with `CARDD_ROOT` pointing at the extracted
`CarDD_release` directory. Setup details are in
[`backend/eval/README.md`](../backend/eval/README.md).

```bash
cd backend
export CARDD_ROOT=~/Downloads/CarDD_release

python eval/damage_detection/build_gt.py # -> data/eval_cardd_gt.json
python eval/damage_detection/run.py      # -> reports/eval_cardd_results.json, reports/eval_cardd_report.md
python eval/cost_estimation/build_inputs.py # -> data/cost_inputs.json
python eval/cost_estimation/run_openai.py   # -> reports/openai_cost_results.json
python eval/cost_estimation/compare.py      # -> reports/cost_comparison.json, reports/cost_benchmark_report.md
```

`data/eval_cardd_gt.json` is committed, so `build_gt.py` only needs re-running to
change the image sample.

| File | Purpose |
|---|---|
| `eval/damage_detection/build_gt.py` | Build CarDD ground-truth category sets (25 images) |
| `data/eval_cardd_gt.json` | Ground-truth sets |
| `eval/damage_detection/run.py` | Run detection eval |
| `reports/eval_cardd_results.json` / `reports/eval_cardd_report.md` | Detection results + report |
| `eval/cost_estimation/build_inputs.py` / `data/cost_inputs.json` | Build shared cost inputs |
| `data/claude_cost_benchmark.json` | Claude reference cost estimates |
| `eval/cost_estimation/run_openai.py` / `reports/openai_cost_results.json` | OpenAI cost run |
| `eval/cost_estimation/compare.py` / `reports/cost_comparison.json` / `reports/cost_benchmark_report.md` | Cost comparison |
