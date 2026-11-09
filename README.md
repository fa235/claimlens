# ClaimLens

AI-assisted car-insurance claim processing. A customer uploads a photo of the
damage; ClaimLens identifies the vehicle and every visible damage area, prices
an itemized repair estimate, and files the claim. Every claim is reviewed by a
human processor, who reviews, edits, and approves line items; low-confidence
results are flagged so the processor knows to look closer.

> From a week of back-and-forth to an estimate in seconds, with a human in the loop.

## Try the demo

Running live on AWS. There are two portals, start with the owner flow, then
switch to the processor view to review what you filed.

| | Portal | What to do |
|---|---|---|
| 🚗 | **[Owner — file a claim](http://claimlens-alb-192713703.us-east-1.elb.amazonaws.com/owner)** | Upload a photo of a damaged car and get an itemized estimate in seconds |
| 🧾 | **[Processor — review queue](http://claimlens-alb-192713703.us-east-1.elb.amazonaws.com/processor)** | See pending claims, then approve, edit, or decline individual line items |

No sign-up required. Any photo of a damaged car works, or grab one of the
[sample images](backend/tests/fixtures/images) from this repo.

> **Demo, not production.** It's HTTP-only with no authentication, so please
> don't upload anything sensitive. Each upload makes real `gpt-4o` calls.
> See [Gaps and risks](docs/DEPLOYMENT.md#gaps-and-risks).

![ClaimLens architecture](docs/claimlens_flow_taskID_2stepflow.svg)

---

## Table of contents

- [Try the demo](#try-the-demo)
- [Setup instructions](#setup-instructions)
- [Architecture overview](#architecture-overview)
- [Why these tools](#why-these-tools)
- [Screens](#screens)
- [Deployment](#deployment)
- [What's next](#whats-next)
- [Evaluation](#evaluation)
- [Model evaluation](#model-evaluation)

---

## Setup instructions

### Prerequisites

- Docker and Docker Compose (the quickest path), **or** Python 3.11+, Node 18+,
  and PostgreSQL 16 for a manual setup.
- An OpenAI API key with access to `gpt-4o`.

### Option A — Docker Compose (recommended)

This brings up Postgres, the FastAPI backend, and the React frontend together.

```bash
# 1. Clone and enter the repo
git clone https://github.com/fa235/claimlens.git
cd claimlens

# 2. Create the backend env file and add your OpenAI key
cp backend/.env.example backend/.env
#   then edit backend/.env and set OPENAI_API_KEY=sk-...

# 3. Start everything
docker compose up --build
```

- Frontend: http://localhost:5173
- API + docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Option B — Run services manually

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # set OPENAI_API_KEY and DATABASE_URL
alembic upgrade head            # create tables (or let the app auto-create on first run)

uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev                     # serves on http://localhost:5173
```

### Configuration

All backend config is read from environment variables (see
[`backend/.env.example`](backend/.env.example)). The ones you'll usually touch:

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | Key used for both vision and cost calls | _(required)_ |
| `LLM_PROVIDER` | `openai` (GPT-4o) or `bedrock` (Qwen, future) | `openai` |
| `OPENAI_VISION_MODEL` / `OPENAI_COST_MODEL` | Models for each step | `gpt-4o` |
| `VISION_LLM_PROVIDER` / `COST_LLM_PROVIDER` | Per-step provider override: `auto`, `openai`, `bedrock`, `fireworks` | `auto` |
| `STORAGE_BACKEND` | `local` (uploads/ folder) or `s3` | `local` |
| `DATABASE_URL` | PostgreSQL connection string | local Postgres |
| `REVIEW_CONFIDENCE_THRESHOLD` | Below this, a claim is flagged for human review | `0.6` |

Secrets live only in `backend/.env`, which is git-ignored.

### Running on open weights via Fireworks AI

Each step picks its provider independently, so you can move either one (or
both) off GPT-4o. Fireworks serves an OpenAI-compatible API, so this needs no
extra Python dependency — only a key from
[Fireworks](https://app.fireworks.ai/settings/users/api-keys).

```bash
# backend/.env — damage detection on Qwen 3.8 Max, pricing on GPT-OSS
VISION_LLM_PROVIDER=fireworks
COST_LLM_PROVIDER=fireworks
FIREWORKS_API_KEY=fw-...
```

| Step | Model | Tokens | Latency |
|---|---|---|---|
| Vision / damage detection | `qwen3p8-max` | 8192 | ~30–50s |
| Cost estimation | [`gpt-oss-120b`](https://fireworks.ai/models/fireworks/gpt-oss-120b) | 2048 | ~3s |

Measured end-to-end on the [sample images](backend/tests/fixtures/images):
`qwen3p8-max` identified a pearl-white Toyota and four damage line items
(including a door-to-quarter-panel gap misalignment) at 0.9 confidence, which
`gpt-oss-120b` priced at $1,300.

Four things to know before switching:

- **The vision model must be multimodal.** GPT-OSS is text-only — fine for
  pricing, but pointing `FIREWORKS_VISION_MODEL` at it will fail. Verified
  working vision models on serverless: `qwen3p8-max`, `qwen3p8-2p4t-a95b`, and
  `kimi-k3`. `glm-5p3` and `nemotron-3-ultra-nvfp4` reject image input.
- **Reasoning models need a large token budget.** `qwen3p8-max` spends its
  budget thinking before it answers: at 2048 and 4096 it never reaches the JSON
  and the vision step fails outright. 8192 works. `kimi-k3` manages on 4096.
- **Open weights are slower.** The vision call takes ~30–50s against GPT-4o's
  few seconds, which is slow for an interactive upload. `kimi-k3` returns in
  ~6s and is the better choice if latency matters more than Qwen's extra detail.
- **Fireworks caps base64 images at 10MB**, so oversized uploads are rejected
  locally rather than failing remotely.

`qwen3p8-flash-next-nvfp4` is **not** on serverless (404). Using it requires an
on-demand GPU deployment, then referencing it as `<model-id>#<deployment-name>`.

See [`backend/.env.example`](backend/.env.example) for every knob.

---

## Architecture overview

ClaimLens is a three-tier application: a React single-page app, a FastAPI
service, and a PostgreSQL database, with object storage for images and OpenAI
GPT-4o as the analysis engine.

### Components

| Layer | Technology | Responsibility |
|---|---|---|
| Frontend | React + Vite | Owner upload flow + processor review queue |
| API | FastAPI (Python) | Claim lifecycle, analysis orchestration, persistence |
| Analysis | OpenAI GPT-4o (swappable: Bedrock, Fireworks open weights) | One vision call (vehicle + damage), one cost call (pricing) |
| Database | PostgreSQL + SQLAlchemy / Alembic | Claims, damage line items, review state |
| Storage | Local filesystem or AWS S3 | Uploaded claim images |
| Packaging | Docker / Docker Compose | Local dev; same images run on AWS ECS Fargate |

### How data flows through it

1. **Upload.** The owner drops a photo into the React app, which `POST`s the
   image to the FastAPI backend.
2. **Persist the image.** The backend stores the file via the storage backend
   (local `uploads/` in dev, S3 in production) and creates a claim record.
3. **Vision call.** `analyze_image` sends the image to GPT-4o, which returns the
   vehicle color/model and a structured list of damage items (type, severity,
   location) plus an overall confidence.
4. **Cost call.** Each damage item is priced by a second GPT-4o call into an
   itemized repair estimate; the claim total excludes declined items.
5. **File for review.** The claim is written to Postgres as `pending` and
   enters the processor queue. If the damage confidence is below
   `REVIEW_CONFIDENCE_THRESHOLD`, it is additionally flagged (`needs_human_review`)
   so the processor knows to look closer.
6. **Human review.** Every claim is reviewed by a processor, who opens the
   queue, sees the itemized estimate and confidence, then approves, edits, or
   declines line items before approving or rejecting the claim.
7. **Status back to the owner.** The owner sees the claim progress through
   _Image Uploaded → Damage Evaluated → Claim Submitted → Awaiting Processor
   Review_.

The analysis is **LLM-only** by default: a single vision call does both vehicle
identification and damage detection, so there is no separate CV model to host.
A pluggable `DAMAGE_DETECTOR` (HuggingFace / fine-tuned YOLOv8) and an optional
multi-agent `ANALYSIS_MODE=agents` path exist as future extension points.

Steps 3 and 4 each choose their own provider, so the vision and cost models can
come from different vendors — GPT-4o, Qwen on Bedrock, or open weights on
Fireworks. See [Running on open weights](#running-on-open-weights-via-fireworks-ai).

---

## Why these tools

- **FastAPI** — async-first, which fits a workload dominated by outbound LLM
  calls; automatic OpenAPI docs at `/docs` make the API self-describing; and
  Pydantic gives typed request/response and env validation for free.
- **React + Vite** — two distinct user journeys (owner upload, processor review)
  are naturally a component-driven SPA; Vite keeps dev feedback fast.
- **OpenAI GPT-4o for both vision and cost** — a single multimodal model reads
  the car and its damage in one call and reasons about repair pricing in
  another. This avoids training, hosting, and maintaining a separate
  damage-detection CV model to ship a working end-to-end product. The provider
  is abstracted so Bedrock/Qwen can slot in later.
- **PostgreSQL + SQLAlchemy + Alembic** — claims are relational (a claim has
  many damage line items, each with its own review state), so a relational store
  is the right fit; Alembic keeps schema changes versioned.
- **S3 (with a local fallback)** — images are large binaries that don't belong
  in the database or a container's ephemeral disk; local storage keeps dev
  friction low while S3 is the production target.
- **Docker Compose → AWS ECS** — one command spins up the whole stack locally,
  and the same containers run in production on ECS Fargate, keeping dev and prod
  consistent. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the live
  architecture.

---

## Screens

**Owner — file a claim.** Upload a photo; the claim starts immediately, no forms
or phone calls.

![File a claim](docs/UX-2.png)

**Owner — instant claim report.** Vehicle, confidence, and an itemized,
severity-tagged repair estimate.

![Claim report](docs/UX-3.png)

**Processor — claim queue.** Pending / Approved / Rejected tabs; each row shows
the vehicle, estimate, and number of damage areas at a glance.

![Claim queue](docs/UX-1.png)

---

## Deployment

ClaimLens runs on AWS: **ECS Fargate** behind an **Application Load Balancer**,
with **RDS Postgres** and **S3** for claim images. Secrets come from AWS Secrets
Manager at task start. Live now — [owner portal](http://claimlens-alb-192713703.us-east-1.elb.amazonaws.com/owner)
· [processor portal](http://claimlens-alb-192713703.us-east-1.elb.amazonaws.com/processor).

| Layer | Resource |
|---|---|
| Compute | ECS Fargate services `claimlens-backend` (:8000), `claimlens-frontend` (:8080) |
| Routing | ALB `claimlens-alb` — `/api/*` and `/uploads/*` to backend, everything else to frontend |
| Database | RDS Postgres 16 (`claimlens-db`, not publicly accessible) |
| Images | `s3://claimlens-uploads-<account-id>` (`STORAGE_BACKEND=s3`) |
| Registry | ECR `claimlens-backend`, `claimlens-frontend` |

The ECS task definitions are checked in at [`infra/ecs/`](infra/ecs/). Full
architecture, redeploy commands, and known gaps are in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

> **Demo deployment, not production-hardened.** The ALB is HTTP-only (no TLS)
> and the API has no authentication yet, so claim data is publicly readable and
> uploads are unauthenticated. See
> [Gaps and risks](docs/DEPLOYMENT.md#gaps-and-risks).

---

## What's next

With more time, the priorities would be:

- **Tighten damage taxonomy.** Evaluation shows GPT-4o never emits the label
  "crack" (0 recall) even when it sees the damage. Fix the prompt vocabulary and
  the free-text→category mapping, and add clean-car negatives so false-alarm
  rate can actually be measured.
- **Ground cost estimates in real data.** Replace model-reasoned pricing with a
  lookup against real repair-cost data (parts + labor by region), so estimates
  are accurate rather than merely plausible, and capture actual API token usage
  to report a precise cost-per-claim.
- **Keep a human in the loop, but measure it.** Track processor override rate
  and estimate error to tune the review-confidence threshold and quantify time
  saved versus the manual baseline.
- **Harden for production.** Authentication/authorization for owners vs.
  processors, audit logging of every decision, retries and rate-limit handling
  around the LLM calls, and background processing for the analysis step.
- **Run the pilot.** Shadow mode on a slice of live claims for 4–6 weeks against
  the current manual process, with agreed success criteria (time-to-estimate,
  claims/processor/day, estimate accuracy, processor trust).

---

## Evaluation

ClaimLens was evaluated on the public **CarDD** car-damage dataset. Headline
results: 100% any-damage detection, micro-F1 0.72 on damage type, and repair
estimates that correlate 0.90 with reference costs (mean error ~$123 per item).
Full methodology, per-category metrics, and caveats are in
[`docs/EVALUATION.md`](docs/EVALUATION.md).

> **Dataset.** The CarDD dataset is **not** included in this repo (it's ~several
> GB). Download it from the official source and point the eval scripts at it:
> **CarDD — https://cardd-ustc.github.io/**
> (paper: [arXiv:2211.00945](https://arxiv.org/abs/2211.00945)). The eval
> scripts expect the `CarDD_COCO/val2017` images.

### Running the evaluation yourself

The harnesses live in `backend/eval/` (`damage_detection/` for accuracy,
`cost_estimation/` for the cost benchmark). They are on-demand scripts, not part
of the running service. Note that they make real `gpt-4o` calls, so they cost
money.

```bash
cd backend
source venv/bin/activate                  # deps from requirements.txt
export OPENAI_API_KEY=sk-...              # or set it in backend/.env
export CARDD_ROOT=~/Downloads/CarDD_release   # where you extracted CarDD

python eval/damage_detection/run.py       # score detection vs CarDD ground truth
python eval/cost_estimation/compare.py    # compare cost estimates vs reference
```

Both harnesses call the production code path, so they exercise whichever
provider is configured. That means you can benchmark the open-weight models
against the same ground truth and the same Claude cost reference:

```bash
# damage detection on Qwen 3.8 Max instead of GPT-4o
VISION_LLM_PROVIDER=fireworks python eval/damage_detection/run.py

# cost estimation on GPT-OSS, scored against the Claude benchmark
COST_LLM_PROVIDER=fireworks python eval/cost_estimation/run_openai.py
python eval/cost_estimation/compare.py --results reports/fireworks_cost_results.json \
    --out-json reports/cost_comparison_fireworks.json \
    --out-md   reports/cost_benchmark_report_fireworks.md
```

The cost runner names its output after the provider, so runs don't overwrite
each other, and the generated reports record which model produced them.

Ground truth and inputs are committed under `backend/data/`, so you can run the
scoring steps directly. Full setup, the complete pipeline order, and what each
script reads/writes are documented in
[`backend/eval/README.md`](backend/eval/README.md).

---

## Model evaluation

GPT-4o and Qwen tie on damage detection (F1 0.716 vs 0.713), but Qwen is 13×
slower and 5× dearer because it emits 23× more reasoning tokens. GPT-OSS prices
claims 12× cheaper than GPT-4o, with agreement inside run-to-run noise. Best
mix: GPT-4o vision + GPT-OSS cost.

| Step | Model | Accuracy | Latency | Cost / 1k claims |
|---|---|---|---|---|
| Damage detection | OpenAI `gpt-4o` | **F1 0.716** | **2.9s** | $4.16 |
| Damage detection | Fireworks `qwen3p8-max` | F1 0.713 | 37.1s | $20.34 |
| Cost estimation | OpenAI `gpt-4o` | MAE $138 · MAPE 25.5% | **1.4s** | $1.44 |
| Cost estimation | Fireworks `gpt-oss-120b` | MAE $147 · MAPE 29.4% | 2.0s | **$0.12** |
| Cost estimation | Fireworks `qwen3p8-max` | MAE $125 · MAPE 21.4% | 2.5s | $2.56 |

<sub>Measured 2026-11-09 over 125 live API calls (50 vision, 75 cost), 0
failures. **Damage
detection** accuracy is micro-F1 against CarDD human labels (25 images);
**cost estimation** accuracy is agreement with the committed Claude reference
(52 items) — CarDD has no repair-price labels, so it is not accuracy against
real prices. Cost is computed from each response's `usage` object at list rates
(`gpt-4o` $2.50/$10.00, `qwen3p8-max` $2.00/$6.00, `gpt-oss-120b` $0.15/$0.60
per 1M in/out). Fireworks models ran at `reasoning_effort=low`. The cost-step
differences are **within run-to-run noise**: a second `gpt-4o` run on identical
inputs scored MAE $123 / MAPE 22.8%, so treat the three as tied on cost
accuracy.</sub>
