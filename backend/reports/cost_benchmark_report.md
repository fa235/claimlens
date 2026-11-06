# Cost Estimation Benchmark — OpenAI vs. Claude

**Benchmark model:** Claude (reference) · **Evaluated model:** OpenAI gpt-4o

Dataset: 25 CarDD images, 52 damage items. Both models received the **identical** damage type/severity/location inputs (vehicle fixed to Unknown).

> CarDD has no real repair-cost labels. This measures how closely the OpenAI estimator **agrees with Claude**, not accuracy against real prices.

## Item-level agreement (n = 52)

| Metric | Value |
|---|---|
| Mean absolute error (MAE) | $123 |
| Median absolute error | $100 |
| MAPE (mean abs % error) | 22.8% |
| Median abs % error | 20.0% |
| Mean signed bias (OpenAI − Claude) | $-63 |
| Pearson correlation r | 0.896 |
| Mean cost — Claude / OpenAI | $542 / $480 |
| Items within 10% of Claude | 21% |
| Items within 25% of Claude | 58% |

## Claim-total agreement (n = 25 images)

| Metric | Value |
|---|---|
| Mean abs error on claim total | $218 |
| MAPE on claim total | 19.1% |
| Grand total — Claude | $28,210 |
| Grand total — OpenAI | $24,950 |

## Per-damage-type breakdown

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

## Per-item detail

| Image | Item | Sev | Claude | OpenAI | Abs err | % err |
|---|---|---|---|---|---|---|
| 000013.jpg | rust | high | $800 | $600 | $200 | -25% |
| 000013.jpg | flat tire | high | $250 | $200 | $50 | -20% |
| 000013.jpg | broken windshield | high | $450 | $400 | $50 | -11% |
| 000016.jpg | scratch | medium | $350 | $250 | $100 | -29% |
| 000017.jpg | scratch | medium | $300 | $300 | $0 | +0% |
| 000024.jpg | scratch | medium | $350 | $250 | $100 | -29% |
| 000024.jpg | paint transfer | medium | $200 | $200 | $0 | +0% |
| 000025.jpg | scratch | medium | $350 | $250 | $100 | -29% |
| 000025.jpg | scuff | medium | $180 | $200 | $20 | +11% |
| 000034.jpg | crumpled fender | high | $1200 | $1200 | $0 | +0% |
| 000034.jpg | broken headlight | high | $650 | $400 | $250 | -38% |
| 000035.jpg | dent | high | $900 | $750 | $150 | -17% |
| 000035.jpg | broken headlight | high | $650 | $400 | $250 | -38% |
| 000038.jpg | dent | high | $900 | $750 | $150 | -17% |
| 000038.jpg | broken headlight | high | $650 | $600 | $50 | -8% |
| 000038.jpg | bumper damage | high | $850 | $900 | $50 | +6% |
| 000047.jpg | broken headlight | high | $650 | $450 | $200 | -31% |
| 000047.jpg | bumper damage | medium | $600 | $350 | $250 | -42% |
| 000047.jpg | dent | medium | $500 | $300 | $200 | -40% |
| 000054.jpg | dent | medium | $500 | $450 | $50 | -10% |
| 000054.jpg | scratch | medium | $350 | $150 | $200 | -57% |
| 000058.jpg | fender damage | high | $1000 | $1200 | $200 | +20% |
| 000058.jpg | flat tire | high | $250 | $250 | $0 | +0% |
| 000059.jpg | bumper damage | high | $850 | $1200 | $350 | +41% |
| 000059.jpg | wheel damage | high | $600 | $700 | $100 | +17% |
| 000059.jpg | broken headlight | high | $650 | $450 | $200 | -31% |
| 000060.jpg | flat tire | high | $250 | $150 | $100 | -40% |
| 000060.jpg | bumper damage | medium | $600 | $400 | $200 | -33% |
| 000080.jpg | crumpled bodywork | high | $1500 | $1500 | $0 | +0% |
| 000080.jpg | flat tire | high | $250 | $200 | $50 | -20% |
| 000083.jpg | scratch | medium | $350 | $300 | $50 | -14% |
| 000083.jpg | dent | medium | $500 | $450 | $50 | -10% |
| 000083.jpg | broken taillight | high | $450 | $250 | $200 | -44% |
| 000084.jpg | hole | high | $900 | $600 | $300 | -33% |
| 000084.jpg | scratch | medium | $350 | $250 | $100 | -29% |
| 000086.jpg | dent | high | $900 | $1200 | $300 | +33% |
| 000086.jpg | scratch | medium | $350 | $300 | $50 | -14% |
| 000089.jpg | scratches | high | $500 | $400 | $100 | -20% |
| 000089.jpg | dent | medium | $500 | $600 | $100 | +20% |
| 000089.jpg | missing part | high | $800 | $1200 | $400 | +50% |
| 000091.jpg | shattered glass | high | $450 | $400 | $50 | -11% |
| 000097.jpg | scratch | medium | $350 | $300 | $50 | -14% |
| 000097.jpg | scuff | medium | $180 | $150 | $30 | -17% |
| 000102.jpg | broken headlight | high | $650 | $450 | $200 | -31% |
| 000102.jpg | bumper damage | medium | $600 | $600 | $0 | +0% |
| 000103.jpg | shattered glass | high | $450 | $400 | $50 | -11% |
| 000103.jpg | dent | medium | $550 | $300 | $250 | -45% |
| 000105.jpg | scratch | medium | $350 | $150 | $200 | -57% |
| 000105.jpg | dent | medium | $500 | $300 | $200 | -40% |
| 000107.jpg | scratch | medium | $350 | $300 | $50 | -14% |
| 000107.jpg | paint peeling | medium | $300 | $350 | $50 | +17% |
| 000109.jpg | scratch | medium | $300 | $300 | $0 | +0% |
