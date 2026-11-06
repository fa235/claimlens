#!/usr/bin/env python3
"""
Render an ECS task-definition template into a concrete definition for *your*
AWS account.

The templates in infra/ecs/ are deliberately account-neutral: they use
placeholders instead of a hard-coded account ID, region, bucket, or ARNs. This
script fills them in by querying the account you are currently authenticated
against, so the same template works for anyone.

Usage
-----
    # Print a ready-to-register definition
    python3 infra/scripts/render_taskdef.py infra/ecs/claimlens-backend.json

    # Register it
    python3 infra/scripts/render_taskdef.py infra/ecs/claimlens-backend.json > /tmp/td.json
    aws ecs register-task-definition --cli-input-json file:///tmp/td.json

Placeholders
------------
    {{ACCOUNT_ID}}      resolved via sts get-caller-identity
    {{REGION}}          $AWS_REGION, else the configured CLI region, else us-east-1
    {{S3_BUCKET}}       $S3_BUCKET, else claimlens-uploads-<account>
    {{ALB_DNS}}         $ALB_DNS, else looked up from the claimlens-alb load balancer
    {{OPENAI_SECRET_ARN}}   $OPENAI_SECRET_ARN, else looked up by secret name
    {{DATABASE_URL_SECRET_ARN}} likewise

Every placeholder can be overridden with the matching environment variable, so
the script also works offline / in CI without AWS access:

    ACCOUNT_ID=111122223333 REGION=eu-west-1 S3_BUCKET=my-bucket \
    ALB_DNS=my-alb.example.com OPENAI_SECRET_ARN=arn:... \
    DATABASE_URL_SECRET_ARN=arn:... \
    python3 infra/scripts/render_taskdef.py infra/ecs/claimlens-backend.json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PROJECT = "claimlens"


def aws(*args: str) -> str | None:
    """Run an AWS CLI command, returning stripped stdout or None on failure."""
    try:
        out = subprocess.run(
            ["aws", *args],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return out if out and out != "None" else None


def resolve_region() -> str:
    return (
        os.environ.get("REGION")
        or os.environ.get("AWS_REGION")
        or aws("configure", "get", "region")
        or "us-east-1"
    )


def resolve_account(region: str) -> str:
    acct = os.environ.get("ACCOUNT_ID")
    if acct:
        return acct
    acct = aws("sts", "get-caller-identity", "--query", "Account", "--output", "text")
    if not acct:
        sys.exit(
            "ERROR: could not determine the AWS account ID.\n"
            "Configure the AWS CLI, or pass ACCOUNT_ID=... explicitly."
        )
    return acct


def resolve_alb_dns(region: str) -> str:
    dns = os.environ.get("ALB_DNS")
    if dns:
        return dns
    dns = aws(
        "elbv2", "describe-load-balancers", "--region", region,
        "--names", f"{PROJECT}-alb",
        "--query", "LoadBalancers[0].DNSName", "--output", "text",
    )
    if dns:
        return dns
    # The ALB may not exist yet (first provision). CORS can be corrected later.
    print(
        f"WARNING: load balancer '{PROJECT}-alb' not found; "
        "CORS_ORIGINS will be left as a placeholder host.",
        file=sys.stderr,
    )
    return "ALB-NOT-YET-CREATED"


def resolve_secret_arn(region: str, env_var: str, secret_name: str) -> str:
    arn = os.environ.get(env_var)
    if arn:
        return arn
    arn = aws(
        "secretsmanager", "describe-secret", "--region", region,
        "--secret-id", secret_name, "--query", "ARN", "--output", "text",
    )
    if arn:
        return arn
    sys.exit(
        f"ERROR: secret '{secret_name}' not found in {region}.\n"
        f"Create it first (infra/scripts/provision.sh does this), "
        f"or pass {env_var}=arn:... explicitly."
    )


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {os.path.basename(sys.argv[0])} <task-definition-template.json>")

    path = sys.argv[1]
    try:
        raw = open(path).read()
    except OSError as exc:
        sys.exit(f"ERROR: cannot read {path}: {exc}")

    region = resolve_region()
    account = resolve_account(region)

    values = {
        "ACCOUNT_ID": account,
        "REGION": region,
        "S3_BUCKET": os.environ.get("S3_BUCKET") or f"{PROJECT}-uploads-{account}",
    }

    # Only resolve the expensive lookups if the template actually uses them.
    if "{{ALB_DNS}}" in raw:
        values["ALB_DNS"] = resolve_alb_dns(region)
    if "{{OPENAI_SECRET_ARN}}" in raw:
        values["OPENAI_SECRET_ARN"] = resolve_secret_arn(
            region, "OPENAI_SECRET_ARN", f"{PROJECT}/openai-api-key"
        )
    if "{{DATABASE_URL_SECRET_ARN}}" in raw:
        values["DATABASE_URL_SECRET_ARN"] = resolve_secret_arn(
            region, "DATABASE_URL_SECRET_ARN", f"{PROJECT}/database-url"
        )

    for key, val in values.items():
        raw = raw.replace("{{" + key + "}}", val)

    leftover = re.findall(r"\{\{([A-Z_]+)\}\}", raw)
    if leftover:
        sys.exit(f"ERROR: unresolved placeholders remain: {sorted(set(leftover))}")

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: rendered output is not valid JSON: {exc}")

    # register-task-definition rejects explicit nulls (e.g. an unused taskRoleArn).
    doc = {k: v for k, v in doc.items() if v is not None}

    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
