# Amazon Rekognition CI/CD Image Labeling Pipeline (Pixel Learning Co.)
<!-- Badges -->
[![Release](https://img.shields.io/badge/release-v1.0.0-brightgreen.svg)](https://github.com/forgisonajeep/rekognition-ci-pipeline/releases/tag/v1.0.0)
![Release](https://img.shields.io/badge/Release-v1.0.0-blue?style=for-the-badge)
[![Amazon Rekognition](https://img.shields.io/badge/Rekognition-Active-brightgreen)]()
[![CI/CD](https://img.shields.io/badge/GitHub%20Actions-CI%2FCD-blue)]()
[![Lambda](https://img.shields.io/badge/Serverless-Lambda%20Event%20Driven-orange)]()
[![DynamoDB TTL](https://img.shields.io/badge/DynamoDB-TTL%20Enabled-purple)]()
  

  

---

<!-- Quick Nav -->
**Jump to:**  
[Project Overview](#project-overview) •
[Architecture Overview](#architecture-overview) •
[Repository Structure](#repository-structure) •
[Prerequisites (GitHub Secrets)](#prerequisites-github-secrets) •
[AWS Resources Setup](#aws-resources-setup) •
[Foundational (CI-based)](#foundational-implementation) •
[Advanced (Event-driven / Serverless)](#advanced-implementation) •
[Security Hardening](#security-hardening) •
[Cost Optimization](#cost-optimization) •
[Troubleshooting](#troubleshooting) •
[What's Next (Complex/IaC)](#next-steps-complex-phase) •
[Closing](#closing) •
[Release Notes](#release-notes)

---
Automated image classification using **Amazon Rekognition** across two stages:
- **Foundational (CI-based):** GitHub Actions runs a Python script that uploads images to S3, calls Rekognition, and (optionally) writes to DynamoDB.
- **Advanced (Event-driven):** S3 uploads trigger **AWS Lambda**, which calls Rekognition and writes structured results (with **TTL**) into **DynamoDB**. Logs are visible in **CloudWatch**.



---

## Project Overview

Pixel Learning Co. wants a **minimal, managed** computer-vision pipeline to auto-label educational images and keep moderation/search consistent. This repo shows how to do that with:
- **Rekognition** (no model training required)
- **S3** (artifact storage / triggers)
- **DynamoDB** (results, per-env, with TTL)
- **GitHub Actions** (automation per branch)
- **Lambda** (event-driven advanced stage)

---

## Architecture Overview



```text
Developer commit / PR
│
├─ Foundational (CI)
│   └─ GitHub Actions → analyze_image.py → S3 → Rekognition (logs only)
│
├─ Release (foundational-1.0)
│   └─ (locked snapshot of CI pipeline before serverless refactor)
│
└─ Advanced (Event-driven / Serverless)
    └─ S3 (rekognition-input/{beta|prod}/...)
        └─ Lambda (lambda_handler.py)
            └─ Rekognition (DetectLabels)
                └─ DynamoDB (TTL set on results)
                    └─ CloudWatch (pretty JSON logs)
```

*Logs (in Foundational) are printed in GitHub Actions console; Advanced logs are persisted as JSON in CloudWatch.*


---

## Repository Structure

    rekognition-ci-pipeline/
    ├─ images/
    │  └─ sneaker.jpeg
    ├─ lambda/
    │  ├─ lambda_handler.py
    │  └─ requirements.txt
    ├─ scripts/
    │  └─ analyze.py
    ├─ .github/workflows/
    │  ├─ on_pull_request.yml  #used in Found & Adv
    │  └─ on_merge.yml         #used in Found & Adv  
    └─ README.md
    
    
---

## Prerequisites (GitHub Secrets)

Add these in **GitHub → Settings → Secrets and variables → Actions**:

| Secret | Example | Notes |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | `AKIA...` | Programmatic credentials for CI |
| `AWS_SECRET_ACCESS_KEY` | `••••` | Keep secret |
| `AWS_REGION` | `us-east-1` | Must match your resources |
| `S3_BUCKET` | `pixel-learning-rekognition-10182025` | Bucket to store inputs |
| `DYNAMODB_TABLE_BETA` | `beta_results` | Foundational/Advanced beta table |
| `DYNAMODB_TABLE_PROD` | `prod_results` | Foundational/Advanced prod table |

> You may also store any additional names as secrets to avoid hardcoding.

---

## AWS Resources Setup

Minimal set (console or CLI):
1) **S3** bucket (e.g., `pixel-learning-rekognition-10182025`) with prefixes:
   - `rekognition-input/beta/`
   - `rekognition-input/prod/`
2) **DynamoDB** table(s):
   - `beta_results`, `prod_results` (PK example: `filename` for demo)
   - Enable **TTL** on attribute `expires_at` (**Number**, epoch seconds)
3) **Lambda** (advanced stage):
   - `rekognition-beta-handler` and `rekognition-prod-handler`
4) **IAM**:
   - Lambda role: S3 `GetObject` on `rekognition-input/*`, Rekognition `DetectLabels`, DynamoDB `PutItem` on the results table(s)
5) **CloudWatch Logs**: enabled by default for Lambda
6) **S3 Event Notifications** (advanced stage):
   - Prefix `rekognition-input/beta/` → `rekognition-beta-handler`
   - Prefix `rekognition-input/prod/` → `rekognition-prod-handler`

---

## Foundational Implementation

Foundational uses **GitHub Actions** to run a **Python script** that uploads the image to S3 and calls Rekognition directly from the runner. Results are printed to the job log and (optionally) written to per-env DynamoDB tables.

### Foundational Script (analyze.py)

    import os, json, boto3
    from datetime import datetime, timezone
    
    def main():
        region = os.environ.get("AWS_REGION", "us-east-1")
        s3_bucket = os.environ["S3_BUCKET"]
        filename = os.environ.get("IMAGE_FILE", "images/sneaker.jpeg")
        branch = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "unknown")
    
        s3 = boto3.client("s3", region_name=region)
        rekog = boto3.client("rekognition", region_name=region)
        ddb = boto3.client("dynamodb", region_name=region)
    
        # Upload to S3 under structured prefix
        key = f"rekognition-input/{os.path.basename(filename)}"
        with open(filename, "rb") as f:
            s3.put_object(Bucket=s3_bucket, Key=key, Body=f, ContentType="image/jpeg")
    
        # Detect labels
        resp = rekog.detect_labels(
            Image={"S3Object": {"Bucket": s3_bucket, "Name": key}},
            MaxLabels=10, MinConfidence=70
        )
    
        labels = [{"Name": l["Name"], "Confidence": round(l["Confidence"], 2)} for l in resp.get("Labels", [])]
        result = {
            "filename": key,
            "labels": labels,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "branch": branch
        }
        print(json.dumps(result, indent=2))
    
        # Optional: write to DynamoDB (table name passed in by workflow per env)
        table = os.environ.get("DDB_TABLE", "")
        if table:
            ddb.put_item(
                TableName=table,
                Item={
                    "filename": {"S": key},
                    "timestamp": {"S": result["timestamp"]},
                    "branch": {"S": branch},
                    "labels": {"S": json.dumps(labels)}
                }
            )
            print(f"Wrote result to DynamoDB table: {table}")
    
    if __name__ == "__main__":
        main()

### Foundational Workflows

**.github/workflows/on_pull_request.yml** (PR → beta)

    name: Foundational - PR (beta)
    on:
      pull_request:
        branches: [ main ]
    
    jobs:
      analyze-beta:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: "3.11"
          - run: pip install boto3
          - name: Analyze image (beta)
            env:
              AWS_ACCESS_KEY_ID:     ${{ secrets.AWS_ACCESS_KEY_ID }}
              AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
              AWS_REGION:            ${{ secrets.AWS_REGION }}
              S3_BUCKET:             ${{ secrets.S3_BUCKET }}
              IMAGE_FILE:            images/sneaker.jpeg
              DDB_TABLE:             ${{ secrets.DYNAMODB_TABLE_BETA }}
            run: python scripts/analyze.py

**.github/workflows/on_merge.yml** (push to main → prod)

    name: Foundational - Merge (prod)
    on:
      push:
        branches: [ main ]
    
    jobs:
      analyze-prod:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: "3.11"
          - run: pip install boto3
          - name: Analyze image (prod)
            env:
              AWS_ACCESS_KEY_ID:     ${{ secrets.AWS_ACCESS_KEY_ID }}
              AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
              AWS_REGION:            ${{ secrets.AWS_REGION }}
              S3_BUCKET:             ${{ secrets.S3_BUCKET }}
              IMAGE_FILE:            images/sneaker.jpeg
              DDB_TABLE:             ${{ secrets.DYNAMODB_TABLE_PROD }}
            run: python scripts/analyze.py

### Manual Validation (Foundational)

- Create a feature branch and commit `images/sneaker.jpeg` → open PR to `main`.
- Confirm **Actions** ran and printed Rekognition labels in the job log.
- Merge to `main` → confirm prod workflow runs.
- (Optional) Query DynamoDB tables to see entries (beta/prod split).

### Foundational Release

Create a release (e.g., **`foundational-1.0`**) to freeze the CI-based approach before refactoring to the advanced event-driven design. Screenshots of Actions success and DynamoDB results can be added here for audit.

---

## Advanced Implementation

In advanced mode, **GitHub Actions no longer calls Rekognition**. Instead, the workflow **only uploads** to S3 under a branch-aware prefix. S3 **triggers Lambda**, which calls Rekognition and writes results to DynamoDB with TTL.

### Lambda Handler (lambda/lambda_handler.py)

    import os, json, time, boto3
    from datetime import datetime, timezone
    
    ddb_table_beta = os.environ.get("DDB_TABLE_BETA", "beta_results")
    ddb_table_prod = os.environ.get("DDB_TABLE_PROD", "prod_results")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    ttl_hours = int(os.environ.get("TTL_HOURS", "168"))  # 7 days default
    
    s3 = boto3.client("s3", region_name=aws_region)
    rekog = boto3.client("rekognition", region_name=aws_region)
    ddb = boto3.client("dynamodb", region_name=aws_region)
    
    def _epoch_in(hours: int) -> int:
        return int(time.time() + hours * 3600)
    
    def handler(event, context):
        # Expect S3 Put event
        rec = event["Records"][0]
        bucket = rec["s3"]["bucket"]["name"]
        key = rec["s3"]["object"]["key"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
        # Decide environment table based on prefix
        if key.startswith("rekognition-input/beta/"):
            table = ddb_table_beta
            branch = "beta"
        elif key.startswith("rekognition-input/prod/"):
            table = ddb_table_prod
            branch = "prod"
        else:
            table = ddb_table_beta
            branch = "beta"
    
        # Call Rekognition
        resp = rekog.detect_labels(
            Image={"S3Object": {"Bucket": bucket, "Name": key}},
            MaxLabels=10, MinConfidence=70
        )
        labels = [{"Name": l["Name"], "Confidence": round(l["Confidence"], 2)} for l in resp.get("Labels", [])]
    
        # TTL
        expires_at = _epoch_in(ttl_hours)
    
        item = {
            "filename": {"S": key},
            "timestamp": {"S": now},
            "branch": {"S": branch},
            "labels": {"S": json.dumps(labels)},
            "expires_at": {"N": str(expires_at)}
        }
        ddb.put_item(TableName=table, Item=item)
    
        log = {
            "filename": key,
            "labels": labels,
            "timestamp": now,
            "branch": branch,
            "table": table,
            "expires_at": expires_at
        }
        print(json.dumps(log, indent=2))
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

### Advanced Workflows

In the Advanced phase, these same workflows are used, but they no longer call Rekognition directly.
They only upload to S3 under rekognition-input/{beta|prod}/…, which triggers Lambda.

**.github/workflows/on_pull_request.yml** (PR → upload only; Lambda does the labeling)

    name: Advanced - PR (beta upload only)
    on:
      pull_request:
        branches: [ main ]
    
    jobs:
      upload-beta:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - name: Install AWS CLI
            run: |
              sudo apt-get update -y
              sudo apt-get install -y awscli
          - name: Upload image to S3 (beta)
            env:
              AWS_ACCESS_KEY_ID:     ${{ secrets.AWS_ACCESS_KEY_ID }}
              AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
              AWS_REGION:            ${{ secrets.AWS_REGION }}
              S3_BUCKET:             ${{ secrets.S3_BUCKET }}
            run: |
              aws s3 cp images/sneaker.jpeg s3://$S3_BUCKET/rekognition-input/beta/sneaker-beta-verify.jpeg --region $AWS_REGION

**.github/workflows/on_merge.yml** (push to main → upload only; Lambda does the labeling)

    name: Advanced - Merge (prod upload only)
    on:
      push:
        branches: [ main ]
    
    jobs:
      upload-prod:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - name: Install AWS CLI
            run: |
              sudo apt-get update -y
              sudo apt-get install -y awscli
          - name: Upload image to S3 (prod)
            env:
              AWS_ACCESS_KEY_ID:     ${{ secrets.AWS_ACCESS_KEY_ID }}
              AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
              AWS_REGION:            ${{ secrets.AWS_REGION }}
              S3_BUCKET:             ${{ secrets.S3_BUCKET }}
            run: |
              aws s3 cp images/sneaker.jpeg s3://$S3_BUCKET/rekognition-input/prod/sneaker-prod-verify.jpeg --region $AWS_REGION

Note: In Advanced, Rekognition is not called in GitHub Actions. The S3 put triggers your Lambda (rekognition-beta-handler / rekognition-prod-handler), which calls Rekognition and writes to DynamoDB (with TTL).


### S3 Event Triggers

- **rekognition-input/beta/** → `rekognition-beta-handler`
- **rekognition-input/prod/** → `rekognition-prod-handler`

> The workflows **do not call Rekognition** in Advanced. They only upload to S3; Lambda handles the rest.

### TTL & DynamoDB Retention

- DynamoDB **TTL attribute**: `expires_at` (Number, epoch seconds)
- In the Lambda handler, TTL is computed as `now + (TTL_HOURS * 3600)`. Default is **168 hours (7 days)** via `TTL_HOURS` env var.

### Advanced Validation (Proof)

- Uploaded `sneaker-prod-test2.jpeg` to `rekognition-input/prod/…`
- Triggered Lambda: **rekognition-prod-handler**
- **CloudWatch** log stream contained pretty JSON with labels + timestamp
- **DynamoDB** `prod_results` item written (`filename`, `labels[]`, `timestamp`, `branch`, `expires_at`)

---

## Security Hardening

- **Least-privilege IAM**:
  - Lambda role: only S3 `GetObject` on `rekognition-input/*`, Rekognition `DetectLabels`, DynamoDB `PutItem` on result tables, CloudWatch logging.
- **No credentials in code**: always use **GitHub Actions Secrets** / Lambda env vars.
- **Private S3 buckets** by default; share artifacts via **presigned URLs**.
- **Separate beta/prod** write paths and tables to avoid cross-contamination.

### Security Posture

This repository enforces a hardened security model built around CI/CD safety controls:

- IAM access is scoped using **principle of least privilege**
- All AWS credentials are stored in **GitHub Actions Secrets**
- In advanced mode, **Rekognition is triggered by S3 events**, not directly from CI
- S3 remains **private by default** (no public object ACLs)
- DynamoDB **TTL is enabled** to automatically expire stale inference logs
- Formal release (`v1.0.0`) is **immutable** for reproducibility
- `main` is protected with **required PR review + passing checks**
- When sharing artifacts externally, only **pre-signed URLs** are used(iths a real change)



---

## Cost Optimization

- Rekognition: bound **MaxLabels** and **MinConfidence** to reduce noise.
- TTL on DynamoDB keeps storage lean (auto expiry).
- Use small test images for CI.
- CloudWatch retention policy (e.g., 7–14 days) to control log costs.

---

## Troubleshooting

- **Workflow didn’t run**: confirm the correct trigger (`pull_request` vs `push` to `main`).
- **AccessDenied**: verify IAM role permissions and S3 bucket ARN paths.
- **DynamoDB item missing** (Advanced): confirm S3 prefix matches the configured Lambda trigger (`beta/` or `prod/`).
- **No logs**: check CloudWatch Logs for the Lambda function in the right region.

---

## What’s Next (Complex / IaC)

- **Infrastructure as Code** (CloudFormation or Terraform) for:
  - S3 bucket + policies scoped to `rekognition-input/*`
  - DynamoDB tables (+ TTL)
  - Lambda functions + IAM roles
  - S3 event notifications
- CI: Deploy infra on PR to **beta** stack; promote on **main** merges.

---

## Closing

This repo demonstrates a clean path from **Foundational (CI)** to **Advanced (event-driven)** for AI-powered image labeling with Rekognition.  
Use the Foundational release (**`foundational-1.0`**) as a proof checkpoint, then continue with the Advanced pipeline for hands-off operations.

---

## Release Notes
**[v1.0.0](https://github.com/forgisonajeep/rekognition-ci-pipeline/releases/tag/v1.0.0)** — Foundational pipeline + Advanced event-driven Lambda live
THIS SHOULD FAIL
THIS SHOULD FAIL
