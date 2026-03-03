"""
Step 2 – Upload 20 test files, then verify they replicated to eu-west-1.

Files uploaded:
  - 10 under critical/ prefix  (Rule 1 triggers)
  - 10 tagged replicate=true   (Rule 2 triggers)

Verification polls the replica bucket for up to 15 minutes.
"""

import boto3
import time
import io
import json
import datetime
from config import (
    PRIMARY_REGION, REPLICA_REGION,
    PRIMARY_BUCKET, REPLICA_BUCKET,
    CRITICAL_PREFIX, REPLICATE_TAG_KEY, REPLICATE_TAG_VALUE,
)

s3_primary = boto3.client("s3", region_name=PRIMARY_REGION)
s3_replica  = boto3.client("s3", region_name=REPLICA_REGION)

RESULTS = []  # accumulated for final report


def ok(msg):  print(f"  [OK]  {msg}")
def info(msg): print(f"  [..] {msg}")
def warn(msg): print(f"  [!!] {msg}")


# ─── upload helpers ───────────────────────────────────────────────────────────

def make_content(filename, idx):
    body = (
        f"File: {filename}\n"
        f"Index: {idx}\n"
        f"Uploaded: {datetime.datetime.utcnow().isoformat()}Z\n"
        f"Assignment: Multi-Region S3 Replication (Assignment 9)\n"
        f"{'data: ' + 'x' * 200}\n"   # pad to ~250 bytes
    )
    return body.encode()


def upload_critical(idx):
    key = f"{CRITICAL_PREFIX}critical-file-{idx:02d}.txt"
    body = make_content(key, idx)
    s3_primary.put_object(
        Bucket=PRIMARY_BUCKET,
        Key=key,
        Body=body,
        ContentType="text/plain",
    )
    return key


def upload_tagged(idx):
    key = f"tagged/tagged-file-{idx:02d}.txt"
    body = make_content(key, idx)
    s3_primary.put_object(
        Bucket=PRIMARY_BUCKET,
        Key=key,
        Body=body,
        ContentType="text/plain",
        Tagging=f"{REPLICATE_TAG_KEY}={REPLICATE_TAG_VALUE}",
    )
    return key


# ─── upload 20 files ──────────────────────────────────────────────────────────

def upload_all():
    print("\n=== Uploading 20 Test Files ===")
    keys = []

    print("  Uploading 10 files under critical/ prefix ...")
    for i in range(1, 11):
        key = upload_critical(i)
        keys.append(key)
        ok(f"Uploaded s3://{PRIMARY_BUCKET}/{key}")

    print("  Uploading 10 files with tag replicate=true ...")
    for i in range(1, 11):
        key = upload_tagged(i)
        keys.append(key)
        ok(f"Uploaded s3://{PRIMARY_BUCKET}/{key}")

    print(f"\n  Total uploaded: {len(keys)} files")
    return keys


# ─── verify replication ───────────────────────────────────────────────────────

def object_exists_in_replica(key):
    try:
        s3_replica.head_object(Bucket=REPLICA_BUCKET, Key=key)
        return True
    except s3_replica.exceptions.ClientError:
        return False


def verify_replication(keys, max_wait_seconds=900):
    print("\n=== Verifying Replication to Replica Bucket ===")
    info(f"Polling replica bucket every 30s (max {max_wait_seconds}s = 15 min)")

    upload_time = datetime.datetime.utcnow()
    pending = set(keys)
    replicated = {}

    start = time.time()
    while pending and (time.time() - start) < max_wait_seconds:
        newly_replicated = []
        for key in list(pending):
            if object_exists_in_replica(key):
                elapsed = time.time() - start
                replicated[key] = elapsed
                newly_replicated.append(key)
                pending.remove(key)

        if newly_replicated:
            ok(f"{len(newly_replicated)} newly replicated | pending: {len(pending)}")
            for k in newly_replicated:
                info(f"  Replicated in {replicated[k]:.1f}s: {k}")
        else:
            elapsed = time.time() - start
            info(f"  Elapsed: {elapsed:.0f}s — still waiting for {len(pending)} files ...")

        if pending:
            time.sleep(30)

    # Summary
    total_elapsed = time.time() - start
    print(f"\n  --- Replication Verification Summary ---")
    print(f"  Files uploaded     : {len(keys)}")
    print(f"  Files replicated   : {len(replicated)}")
    print(f"  Files still pending: {len(pending)}")

    if replicated:
        times = list(replicated.values())
        print(f"  Min replication lag: {min(times):.1f}s")
        print(f"  Max replication lag: {max(times):.1f}s")
        print(f"  Avg replication lag: {sum(times)/len(times):.1f}s")

    if pending:
        warn(f"Not replicated within {max_wait_seconds}s: {pending}")
        sla_met = False
    else:
        ok("All 20 files replicated successfully!")
        sla_met = max(replicated.values()) <= 900 if replicated else False
        if sla_met:
            ok("15-minute SLA MET")
        else:
            warn("15-minute SLA EXCEEDED")

    return {
        "keys_uploaded": len(keys),
        "keys_replicated": len(replicated),
        "pending": list(pending),
        "replication_times": replicated,
        "sla_met": sla_met,
        "total_elapsed_s": total_elapsed,
    }


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    keys = upload_all()
    results = verify_replication(keys)

    # Persist results for the report
    with open("replication_results.json", "w") as f:
        # Convert dict keys to strings for JSON serialization
        results["replication_times"] = {
            k: v for k, v in results["replication_times"].items()
        }
        json.dump(results, f, indent=2)
    ok("Results saved to replication_results.json")

    return results


if __name__ == "__main__":
    main()
