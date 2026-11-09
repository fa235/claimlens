# Deployment (AWS)

ClaimLens runs on **ECS Fargate** behind an **Application Load Balancer**, with
**RDS Postgres** for data and **S3** for uploaded claim images. This document
records the live deployment as it actually exists, captured from the running
AWS account.

- **Region:** `us-east-1`
- **Live demo:** http://claimlens-alb-192713703.us-east-1.elb.amazonaws.com

Resource names below use `<account-id>` where the real AWS account number
appears. Nothing in this repo is tied to a specific account — see
[Reproducing this in your own account](#reproducing-this-in-your-own-account).

> The infrastructure was originally created imperatively via the AWS CLI, not
> from checked-in IaC. It has since been captured in two places: the ECS task
> definitions in [`infra/ecs/`](../infra/ecs/), and
> [`infra/scripts/provision.sh`](../infra/scripts/provision.sh), which recreates
> the full stack and was reconstructed from CloudTrail records of the original
> deployment. See [Gaps](#gaps-and-risks) for what that still doesn't give you.

---

## Architecture

```
                  Internet
                     │  HTTP :80
            ┌────────▼─────────┐
            │  claimlens-alb   │  (internet-facing ALB)
            └────┬─────────┬───┘
     /api/*      │         │  everything else
     /uploads/*  │         │  (default rule)
          ┌──────▼───┐ ┌───▼───────┐
          │ backend  │ │ frontend  │   ECS Fargate services
          │  :8000   │ │  :8080    │   (desired count 1 each)
          └────┬─────┘ └───────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
  RDS Postgres     S3 uploads
  claimlens-db     claimlens-uploads-<account-id>
```

### Components

| Resource | Identifier | Notes |
|---|---|---|
| ECS cluster | `default` | Both services run here |
| Backend service | `claimlens-backend` | Fargate, 2048 CPU / 4096 MiB, 1 task |
| Frontend service | `claimlens-frontend` | Fargate, 256 CPU / 512 MiB, 1 task |
| Load balancer | `claimlens-alb` | internet-facing, HTTP :80 only |
| Target groups | `claimlens-backend-tg` (health `/health`), `claimlens-frontend-tg` (health `/`) | both healthy |
| ECR repos | `claimlens-backend`, `claimlens-frontend` | images pushed as `:latest` |
| Database | `claimlens-db` — Postgres 16.13, `db.t3.micro` | not publicly accessible |
| Image storage | `s3://claimlens-uploads-<account-id>` | `STORAGE_BACKEND=s3` |
| Logs | CloudWatch `/ecs/claimlens-backend`, `/ecs/claimlens-frontend` | stream prefix `ecs` |

### ALB routing

One HTTP listener on port 80 with two rules:

| Priority | Path | Target |
|---|---|---|
| 10 | `/api/*`, `/uploads/*` | backend |
| default | everything else | frontend |

Because only `/api/*` and `/uploads/*` reach the backend, the API's `/health`
endpoint is **not** publicly reachable through the ALB — requesting `/health` on
the ALB returns the frontend's HTML. The ALB health check still hits `/health`
directly on the backend task, which is why the target group reports healthy.

### IAM roles

| Role | Used by | Purpose |
|---|---|---|
| `ClaimLensECSExecutionRole` | both task definitions | pull from ECR, write logs, read secrets |
| `ClaimLensBackendInstanceRole` | backend task role | app's own AWS access (S3 uploads) |

The frontend has no task role, it serves static assets and needs no AWS access.

### Configuration

Non-secret settings are plain environment variables in the backend task
definition:

| Variable | Value |
|---|---|
| `LLM_PROVIDER` | `openai` |
| `OPENAI_VISION_MODEL` / `OPENAI_COST_MODEL` | `gpt-4o` |
| `VISION_LLM_PROVIDER` / `COST_LLM_PROVIDER` | `auto` (set to `fireworks` to run a step on open weights) |
| `STORAGE_BACKEND` | `s3` |
| `S3_BUCKET` | `claimlens-uploads-<account-id>` |
| `DAMAGE_DETECTOR` | `huggingface` |
| `HF_DAMAGE_MODEL` | `Naiscorp/car-damage-detection` |
| `DAMAGE_CONF_THRESHOLD` | `0.5` |
| `SAVE_ANNOTATED` | `true` |
| `CORS_ORIGINS` | the ALB URL |
| `AWS_REGION` | `us-east-1` |

Secrets are pulled from **AWS Secrets Manager** at task start (not stored in the
task definition):

| Secret | Injected as |
|---|---|
| `claimlens/openai-api-key` | `OPENAI_API_KEY` |
| `claimlens/database-url` | `DATABASE_URL` |

If you move a step to Fireworks (`VISION_LLM_PROVIDER` / `COST_LLM_PROVIDER` =
`fireworks`), add a `claimlens/fireworks-api-key` secret injected as
`FIREWORKS_API_KEY` the same way. Don't put the key in the task definition.

### Network isolation

The task security groups only accept traffic **from the ALB's security group**,
not from the internet:

- `claimlens-backend-task-sg` — port 8000 from `claimlens-alb-sg` only
- `claimlens-frontend-task-sg` — port 8080 from `claimlens-alb-sg` only
- `claimlens-alb-sg` — port 80 from `0.0.0.0/0`

Tasks run in two subnets in different availability zones, with public IPs
assigned (needed for ECR and Secrets Manager access without a NAT gateway).

---

## Reproducing this in your own account

Nothing in this repo is tied to a particular AWS account. The provisioning
script discovers the account, region, VPC, and subnets at runtime, and the task
definitions in `infra/ecs/` are templates whose placeholders are filled in for
whichever account you are authenticated against.

**Prerequisites:** AWS CLI v2 with credentials, Docker, and a VPC with subnets
in at least two availability zones (the default VPC works).

```bash
git clone https://github.com/fa235/claimlens.git
cd claimlens

# 1. Preview — makes no changes, prints what it would create
./infra/scripts/provision.sh

# 2. Create everything
APPLY=1 \
  OPENAI_API_KEY=sk-...          \
  DB_PASSWORD=<choose-a-password> \
  ./infra/scripts/provision.sh

# 3. Build and push the images, then roll them out
#    (see "Build and push images" below)

# 4. Run database migrations against RDS
```

Order of operations: ECR repos → S3 bucket → security groups → RDS (waits for
`available`, several minutes) → Secrets Manager → IAM roles → log groups → ALB,
target groups, listener, routing rule → task definitions → ECS services.

The script skips anything that already exists, so re-running it is safe and
reports `exists` for resources already in place.

### Choosing a different region or VPC

```bash
AWS_REGION=eu-west-1 ./infra/scripts/provision.sh          # different region
VPC_ID=vpc-abc123 ./infra/scripts/provision.sh             # specific VPC
SUBNET_A=subnet-aaa SUBNET_B=subnet-bbb ./infra/scripts/provision.sh
ECS_CLUSTER=my-cluster ./infra/scripts/provision.sh
```

### Rendering a task definition by hand

`infra/ecs/*.json` contain placeholders (`{{ACCOUNT_ID}}`, `{{REGION}}`,
`{{S3_BUCKET}}`, `{{ALB_DNS}}`, and the two secret ARNs), so they cannot be
registered directly. Render them first:

```bash
python3 infra/scripts/render_taskdef.py infra/ecs/claimlens-backend.json > /tmp/td.json
aws ecs register-task-definition --cli-input-json file:///tmp/td.json
```

The renderer resolves placeholders from your own account; every one can also be
overridden by an environment variable of the same name, which makes it usable
offline or in CI.

---

## Redeploying

### Build and push images

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
ECR=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com

aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ECR

# Backend
docker build --platform linux/amd64 -t $ECR/claimlens-backend:latest ./backend
docker push $ECR/claimlens-backend:latest

# Frontend
docker build --platform linux/amd64 -t $ECR/claimlens-frontend:latest ./frontend
docker push $ECR/claimlens-frontend:latest
```

`--platform linux/amd64` matters when building on Apple Silicon; Fargate runs
x86_64 by default and an arm64 image will fail to start.

### Roll out the new images

Because both task definitions reference the `:latest` tag, a new image needs a
forced new deployment rather than a task-definition change:

```bash
aws ecs update-service --cluster default --service claimlens-backend  --force-new-deployment
aws ecs update-service --cluster default --service claimlens-frontend --force-new-deployment
```

### Apply a task-definition change

```bash
aws ecs register-task-definition --cli-input-json file://infra/ecs/claimlens-backend.json
aws ecs update-service --cluster default --service claimlens-backend \
  --task-definition claimlens-backend
```

### Database migrations

Alembic migrations are not run automatically by the service. Run them against
RDS from a machine that can reach the database (the instance is not publicly
accessible, so this needs a bastion/VPN or a one-off ECS task):

```bash
DATABASE_URL=<from Secrets Manager> alembic upgrade head
```

### Verify

```bash
URL=http://claimlens-alb-192713703.us-east-1.elb.amazonaws.com
curl -s -o /dev/null -w "%{http_code}\n" $URL/        # frontend
curl -s "$URL/api/claims" | head -c 200               # backend

aws ecs describe-services --cluster default \
  --services claimlens-backend claimlens-frontend \
  --query 'services[].{name:serviceName,running:runningCount,desired:desiredCount}'

aws logs tail /ecs/claimlens-backend --since 10m
```

---

## Gaps and risks

Known shortcomings of the current deployment, in rough priority order.

1. **No authentication on the API.** `GET /api/claims` is publicly readable and
   returns real claim records (vehicle details, license plate field, image
   URLs). Uploads are also unauthenticated, and every upload triggers two
   billable `gpt-4o` calls, so an open endpoint is both a data-exposure and a
   cost risk. The README already lists auth under "What's next"; until it
   exists, treat the URL as sensitive and consider restricting the ALB by source
   IP or putting it behind basic auth.
2. **HTTP only, no TLS.** The ALB has a single port-80 listener and no
   certificate, so claim images and data travel in cleartext. Fix: request an
   ACM certificate, add an HTTPS :443 listener, and redirect :80 → :443.
3. **Mutable `:latest` image tags.** Both task definitions point at `:latest`,
   so there is no record of which build is running and no clean rollback. Fix:
   tag images with the git SHA and register a new task-definition revision per
   deploy.
4. **No declarative IaC.** The stack can now be rebuilt with
   `infra/scripts/provision.sh`, but a provisioning script is weaker than real
   infrastructure-as-code: it creates and skips, it does not detect or correct
   drift, and a resource changed by hand will silently diverge from the script.
   Fix: import the resources into Terraform and make `plan` the source of truth.
5. **Single task per service, no autoscaling.** Desired count is 1 for both, so
   any task failure is a full outage and there is no capacity headroom.
6. **`db.t3.micro` with no read replica or Multi-AZ**, acceptable for a demo,
   not for production claim data.
7. **No CI/CD.** Builds and deploys are manual; there is no pipeline in the
   repo.
