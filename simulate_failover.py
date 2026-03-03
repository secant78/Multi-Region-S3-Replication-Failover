"""
Step 5 – Simulate primary region failure and calculate RTO.

Failover simulation:
  1. Record a "failure start" timestamp.
  2. Verify all replicated objects are readable from the replica bucket
     (eu-west-1) without accessing the primary bucket at all.
  3. Measure time from failure declaration to confirmed read availability
     in replica → this is the RTO.

No actual AWS infrastructure is disabled; we simply stop using the
primary bucket and measure how quickly the replica serves requests.
"""

import boto3
import time
import json
import datetime
import io
from config import (
    PRIMARY_REGION, REPLICA_REGION,
    PRIMARY_BUCKET, REPLICA_BUCKET,
    CRITICAL_PREFIX,
)

# ONLY the replica client is used during failover simulation
s3_primary = boto3.client("s3", region_name=PRIMARY_REGION)
s3_replica  = boto3.client("s3", region_name=REPLICA_REGION)


def ok(msg):   print(f"  [OK]  {msg}")
def info(msg): print(f"  [..] {msg}")
def warn(msg): print(f"  [!!] {msg}")


def list_replica_objects():
    """List all objects currently in the replica bucket."""
    paginator = s3_replica.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=REPLICA_BUCKET):
        for obj in page.get("Contents", []):
            objects.append(obj["Key"])
    return objects


def read_object_from_replica(key):
    """Attempt to read an object exclusively from the replica bucket."""
    resp = s3_replica.get_object(Bucket=REPLICA_BUCKET, Key=key)
    data = resp["Body"].read()
    return len(data)


def declare_failure():
    print("\n" + "!"*60)
    print("  !! SIMULATING PRIMARY REGION (us-east-1) FAILURE !!")
    print("!"*60)
    failure_time = datetime.datetime.utcnow()
    print(f"  Failure declared at: {failure_time.isoformat()}Z")
    print("  All reads will now route EXCLUSIVELY to replica (eu-west-1)")
    return failure_time


def verify_replica_availability(objects):
    """
    Attempt to read every object from replica, measuring individual latencies.
    Returns a dict of key → {'readable': bool, 'size_bytes': int, 'latency_ms': float}.
    """
    print(f"\n=== Verifying Replica Read Availability ({len(objects)} objects) ===")
    results = {}
    readable_count = 0

    for key in objects:
        t0 = time.time()
        try:
            size = read_object_from_replica(key)
            latency_ms = (time.time() - t0) * 1000
            results[key] = {"readable": True, "size_bytes": size, "latency_ms": latency_ms}
            readable_count += 1
            ok(f"  READ OK  {key:60s}  {latency_ms:.0f}ms")
        except Exception as e:
            latency_ms = (time.time() - t0) * 1000
            results[key] = {"readable": False, "error": str(e), "latency_ms": latency_ms}
            warn(f"  READ FAIL {key}: {e}")

    print(f"\n  Readable: {readable_count}/{len(objects)}")
    return results


def calculate_rto(failure_time, first_read_time):
    """RTO = time from failure declaration to first confirmed read in replica."""
    rto_s = (first_read_time - failure_time).total_seconds()
    return rto_s


def main():
    print("\n=== Step 5: Failover Simulation & RTO Calculation ===")

    # ── enumerate what's in the replica ──────────────────────────────────────
    info("Listing objects in replica bucket ...")
    replica_objects = list_replica_objects()

    # Filter out the 500 MB test file to keep reads fast
    test_objects = [k for k in replica_objects
                    if "large-test-file" not in k]
    info(f"Found {len(replica_objects)} objects in replica "
         f"({len(test_objects)} selected for read test, "
         f"{len(replica_objects)-len(test_objects)} large files skipped)")

    if not test_objects:
        warn("No objects in replica! Run upload_and_verify.py first.")
        return

    # ── declare failure ───────────────────────────────────────────────────────
    failure_time = declare_failure()

    # ── measure time-to-first-byte from replica ───────────────────────────────
    info("Starting timed read from replica ...")
    failover_start = time.time()

    first_successful_read_time = None
    read_results = {}

    for key in test_objects:
        t0 = time.time()
        try:
            size = read_object_from_replica(key)
            latency_ms = (time.time() - t0) * 1000
            read_results[key] = {"readable": True, "size_bytes": size, "latency_ms": latency_ms}
            if first_successful_read_time is None:
                first_successful_read_time = datetime.datetime.utcnow()
                ok(f"First successful read from replica: {key} ({latency_ms:.0f}ms)")
        except Exception as e:
            read_results[key] = {"readable": False, "error": str(e)}

    failover_duration = time.time() - failover_start
    readable = sum(1 for v in read_results.values() if v["readable"])

    # ── RTO ───────────────────────────────────────────────────────────────────
    if first_successful_read_time:
        rto_s = calculate_rto(failure_time, first_successful_read_time)
    else:
        rto_s = None

    latencies = [v["latency_ms"] for v in read_results.values() if v["readable"]]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0

    print(f"\n  {'='*50}")
    print(f"  FAILOVER SIMULATION RESULTS")
    print(f"  {'='*50}")
    print(f"  Failure declared (UTC) : {failure_time.isoformat()}Z")
    print(f"  First replica read     : {first_successful_read_time.isoformat() if first_successful_read_time else 'N/A'}Z")
    print(f"  RTO (time to first read): {rto_s:.2f}s" if rto_s else "  RTO: N/A")
    print(f"  Objects tested         : {len(test_objects)}")
    print(f"  Objects readable       : {readable}/{len(test_objects)}")
    print(f"  Avg read latency       : {avg_latency:.0f}ms")
    print(f"  P95 read latency       : {p95_latency:.0f}ms")
    print(f"  Full verification time : {failover_duration:.1f}s")
    print(f"  Replica region         : {REPLICA_REGION}")
    print(f"  {'='*50}")

    if readable == len(test_objects):
        ok("SUCCESS: All objects readable from replica during primary failure simulation")
    else:
        warn(f"PARTIAL: {len(test_objects)-readable} objects NOT readable from replica")

    result = {
        "failure_time_utc": failure_time.isoformat(),
        "first_read_utc": first_successful_read_time.isoformat() if first_successful_read_time else None,
        "rto_seconds": rto_s,
        "objects_tested": len(test_objects),
        "objects_readable": readable,
        "avg_read_latency_ms": avg_latency,
        "p95_read_latency_ms": p95_latency,
        "full_verification_s": failover_duration,
        "read_results": read_results,
    }

    with open("failover_results.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    ok("Results saved to failover_results.json")

    return result


if __name__ == "__main__":
    main()
