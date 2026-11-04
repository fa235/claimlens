# SageMaker Setup Guide

One-time AWS setup before you can run training jobs.
Takes about 15 minutes.

---

## Step 1 — Create an S3 bucket

```bash
aws s3 mb s3://claimlens-training --region us-east-1
```

Replace `claimlens-training` with your preferred bucket name.
Note it down — you'll use it as `S3_BUCKET`.

---

## Step 2 — Create the SageMaker IAM role

### 2a. Create the role

```bash
aws iam create-role \
  --role-name ClaimLensSageMakerRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "sagemaker.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'
```

### 2b. Attach the managed SageMaker policy

```bash
aws iam attach-role-policy \
  --role-name ClaimLensSageMakerRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess
```

### 2c. Attach the custom S3 + logging policy

Edit `iam_policy.json` — replace `YOUR-CLAIMLENS-BUCKET` with your actual bucket name, then:

```bash
aws iam put-role-policy \
  --role-name ClaimLensSageMakerRole \
  --policy-name ClaimLensS3Access \
  --policy-document file://sagemaker/iam_policy.json
```

### 2d. Get the role ARN

```bash
aws iam get-role --role-name ClaimLensSageMakerRole \
  --query 'Role.Arn' --output text
```

Save this — it looks like:
`arn:aws:iam::123456789012:role/ClaimLensSageMakerRole`

---

## Step 3 — Create sagemaker/.env

```bash
cp sagemaker/.env.example sagemaker/.env
```

Edit `sagemaker/.env`:

```env
AWS_REGION=us-east-1
S3_BUCKET=claimlens-training
SAGEMAKER_ROLE_ARN=arn:aws:iam::123456789012:role/ClaimLensSageMakerRole
S3_DATA_PREFIX=claimlens/training-data
```

---

## Step 4 — Install launcher dependencies

```bash
pip install -r sagemaker/requirements_launcher.txt
```

---

## You're ready. Now follow the SageMaker workflow in README.md.
