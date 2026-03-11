"""
Assignment 9: Multi-Region S3 Replication with Failover
Configuration constants shared across all scripts.
"""

ACCOUNT_ID = "866934333672"
PRIMARY_REGION = "us-east-1"
REPLICA_REGION = "eu-west-1"

# Unique suffix so buckets don't collide with others in the account
SUFFIX = "sean-0303"
PRIMARY_BUCKET = f"s3-primary-{SUFFIX}"
REPLICA_BUCKET = f"s3-replica-{SUFFIX}"

REPLICATION_ROLE_NAME = f"s3-crr-role-{SUFFIX}"
REPLICATION_POLICY_NAME = f"s3-crr-policy-{SUFFIX}"

# Replication rule prefixes / tags
CRITICAL_PREFIX = "critical/"
REPLICATE_TAG_KEY = "replicate"
REPLICATE_TAG_VALUE = "true"

# CloudWatch alarm
ALARM_NAME = f"S3ReplicationLag-{SUFFIX}"
LAG_THRESHOLD_SECONDS = 900  # 15 minutes SLA
