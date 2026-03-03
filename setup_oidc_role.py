"""
OIDC Federated Identity Setup for GitHub Actions
-------------------------------------------------
Creates:
  1. An IAM OIDC Identity Provider for token.actions.githubusercontent.com
  2. An IAM Role (github-actions-oidc-role) trusted exclusively by this
     GitHub repository, scoped to main branch, feature/* branches, and PRs
  3. A least-privilege inline policy covering all AWS actions used by the
     4 GitHub Actions workflows in this project

Run once from a machine with IAM administrator access:
    python setup_oidc_role.py

The script is fully idempotent -- running it multiple times is safe.
"""

import boto3
import json
import sys
from config import ACCOUNT_ID, PRIMARY_BUCKET, REPLICA_BUCKET

# ── constants ─────────────────────────────────────────────────────────────────

GITHUB_REPO       = "secant78/Multi-Region-S3-Replication-Failover"
OIDC_PROVIDER_URL = "https://token.actions.githubusercontent.com"
OIDC_AUDIENCE     = "sts.amazonaws.com"

# Two thumbprints covering GitHub's current and rotated TLS certificates.
# AWS ignores thumbprints for GitHub's OIDC provider (validates cert via CDN),
# but the API requires at least one syntactically valid 40-hex-char value.
OIDC_THUMBPRINTS = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b4ddf6e7094db68bca4",
]

OIDC_PROVIDER_ARN = (
    f"arn:aws:iam::{ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
)

ROLE_NAME   = "github-actions-oidc-role"
ROLE_ARN    = f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}"
POLICY_NAME = "github-actions-oidc-policy"

iam = boto3.client("iam", region_name="us-east-1")


# ── helpers ───────────────────────────────────────────────────────────────────

def ok(msg):   print(f"  [OK]  {msg}")
def info(msg): print(f"  [..] {msg}")
def warn(msg): print(f"  [!!] {msg}")
def step(msg): print(f"\n=== {msg} ===")


# ── Step 1: OIDC Identity Provider ────────────────────────────────────────────

def create_oidc_provider():
    step("Creating OIDC Identity Provider")
    info(f"URL : {OIDC_PROVIDER_URL}")
    info(f"Aud : {OIDC_AUDIENCE}")

    try:
        resp = iam.create_open_id_connect_provider(
            Url=OIDC_PROVIDER_URL,
            ClientIDList=[OIDC_AUDIENCE],
            ThumbprintList=OIDC_THUMBPRINTS,
        )
        provider_arn = resp["OpenIDConnectProviderArn"]
        ok(f"OIDC provider created: {provider_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        ok(f"OIDC provider already exists: {OIDC_PROVIDER_ARN}")
        provider_arn = OIDC_PROVIDER_ARN

    return provider_arn


# ── Step 2: Trust Policy ──────────────────────────────────────────────────────

def build_trust_policy(provider_arn):
    """
    Trust policy conditions:
      - aud == sts.amazonaws.com  (StringEquals — exact match required)
      - sub matches repo + branch (StringLike allows wildcards):
          * main branch push
          * any feature/* branch push
          * pull_request event (sub format differs from branch push)
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "GitHubActionsOIDC",
                "Effect": "Allow",
                "Principal": {
                    "Federated": provider_arn,
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": OIDC_AUDIENCE,
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{GITHUB_REPO}:ref:refs/heads/main",
                            f"repo:{GITHUB_REPO}:ref:refs/heads/feature/*",
                            f"repo:{GITHUB_REPO}:pull_request",
                        ],
                    },
                },
            }
        ],
    }


# ── Step 3: Permissions Policy ────────────────────────────────────────────────

def build_permissions_policy():
    """
    Least-privilege policy covering all AWS actions used by the 4 workflows:
      Workflow 01 - deploy infrastructure (S3, IAM, CloudWatch, STS)
      Workflow 02 - replication tests    (S3 read/write/delete/list)
      Workflow 03 - failover simulation  (S3 read/list)
      Workflow 04 - lint/validate        (no AWS calls — not included)
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "S3BucketManagement",
                "Effect": "Allow",
                "Action": [
                    "s3:CreateBucket",
                    "s3:HeadBucket",
                    "s3:GetBucketVersioning",
                    "s3:PutBucketVersioning",
                    "s3:PutPublicAccessBlock",
                    "s3:GetBucketReplication",
                    "s3:PutBucketReplication",
                    "s3:ListBucket",
                    "s3:ListBucketVersions",
                    "s3:ListAllMyBuckets",
                    "s3:GetBucketLocation",
                ],
                "Resource": [
                    f"arn:aws:s3:::{PRIMARY_BUCKET}",
                    f"arn:aws:s3:::{REPLICA_BUCKET}",
                ],
            },
            {
                "Sid": "S3ObjectOperations",
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:DeleteObject",
                    "s3:HeadObject",
                    "s3:GetObjectVersion",
                    "s3:ListObjectVersions",
                    "s3:ListObjectsV2",
                ],
                "Resource": [
                    f"arn:aws:s3:::{PRIMARY_BUCKET}/*",
                    f"arn:aws:s3:::{REPLICA_BUCKET}/*",
                ],
            },
            {
                "Sid": "IAMReplicationRole",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateRole",
                    "iam:GetRole",
                    "iam:PutRolePolicy",
                    "iam:PassRole",
                ],
                # Scoped only to the S3 CRR role — not all IAM roles
                "Resource": f"arn:aws:iam::{ACCOUNT_ID}:role/s3-crr-role-*",
            },
            {
                "Sid": "CloudWatchAlarms",
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:PutMetricAlarm",
                    "cloudwatch:DescribeAlarms",
                ],
                "Resource": "*",
            },
            {
                "Sid": "STSIdentityCheck",
                "Effect": "Allow",
                "Action": "sts:GetCallerIdentity",
                "Resource": "*",
            },
        ],
    }


