# ClaimLens Evaluation on CarDD (COCO val2017)

- Images evaluated: **25**
- Provider / model: **openai / gpt-4o**
- Task: multi-label damage-category detection vs. CarDD ground truth
- Categories: dent, scratch, crack, glass shatter, lamp broken, tire flat

## Aggregate metrics

| Metric | Value |
|---|---|
| Micro precision | 0.789 |
| Micro recall | 0.667 |
| Micro F1 | 0.723 |
| Exact set-match rate | 0.440 |
| Any-damage detection rate | 1.000 |
| TP / FP / FN | 30 / 8 / 15 |

## Per-category metrics

| Category | Support | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| dent | 8 | 7 | 4 | 1 | 0.636 | 0.875 | 0.737 |
| scratch | 13 | 10 | 2 | 3 | 0.833 | 0.769 | 0.800 |
| crack | 7 | 0 | 0 | 7 | 0.000 | 0.000 | 0.000 |
| glass shatter | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| lamp broken | 8 | 6 | 2 | 2 | 0.750 | 0.750 | 0.750 |
| tire flat | 6 | 4 | 0 | 2 | 1.000 | 0.667 | 0.800 |

## Per-image results

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
