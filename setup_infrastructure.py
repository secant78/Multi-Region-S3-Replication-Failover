"""
Step 1 – Create IAM role, primary bucket, replica bucket, and CRR rules.
Run once to bootstrap the entire lab environment.
"""

import boto3
import json
import time
import sys
from config import (
    ACCOUNT_ID, PRIMARY_REGION, REPLICA_REGION,
    PRIMARY_BUCKET, REPLICA_BUCKET,
    REPLICATION_ROLE_NAME, REPLICATION_POLICY_NAME,
    CRITICAL_PREFIX, REPLICATE_TAG_KEY, REPLICATE_TAG_VALUE,
    ALARM_NAME, LAG_THRESHOLD_SECONDS,
)

iam = boto3.client("iam", region_name="us-east-1")
s3_primary = boto3.client("s3", region_name=PRIMARY_REGION)
s3_replica  = boto3.client("s3", region_name=REPLICA_REGION)
cw = boto3.client("cloudwatch", region_name=PRIMARY_REGION)


# ─── helpers ──────────────────────────────────────────────────────────────────

def ok(msg):  print(f"  [OK]  {msg}")
def info(msg): print(f"  [..] {msg}")
def step(msg): print(f"\n=== {msg} ===")


# ─── 1. IAM replication role ───────────────────────────────────────────────────

def create_replication_role():
    step("Creating IAM Replication Role")

    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "s3.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }]
    }

    try:
        resp = iam.create_role(
            RoleName=REPLICATION_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="S3 CRR role for Assignment 9",
        )
        role_arn = resp["Role"]["Arn"]
        ok(f"Role created: {role_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=REPLICATION_ROLE_NAME)["Role"]["Arn"]
        ok(f"Role already exists: {role_arn}")

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetReplicationConfiguration",
                    "s3:ListBucket",
                ],
                "Resource": f"arn:aws:s3:::{PRIMARY_BUCKET}",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObjectVersionForReplication",
                    "s3:GetObjectVersionAcl",
                    "s3:GetObjectVersionTagging",
                ],
                "Resource": f"arn:aws:s3:::{PRIMARY_BUCKET}/*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:ReplicateObject",
                    "s3:ReplicateDelete",
                    "s3:ReplicateTags",
                ],
                "Resource": f"arn:aws:s3:::{REPLICA_BUCKET}/*",
            },
        ],
    }

    try:
        iam.put_role_policy(
            RoleName=REPLICATION_ROLE_NAME,
            PolicyName=REPLICATION_POLICY_NAME,
            PolicyDocument=json.dumps(policy),
        )
        ok("Inline policy attached")
    except Exception as e:
        print(f"  [WARN] Policy attachment: {e}")

    return role_arn


# ─── 2. S3 buckets ────────────────────────────────────────────────────────────

def create_bucket(client, bucket_name, region):
    info(f"Creating bucket: {bucket_name} in {region}")
    try:
        if region == "us-east-1":
            client.create_bucket(Bucket=bucket_name)
        else:
            client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        ok(f"Bucket created: {bucket_name}")
    except client.exceptions.BucketAlreadyOwnedByYou:
        ok(f"Bucket already owned: {bucket_name}")
    except Exception as e:
        print(f"  [ERR] {e}")
        raise


def enable_versioning(client, bucket_name):
    client.put_bucket_versioning(
        Bucket=bucket_name,
        VersioningConfiguration={"Status": "Enabled"},
    )
    ok(f"Versioning enabled on {bucket_name}")


def block_public_access(client, bucket_name):
    client.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    ok(f"Public access blocked on {bucket_name}")


def setup_buckets():
    step("Creating S3 Buckets")
    create_bucket(s3_primary, PRIMARY_BUCKET, PRIMARY_REGION)
    create_bucket(s3_replica,  REPLICA_BUCKET, REPLICA_REGION)

    step("Enabling Versioning")
    enable_versioning(s3_primary, PRIMARY_BUCKET)
    enable_versioning(s3_replica,  REPLICA_BUCKET)

    step("Blocking Public Access")
    block_public_access(s3_primary, PRIMARY_BUCKET)
    block_public_access(s3_replica,  REPLICA_BUCKET)


# ─── 3. Cross-Region Replication ──────────────────────────────────────────────