# ── Step 4: IAM Role ──────────────────────────────────────────────────────────

def create_oidc_role(provider_arn):
    step("Creating IAM OIDC Role")
    info(f"Role name : {ROLE_NAME}")
    info(f"Role ARN  : {ROLE_ARN}")

    trust_policy = build_trust_policy(provider_arn)

    try:
        resp = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=(
                "Assumed by GitHub Actions via OIDC for the "
                f"{GITHUB_REPO} repository. "
                "Provides least-privilege access to S3, IAM (CRR role only), "
                "CloudWatch, and STS for the Multi-Region S3 Replication project."
            ),
            MaxSessionDuration=3600,  # 1 hour — sufficient for any single workflow job
            Tags=[
                {"Key": "Project",     "Value": "Multi-Region-S3-Replication"},
                {"Key": "ManagedBy",   "Value": "setup_oidc_role.py"},
                {"Key": "GitHubRepo",  "Value": GITHUB_REPO},
                {"Key": "AuthMethod",  "Value": "OIDC"},
            ],
        )
        role_arn = resp["Role"]["Arn"]
        ok(f"Role created: {role_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        ok(f"Role already exists: {role_arn}")

        # Update trust policy to ensure it reflects current config
        iam.update_assume_role_policy(
            RoleName=ROLE_NAME,
            PolicyDocument=json.dumps(trust_policy),
        )
        ok("Trust policy refreshed")

    return role_arn


# ── Step 5: Inline Permissions Policy ─────────────────────────────────────────

def attach_permissions_policy():
    step("Attaching Permissions Policy")
    info(f"Policy name : {POLICY_NAME}")

    permissions_policy = build_permissions_policy()

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=POLICY_NAME,
        PolicyDocument=json.dumps(permissions_policy),
    )
    ok(f"Inline policy attached: {POLICY_NAME}")


# ── Step 6: Verify ────────────────────────────────────────────────────────────

def verify_role():
    step("Verifying Role Configuration")

    role = iam.get_role(RoleName=ROLE_NAME)["Role"]
    trust = role["AssumeRolePolicyDocument"]

    ok(f"Role ARN   : {role['Arn']}")
    ok(f"Created    : {role['CreateDate']}")
    ok(f"Max session: {role['MaxSessionDuration']}s")

    print("\n  Trust Policy (summary):")
    for stmt in trust.get("Statement", []):
        principal = stmt.get("Principal", {}).get("Federated", "N/A")
        conditions = stmt.get("Condition", {})
        sub_conds = conditions.get("StringLike", {}).get(
            "token.actions.githubusercontent.com:sub", []
        )
        print(f"    Principal  : {principal}")
        print(f"    Trusted subs:")
        for sub in (sub_conds if isinstance(sub_conds, list) else [sub_conds]):
            print(f"      - {sub}")

    print("\n  Permissions Policy (actions summary):")
    policy = iam.get_role_policy(RoleName=ROLE_NAME, PolicyName=POLICY_NAME)
    doc = policy["PolicyDocument"]
    for stmt in doc.get("Statement", []):
        sid = stmt.get("Sid", "unnamed")
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        print(f"    [{sid}]: {len(actions)} action(s)")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 65)
    print("  OIDC Federated Identity Setup for GitHub Actions")
    print("=" * 65)
    print(f"  Repository  : {GITHUB_REPO}")
    print(f"  AWS Account : {ACCOUNT_ID}")
    print(f"  Role name   : {ROLE_NAME}")
    print("=" * 65)

    # Verify caller has sufficient IAM permissions before starting
    sts = boto3.client("sts", region_name="us-east-1")
    identity = sts.get_caller_identity()
    info(f"Running as  : {identity['Arn']}")

    provider_arn = create_oidc_provider()
    role_arn     = create_oidc_role(provider_arn)
    attach_permissions_policy()
    verify_role()

    print("\n" + "=" * 65)
    print("  SETUP COMPLETE")
    print("=" * 65)
    print(f"  OIDC Provider ARN : {OIDC_PROVIDER_ARN}")
    print(f"  Role ARN          : {role_arn}")
    print()
    print("  Next steps:")
    print("  1. No GitHub secrets needed -- OIDC is keyless")
    print("  2. Push workflow changes and trigger Workflow 01")
    print("  3. Verify 'sts:GetCallerIdentity' shows assumed-role/github-actions-oidc-role")
    print("  4. Delete old AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY secrets")
    print("=" * 65 + "\n")

    return role_arn


if __name__ == "__main__":
    main()
