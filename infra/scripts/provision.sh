#!/usr/bin/env bash
#
# Provision the ClaimLens AWS infrastructure from scratch.
#
# Reconstructed from CloudTrail records of the original (manual) deployment, so
# the resource shapes match what is actually running — see docs/DEPLOYMENT.md.
#
# This script is IDEMPOTENT-ISH, not a replacement for real IaC: it creates
# resources if missing and reuses them if present, but it does not reconcile
# drift or delete anything. For a proper source of truth, import these
# resources into Terraform (see infra/README.md).
#
# Usage:
#   ./infra/scripts/provision.sh            # show what it would do
#   APPLY=1 ./infra/scripts/provision.sh    # actually create resources
#
# Prerequisites:
#   - AWS CLI v2 configured with credentials for the target account
#   - A VPC with at least two subnets in different AZs
#   - OPENAI_API_KEY and DB_PASSWORD exported (used to seed Secrets Manager)
#
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
REGION="${AWS_REGION:-us-east-1}"
CLUSTER="${ECS_CLUSTER:-default}"
PROJECT="claimlens"

DB_NAME="claimlens"
DB_USER="claimlens"
DB_INSTANCE_CLASS="db.t3.micro"
DB_STORAGE_GB=20
DB_ENGINE_VERSION="16"

BACKEND_PORT=8000
FRONTEND_PORT=8080
BACKEND_CPU=2048
BACKEND_MEMORY=4096
FRONTEND_CPU=256
FRONTEND_MEMORY=512

APPLY="${APPLY:-0}"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ECR_HOST="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
UPLOADS_BUCKET="${PROJECT}-uploads-${ACCOUNT}"

# ── Helpers ───────────────────────────────────────────────────────────────────
# Diagnostics go to stderr so helper functions can return values on stdout via
# command substitution without the log lines being captured too.
log()  { printf '\n\033[1m==> %s\033[0m\n' "$*" >&2; }
info() { printf '    %s\n' "$*" >&2; }

# Run a mutating command only when APPLY=1.
run() {
  if [[ "$APPLY" == "1" ]]; then
    "$@"
  else
    printf '    [dry-run] %s\n' "$*" >&2
  fi
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: $name must be set (needed to seed Secrets Manager)." >&2
    exit 1
  fi
}

# ── Preflight ─────────────────────────────────────────────────────────────────
log "Target"
info "account : $ACCOUNT"
info "region  : $REGION"
info "cluster : $CLUSTER"
info "apply   : $APPLY  (set APPLY=1 to make changes)"

if [[ "$APPLY" == "1" ]]; then
  require_env OPENAI_API_KEY
  require_env DB_PASSWORD
fi

# VPC + subnets: default to the account's default VPC unless overridden.
VPC_ID="${VPC_ID:-$(aws ec2 describe-vpcs --region "$REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)}"

if [[ -z "$VPC_ID" || "$VPC_ID" == "None" ]]; then
  echo "ERROR: no VPC found. Set VPC_ID explicitly." >&2
  exit 1
fi

# Read "<az> <subnet-id>" pairs. Avoids `mapfile`, which macOS bash 3.2 lacks.
ALL_SUBNETS=()
AZ_SEEN=""
AZ_SUBNETS=()
while IFS=$'\t' read -r _az _subnet; do
  [[ -n "$_subnet" ]] || continue
  ALL_SUBNETS+=("$_subnet")
  # Keep the first subnet found in each AZ — an ALB needs two distinct AZs.
  case " $AZ_SEEN " in
    *" $_az "*) ;;
    *) AZ_SEEN="$AZ_SEEN $_az"; AZ_SUBNETS+=("$_subnet") ;;
  esac