def configure_crr(role_arn):
    step("Configuring Cross-Region Replication (CRR)")

    replication_config = {
        "Role": role_arn,
        "Rules": [
            # Rule 1 – replicate all objects under critical/ prefix
            {
                "ID": "rule-critical-prefix",
                "Status": "Enabled",
                "Priority": 1,
                "Filter": {"Prefix": CRITICAL_PREFIX},
                "DeleteMarkerReplication": {"Status": "Enabled"},
                "Destination": {
                    "Bucket": f"arn:aws:s3:::{REPLICA_BUCKET}",
                    "StorageClass": "STANDARD",
                },
            },
            # Rule 2 – replicate objects tagged replicate=true
            # Note: AWS does not support DeleteMarkerReplication with Tag filters.
            # Delete markers for tagged objects are NOT replicated (AWS limitation).
            {
                "ID": "rule-replicate-tag",
                "Status": "Enabled",
                "Priority": 2,
                "Filter": {
                    "Tag": {
                        "Key": REPLICATE_TAG_KEY,
                        "Value": REPLICATE_TAG_VALUE,
                    }
                },
                "DeleteMarkerReplication": {"Status": "Disabled"},
                "Destination": {
                    "Bucket": f"arn:aws:s3:::{REPLICA_BUCKET}",
                    "StorageClass": "STANDARD",
                },
            },
        ],
    }

    s3_primary.put_bucket_replication(
        Bucket=PRIMARY_BUCKET,
        ReplicationConfiguration=replication_config,
    )
    ok("CRR configured with 2 rules (prefix + tag)")


# ─── 4. CloudWatch alarm ──────────────────────────────────────────────────────

def create_cloudwatch_alarm():
    step("Creating CloudWatch Alarm for Replication Lag")

    # S3 replication lag metric: OperationsFailedReplication shows failures;
    # ReplicationLatency (seconds) is the key SLA metric.
    cw.put_metric_alarm(
        AlarmName=ALARM_NAME,
        AlarmDescription=(
            f"Alert when S3 replication lag from {PRIMARY_BUCKET} "
            f"exceeds {LAG_THRESHOLD_SECONDS}s (15-min SLA)"
        ),
        Namespace="AWS/S3",
        MetricName="ReplicationLatency",
        Dimensions=[
            {"Name": "SourceBucket",      "Value": PRIMARY_BUCKET},
            {"Name": "DestinationBucket", "Value": REPLICA_BUCKET},
            {"Name": "RuleId",            "Value": "rule-critical-prefix"},
        ],
        Statistic="Maximum",
        Period=300,          # 5-minute evaluation period
        EvaluationPeriods=3, # alarm if 3 consecutive periods breach
        Threshold=LAG_THRESHOLD_SECONDS,
        ComparisonOperator="GreaterThanThreshold",
        TreatMissingData="notBreaching",
    )
    ok(f"CloudWatch alarm created: {ALARM_NAME}")

    # Second alarm – failed replication operations
    cw.put_metric_alarm(
        AlarmName=f"{ALARM_NAME}-failures",
        AlarmDescription=f"Alert on S3 replication failures for {PRIMARY_BUCKET}",
        Namespace="AWS/S3",
        MetricName="OperationsFailedReplication",
        Dimensions=[
            {"Name": "SourceBucket",      "Value": PRIMARY_BUCKET},
            {"Name": "DestinationBucket", "Value": REPLICA_BUCKET},
            {"Name": "RuleId",            "Value": "rule-critical-prefix"},
        ],
        Statistic="Sum",
        Period=300,
        EvaluationPeriods=1,
        Threshold=1,
        ComparisonOperator="GreaterThanOrEqualToThreshold",
        TreatMissingData="notBreaching",
    )
    ok(f"CloudWatch failure alarm created: {ALARM_NAME}-failures")


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("  Assignment 9: Multi-Region S3 Replication Setup")
    print("="*60)
    print(f"  Primary : s3://{PRIMARY_BUCKET} ({PRIMARY_REGION})")
    print(f"  Replica : s3://{REPLICA_BUCKET} ({REPLICA_REGION})")
    print("="*60)

    role_arn = create_replication_role()

    # Brief pause so IAM propagates
    info("Waiting 10s for IAM propagation...")
    time.sleep(10)

    setup_buckets()
    configure_crr(role_arn)
    create_cloudwatch_alarm()

    print("\n" + "="*60)
    print("  Infrastructure setup COMPLETE")
    print(f"  Primary bucket : {PRIMARY_BUCKET}")
    print(f"  Replica bucket : {REPLICA_BUCKET}")
    print(f"  Replication role ARN : {role_arn}")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
