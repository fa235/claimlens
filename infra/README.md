# infra/

Infrastructure configuration for the AWS deployment. Full architecture and
redeploy steps are in [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).

```
infra/
├── ecs/
│   ├── claimlens-backend.json    task-definition template (backend)
│   └── claimlens-frontend.json   task-definition template (frontend)
└── scripts/
    ├── provision.sh              creates the whole stack from scratch
    └── render_taskdef.py         fills template placeholders for your account
```

## ecs/ — task-definition templates

These were exported from the live ECS services, so the CPU/memory, ports, env
vars, and log config match what actually runs. Account-specific values are
replaced with placeholders so the templates work in any account:

| Placeholder | Resolved from |
|---|---|
| `{{ACCOUNT_ID}}` | `sts get-caller-identity` |
| `{{REGION}}` | `$AWS_REGION`, else the CLI's configured region |
| `{{S3_BUCKET}}` | `claimlens-uploads-<account-id>` |
| `{{ALB_DNS}}` | the `claimlens-alb` load balancer's DNS name |
| `{{OPENAI_SECRET_ARN}}` / `{{DATABASE_URL_SECRET_ARN}}` | Secrets Manager, by secret name |

Because of the placeholders they **cannot be registered directly**. Render
first:

```bash
python3 infra/scripts/render_taskdef.py infra/ecs/claimlens-backend.json > /tmp/td.json
aws ecs register-task-definition --cli-input-json file:///tmp/td.json
aws ecs update-service --cluster default --service claimlens-backend \
  --task-definition claimlens-backend
```

Any placeholder can be overridden by an environment variable of the same name,
so the renderer also works with no AWS access:

```bash
ACCOUNT_ID=111122223333 REGION=eu-west-1 \
  python3 infra/scripts/render_taskdef.py infra/ecs/claimlens-frontend.json
```

## scripts/provision.sh — rebuild the stack

Creates every resource the deployment needs: ECR repos, S3 uploads bucket,
security groups, RDS Postgres, Secrets Manager entries, IAM roles, CloudWatch
log groups, the ALB with its target groups and routing rules, the task
definitions, and the two ECS services.

The resource shapes were **reconstructed from CloudTrail** records of the
original manual deployment, so they match production rather than being guesses.

```bash
# Preview — makes no changes
./infra/scripts/provision.sh

# Apply (secrets are only needed on a fresh account)
APPLY=1 OPENAI_API_KEY=sk-... DB_PASSWORD=... ./infra/scripts/provision.sh
```

It skips anything that already exists, so running it against the current
account reports everything as `exists` and changes nothing. Useful knobs:
`AWS_REGION`, `VPC_ID`, `SUBNET_A`/`SUBNET_B`, `ECS_CLUSTER`.

### Limits

It creates resources and reuses existing ones, but it does **not** reconcile
drift, update a resource whose settings changed, or delete anything. If you edit
a security group by hand, the script won't notice. That's the fundamental
difference between a provisioning script and real IaC — for a true source of
truth, import these resources into Terraform.

Two steps remain manual by design: building/pushing the container images, and
running Alembic migrations against RDS. Both are in
[`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).

## Secrets

The task definitions reference AWS Secrets Manager **ARNs only**; no secret
values are stored in this repo:

| Secret | Injected as |
|---|---|
| `claimlens/openai-api-key` | `OPENAI_API_KEY` |
| `claimlens/database-url` | `DATABASE_URL` |