done < <(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[].[AvailabilityZone,SubnetId]' --output text)

if (( ${#ALL_SUBNETS[@]} < 2 )); then
  echo "ERROR: need at least 2 subnets in $VPC_ID, found ${#ALL_SUBNETS[@]}." >&2
  exit 1
fi
if (( ${#AZ_SUBNETS[@]} < 2 )); then
  echo "ERROR: need subnets in at least 2 availability zones for an ALB." >&2
  exit 1
fi

# ALB and tasks use one subnet per AZ; RDS gets the full set for its subnet group.
# Override with SUBNET_A / SUBNET_B to pin specific subnets.
SUBNET_A="${SUBNET_A:-${AZ_SUBNETS[0]}}"
SUBNET_B="${SUBNET_B:-${AZ_SUBNETS[1]}}"

log "Network"
info "vpc     : $VPC_ID"
info "subnets : $SUBNET_A, $SUBNET_B  (RDS group uses all ${#ALL_SUBNETS[@]})"

# ── 1. ECR repositories ───────────────────────────────────────────────────────
log "1. ECR repositories"
for repo in "${PROJECT}-backend" "${PROJECT}-frontend"; do
  if aws ecr describe-repositories --region "$REGION" --repository-names "$repo" >/dev/null 2>&1; then
    info "exists: $repo"
  else
    info "create: $repo"
    run aws ecr create-repository --region "$REGION" --repository-name "$repo"
  fi
done

# ── 2. S3 uploads bucket ──────────────────────────────────────────────────────
log "2. S3 uploads bucket"
if aws s3api head-bucket --bucket "$UPLOADS_BUCKET" >/dev/null 2>&1; then
  info "exists: $UPLOADS_BUCKET"
else
  info "create: $UPLOADS_BUCKET"
  # us-east-1 rejects LocationConstraint; every other region requires it.
  if [[ "$REGION" == "us-east-1" ]]; then
    run aws s3api create-bucket --bucket "$UPLOADS_BUCKET" --region "$REGION"
  else
    run aws s3api create-bucket --bucket "$UPLOADS_BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION"
  fi
  run aws s3api put-public-access-block --bucket "$UPLOADS_BUCKET" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
fi

# ── 3. Security groups ────────────────────────────────────────────────────────
# Layering: internet -> ALB only; ALB -> tasks only; backend task -> RDS only.
log "3. Security groups"

sg_id() {
  aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=$1" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null
}

ensure_sg() {
  local name="$1" desc="$2" existing
  existing="$(sg_id "$name")"
  if [[ -n "$existing" && "$existing" != "None" ]]; then
    info "exists: $name ($existing)"
    echo "$existing"
    return
  fi
  info "create: $name"
  if [[ "$APPLY" == "1" ]]; then
    aws ec2 create-security-group --region "$REGION" --vpc-id "$VPC_ID" \
      --group-name "$name" --description "$desc" \
      --query GroupId --output text
  else
    echo "sg-DRYRUN-${name}"
  fi
}

ALB_SG="$(ensure_sg "${PROJECT}-alb-sg"           "ClaimLens ALB")"
BACKEND_SG="$(ensure_sg "${PROJECT}-backend-task-sg"  "ClaimLens backend Fargate tasks")"
FRONTEND_SG="$(ensure_sg "${PROJECT}-frontend-task-sg" "ClaimLens frontend Fargate tasks")"
RDS_SG="$(ensure_sg "${PROJECT}-rds-sg"           "ClaimLens RDS Postgres")"

# Ingress rules. Duplicates fail harmlessly, so errors are tolerated here.
log "3b. Security group ingress"
info "ALB      :80   <- 0.0.0.0/0"
run aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$ALB_SG" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0 || true

info "backend  :$BACKEND_PORT <- ALB SG"
run aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$BACKEND_SG" \
  --protocol tcp --port "$BACKEND_PORT" --source-group "$ALB_SG" || true

info "frontend :$FRONTEND_PORT <- ALB SG"
run aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$FRONTEND_SG" \
  --protocol tcp --port "$FRONTEND_PORT" --source-group "$ALB_SG" || true

info "rds      :5432 <- backend SG"
run aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$RDS_SG" \
  --protocol tcp --port 5432 --source-group "$BACKEND_SG" || true

# ── 4. RDS Postgres ───────────────────────────────────────────────────────────
log "4. RDS Postgres"
if aws rds describe-db-subnet-groups --region "$REGION" \
     --db-subnet-group-name "${PROJECT}-db-subnets" >/dev/null 2>&1; then
  info "exists: subnet group ${PROJECT}-db-subnets"
else
  info "create: subnet group ${PROJECT}-db-subnets"
  run aws rds create-db-subnet-group --region "$REGION" \
    --db-subnet-group-name "${PROJECT}-db-subnets" \
    --db-subnet-group-description "ClaimLens RDS subnets" \
    --subnet-ids "${ALL_SUBNETS[@]}"
fi

if aws rds describe-db-instances --region "$REGION" \
     --db-instance-identifier "${PROJECT}-db" >/dev/null 2>&1; then
  info "exists: ${PROJECT}-db"
else
  info "create: ${PROJECT}-db ($DB_INSTANCE_CLASS, postgres $DB_ENGINE_VERSION, ${DB_STORAGE_GB}GB gp3)"
  run aws rds create-db-instance --region "$REGION" \
    --db-instance-identifier "${PROJECT}-db" \
    --db-name "$DB_NAME" \
    --master-username "$DB_USER" \
    --master-user-password "${DB_PASSWORD:-DRYRUN}" \
    --db-instance-class "$DB_INSTANCE_CLASS" \
    --engine postgres --engine-version "$DB_ENGINE_VERSION" \
    --allocated-storage "$DB_STORAGE_GB" --storage-type gp3 \
    --db-subnet-group-name "${PROJECT}-db-subnets" \
    --vpc-security-group-ids "$RDS_SG" \
    --backup-retention-period 1 \
    --no-multi-az --no-publicly-accessible
  info "waiting for the instance to become available (several minutes)..."
  run aws rds wait db-instance-available --region "$REGION" \
    --db-instance-identifier "${PROJECT}-db"
fi

DB_HOST="$(aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "${PROJECT}-db" \
  --query 'DBInstances[0].Endpoint.Address' --output text 2>/dev/null || echo "DRYRUN-db-endpoint")"
info "endpoint: $DB_HOST"

# ── 5. Secrets Manager ────────────────────────────────────────────────────────
log "5. Secrets Manager"
ensure_secret() {
  local name="$1" value="$2"
  if aws secretsmanager describe-secret --region "$REGION" --secret-id "$name" >/dev/null 2>&1; then
    info "exists: $name (leaving value untouched)"
  else
    info "create: $name"
    run aws secretsmanager create-secret --region "$REGION" \
      --name "$name" --secret-string "$value"
  fi
}

ensure_secret "${PROJECT}/openai-api-key" "${OPENAI_API_KEY:-DRYRUN}"
ensure_secret "${PROJECT}/database-url" \
  "postgresql://${DB_USER}:${DB_PASSWORD:-DRYRUN}@${DB_HOST}:5432/${DB_NAME}"

OPENAI_SECRET_ARN="$(aws secretsmanager describe-secret --region "$REGION" \
  --secret-id "${PROJECT}/openai-api-key" --query ARN --output text 2>/dev/null || echo "DRYRUN")"
DBURL_SECRET_ARN="$(aws secretsmanager describe-secret --region "$REGION" \
  --secret-id "${PROJECT}/database-url" --query ARN --output text 2>/dev/null || echo "DRYRUN")"

# ── 6. IAM roles ──────────────────────────────────────────────────────────────
log "6. IAM roles"
ECS_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

# Execution role: ECS itself uses this to pull images, write logs, read secrets.
if aws iam get-role --role-name ClaimLensECSExecutionRole >/dev/null 2>&1; then
  info "exists: ClaimLensECSExecutionRole"
else
  info "create: ClaimLensECSExecutionRole"
  run aws iam create-role --role-name ClaimLensECSExecutionRole \
    --assume-role-policy-document "$ECS_TRUST"
  run aws iam attach-role-policy --role-name ClaimLensECSExecutionRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
fi

info "update: ClaimLensECSExecutionRole inline policy ClaimLensReadSecrets"
READ_SECRETS=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{
  "Sid":"ReadClaimLensSecrets","Effect":"Allow","Action":"secretsmanager:GetSecretValue",
  "Resource":["arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:${PROJECT}/openai-api-key-*",
              "arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:${PROJECT}/database-url-*"]}]}
JSON
)
run aws iam put-role-policy --role-name ClaimLensECSExecutionRole \
  --policy-name ClaimLensReadSecrets --policy-document "$READ_SECRETS"

# Task role: the application's own AWS access (S3 uploads, optional Bedrock).
if aws iam get-role --role-name ClaimLensBackendInstanceRole >/dev/null 2>&1; then
  info "exists: ClaimLensBackendInstanceRole"
else
  info "create: ClaimLensBackendInstanceRole"
  run aws iam create-role --role-name ClaimLensBackendInstanceRole \
    --assume-role-policy-document "$ECS_TRUST"
fi

info "update: ClaimLensBackendInstanceRole inline policy ClaimLensBackendPerms"
BACKEND_PERMS=$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Sid":"Bedrock","Effect":"Allow",
  "Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],"Resource":"*"},
 {"Sid":"S3","Effect":"Allow",
  "Action":["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
  "Resource":["arn:aws:s3:::${PROJECT}-*","arn:aws:s3:::${PROJECT}-*/*"]}]}
JSON
)
run aws iam put-role-policy --role-name ClaimLensBackendInstanceRole \
  --policy-name ClaimLensBackendPerms --policy-document "$BACKEND_PERMS"

# ── 7. CloudWatch log groups ──────────────────────────────────────────────────
log "7. CloudWatch log groups"
for lg in "/ecs/${PROJECT}-backend" "/ecs/${PROJECT}-frontend"; do
  if aws logs describe-log-groups --region "$REGION" --log-group-name-prefix "$lg" \
       --query 'logGroups[0].logGroupName' --output text 2>/dev/null | grep -qx "$lg"; then
    info "exists: $lg"
  else
    info "create: $lg"
    run aws logs create-log-group --region "$REGION" --log-group-name "$lg"
  fi
done

# ── 8. ALB, target groups, listener ───────────────────────────────────────────
log "8. Load balancer"
if aws elbv2 describe-load-balancers --region "$REGION" --names "${PROJECT}-alb" >/dev/null 2>&1; then
  info "exists: ${PROJECT}-alb"
else
  info "create: ${PROJECT}-alb (internet-facing)"
  run aws elbv2 create-load-balancer --region "$REGION" --name "${PROJECT}-alb" \
    --type application --scheme internet-facing \
    --subnets "$SUBNET_A" "$SUBNET_B" --security-groups "$ALB_SG"
  run aws elbv2 wait load-balancer-available --region "$REGION" --names "${PROJECT}-alb"
fi

ALB_ARN="$(aws elbv2 describe-load-balancers --region "$REGION" --names "${PROJECT}-alb" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "DRYRUN")"
ALB_DNS="$(aws elbv2 describe-load-balancers --region "$REGION" --names "${PROJECT}-alb" \
  --query 'LoadBalancers[0].DNSName' --output text 2>/dev/null || echo "DRYRUN")"

ensure_tg() {
  local name="$1" port="$2" health="$3"
  if aws elbv2 describe-target-groups --region "$REGION" --names "$name" >/dev/null 2>&1; then
    info "exists: $name"
  else
    info "create: $name (HTTP:$port, health $health)"
    run aws elbv2 create-target-group --region "$REGION" --name "$name" \
      --protocol HTTP --port "$port" --vpc-id "$VPC_ID" --target-type ip \
      --health-check-path "$health" \
      --health-check-interval-seconds 30 --health-check-timeout-seconds 10 \
      --healthy-threshold-count 2 --unhealthy-threshold-count 5
  fi
  aws elbv2 describe-target-groups --region "$REGION" --names "$name" \
    --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || echo "DRYRUN-$name"
}

log "8b. Target groups"
BACKEND_TG="$(ensure_tg "${PROJECT}-backend-tg"  "$BACKEND_PORT"  /health)"
FRONTEND_TG="$(ensure_tg "${PROJECT}-frontend-tg" "$FRONTEND_PORT" /)"

log "8c. Listener and routing"
LISTENER_ARN="$(aws elbv2 describe-listeners --region "$REGION" --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text 2>/dev/null || echo "None")"

if [[ -n "$LISTENER_ARN" && "$LISTENER_ARN" != "None" ]]; then
  info "exists: HTTP:80 listener"
else
  info "create: HTTP:80 listener -> frontend (default)"
  run aws elbv2 create-listener --region "$REGION" --load-balancer-arn "$ALB_ARN" \
    --protocol HTTP --port 80 \
    --default-actions "Type=forward,TargetGroupArn=$FRONTEND_TG"
  LISTENER_ARN="$(aws elbv2 describe-listeners --region "$REGION" --load-balancer-arn "$ALB_ARN" \
    --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text 2>/dev/null || echo "DRYRUN")"
fi

# Rule 10 sends API and upload traffic to the backend; everything else falls
# through to the frontend default action.
EXISTING_RULE="$(aws elbv2 describe-rules --region "$REGION" --listener-arn "$LISTENER_ARN" \
  --query "Rules[?Priority=='10'].RuleArn | [0]" --output text 2>/dev/null || echo "None")"

if [[ -n "$EXISTING_RULE" && "$EXISTING_RULE" != "None" ]]; then
  info "exists: rule priority 10 (/api/*, /uploads/*)"
else
  info "create: rule priority 10 -> backend for /api/*, /uploads/*"
  run aws elbv2 create-rule --region "$REGION" --listener-arn "$LISTENER_ARN" --priority 10 \
    --conditions 'Field=path-pattern,Values=/api/*,/uploads/*' \
    --actions "Type=forward,TargetGroupArn=$BACKEND_TG"
fi

# ── 9. Task definitions ───────────────────────────────────────────────────────
# Rendered from infra/ecs/*.json so the committed definitions stay the source of
# truth; only account/region/ARN-specific values are substituted.
log "9. ECS task definitions"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

register_taskdef() {
  local family="$1" src="$REPO_ROOT/infra/ecs/$1.json" tmp
  if [[ ! -f "$src" ]]; then
    info "SKIP $family (missing $src)"
    return
  fi
  tmp="$(mktemp)"

  # Fill the template's placeholders with this account's real values. Passing
  # them explicitly avoids re-querying AWS for what we already resolved above.
  if ! ACCOUNT_ID="$ACCOUNT" REGION="$REGION" S3_BUCKET="$UPLOADS_BUCKET" \
       ALB_DNS="$ALB_DNS" OPENAI_SECRET_ARN="$OPENAI_SECRET_ARN" \
       DATABASE_URL_SECRET_ARN="$DBURL_SECRET_ARN" \
       python3 "$REPO_ROOT/infra/scripts/render_taskdef.py" "$src" > "$tmp"; then
    echo "ERROR: failed to render $family task definition." >&2
    exit 1
  fi

  info "register: $family"
  run aws ecs register-task-definition --region "$REGION" --cli-input-json "file://$tmp"
  [[ "$APPLY" == "1" ]] || info "[dry-run] rendered definition at $tmp"
}

register_taskdef "${PROJECT}-backend"
register_taskdef "${PROJECT}-frontend"

# ── 10. ECS services ──────────────────────────────────────────────────────────
log "10. ECS services"
ensure_service() {
  local name="$1" tg="$2" port="$3" sg="$4" grace="$5" existing
  existing="$(aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" \
    --services "$name" --query 'services[?status==`ACTIVE`].serviceName' --output text 2>/dev/null || true)"
  if [[ -n "$existing" ]]; then
    info "exists: $name (use update-service to change it)"
    return
  fi
  info "create: $name (Fargate, desired 1)"
  run aws ecs create-service --region "$REGION" --cluster "$CLUSTER" \
    --service-name "$name" --task-definition "$name" \
    --desired-count 1 --launch-type FARGATE \
    --load-balancers "targetGroupArn=$tg,containerName=Main,containerPort=$port" \
    --network-configuration \
      "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$sg],assignPublicIp=ENABLED}" \
    --health-check-grace-period-seconds "$grace"
}

ensure_service "${PROJECT}-backend"  "$BACKEND_TG"  "$BACKEND_PORT"  "$BACKEND_SG"  180
ensure_service "${PROJECT}-frontend" "$FRONTEND_TG" "$FRONTEND_PORT" "$FRONTEND_SG" 60

# ── Done ──────────────────────────────────────────────────────────────────────
log "Done"
if [[ "$APPLY" == "1" ]]; then
  info "URL: http://${ALB_DNS}"
  info ""
  info "Remaining manual steps:"
  info "  1. Build and push images (see docs/DEPLOYMENT.md), then:"
  info "     aws ecs update-service --cluster $CLUSTER --service ${PROJECT}-backend  --force-new-deployment"
  info "     aws ecs update-service --cluster $CLUSTER --service ${PROJECT}-frontend --force-new-deployment"
  info "  2. Run Alembic migrations against RDS (not automated)."
else
  info "Dry run only — nothing was created. Re-run with APPLY=1 to apply."
fi
