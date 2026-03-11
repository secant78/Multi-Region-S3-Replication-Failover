# Assignment 9: Multi-Region S3 Replication with Failover

Active-passive S3 Cross-Region Replication (CRR) setup with automatic failover testing between **us-east-1** (primary) and **eu-west-1** (replica).

## Architecture

```
PRIMARY (us-east-1)                       REPLICA (eu-west-1)
s3-primary-sean-0303                      s3-replica-sean-0303
  ├── Rule 1: critical/ prefix  ────CRR──►  (delete markers replicated)
  └── Rule 2: tag replicate=true ───CRR──►  (object versions replicated)

CloudWatch Alarms:
  S3ReplicationLag-sean-0303          → triggers if lag > 15 min
  S3ReplicationLag-sean-0303-failures → triggers on any replication failure
```

## CI/CD Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `1 - Deploy Infrastructure` | Push to `main` / manual | Creates buckets, IAM role, CRR rules, CloudWatch alarms |
| `2 - Replication Tests` | After workflow 1 / daily 06:00 UTC | Uploads 20 files, delete marker test, 500 MB lag test |
| `3 - Failover Simulation & RTO Report` | After workflow 2 / weekly Sunday 08:00 UTC | Simulates primary failure, measures RTO, generates lab report |
| `4 - Lint & Validate` | Every push / PR | Flake8 linting, config validation, YAML syntax check |

## Authentication: OIDC Federated Identity (No Long-Lived Secrets)

This project uses **OpenID Connect (OIDC)** to authenticate GitHub Actions to AWS.
**No IAM access keys or repository secrets are required.**

### How It Works

```
GitHub Actions Runner
  │
  ├─ GitHub generates a short-lived OIDC JWT (valid ~5 min)
  │  signed by token.actions.githubusercontent.com
  │
  └─► aws-actions/configure-aws-credentials
        │
        └─► sts:AssumeRoleWithWebIdentity
              │  validates: aud == sts.amazonaws.com
              │  validates: sub matches repo + branch condition
              │
              └─► Temporary credentials (1-hour TTL, auto-expire)
                    └─► S3, IAM, CloudWatch API calls
```

### One-Time Setup (run locally with IAM admin access)

```bash
pip install boto3
python setup_oidc_role.py
```

This creates:
- **IAM OIDC Identity Provider** for `token.actions.githubusercontent.com`
- **IAM Role** `github-actions-oidc-role`
  ARN: `arn:aws:iam::866934333672:role/github-actions-oidc-role`
  With a least-privilege policy scoped to only the S3 buckets, CRR IAM role, CloudWatch alarms, and STS identity check needed by the workflows

The script is fully idempotent — safe to run multiple times.

### Trusted Branches & Events

The OIDC trust policy accepts tokens only from:

| Condition | Value |
|---|---|
| Repository | `secant78/Multi-Region-S3-Replication-Failover` |
| Branches | `main`, `feature/*` |
| Events | Push + Pull Request |

Tokens from forks, unrelated repos, or other branches are **rejected by AWS STS**.

### Verifying OIDC is Working

After a successful workflow run, the "Verify AWS identity" step in Workflow 1 will show:

```json
{
  "Arn": "arn:aws:iam::866934333672:assumed-role/github-actions-oidc-role/GitHubActions-DeployInfrastructure"
}
```

The presence of `assumed-role/github-actions-oidc-role` confirms OIDC is active.

## Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure AWS credentials
aws configure

# 3. Run everything in sequence
python run_all.py

# Or skip the 500 MB upload (faster)
python run_all.py --skip-large

# Run individual steps
python setup_infrastructure.py    # Step 1: Create AWS resources
python upload_and_verify.py       # Step 2: Upload 20 files + verify
python test_delete_marker.py      # Step 3: Delete marker replication
python test_large_file_lag.py     # Step 4: 500 MB lag test
python simulate_failover.py       # Step 5: Failover + RTO
python generate_report.py         # Step 6: Print final report
```

## Test Results (Latest Run)

| Test | Result | Metric |
|---|---|---|
| 20-file replication | PASS | Avg 36.8s (SLA: 15 min) |
| Delete marker replication | PASS | 32.0s |
| 500 MB large file | PASS | 62.9s (1.0 min) |
| Failover RTO | PASS | 0.25s |

## Success Criteria

- [x] Replication happens within 15 minutes
- [x] Delete markers replicate correctly
- [x] Can retrieve objects from replica during primary failure

## Project Structure

```
.
├── config.py                  # Shared constants (bucket names, regions, thresholds)
├── setup_oidc_role.py         # One-time: create OIDC provider + github-actions-oidc-role
├── setup_infrastructure.py    # IAM CRR role + S3 buckets + CRR rules + CloudWatch
├── upload_and_verify.py       # Upload 20 test files, poll for replication
├── test_delete_marker.py      # Delete object, verify delete marker replicates
├── test_large_file_lag.py     # Multipart upload 500 MB, measure lag
├── simulate_failover.py       # Declare failure, read from replica, measure RTO
├── generate_report.py         # Aggregate results into lab_report.txt
├── run_all.py                 # Master runner (all steps in sequence)
├── requirements.txt
└── .github/
    └── workflows/
        ├── 01-deploy-infrastructure.yml  # OIDC auth
        ├── 02-replication-tests.yml      # OIDC auth (3 jobs)
        ├── 03-failover-simulation.yml    # OIDC auth
        └── 04-lint-and-validate.yml      # no AWS calls
```
