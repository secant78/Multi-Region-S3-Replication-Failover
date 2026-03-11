"""
Step 3 – Delete an object in the primary bucket and verify the delete marker
         replicates to the replica bucket within the SLA window.

Expects upload_and_verify.py to have already run so critical/ files exist.
"""

import boto3
import time
import json
import datetime
from config import (
    PRIMARY_REGION, REPLICA_REGION,
    PRIMARY_BUCKET, REPLICA_BUCKET,
    CRITICAL_PREFIX,
)

s3_primary = boto3.client("s3", region_name=PRIMARY_REGION)
s3_replica  = boto3.client("s3", region_name=REPLICA_REGION)


def ok(msg):   print(f"  [OK]  {msg}")
def info(msg): print(f"  [..] {msg}")
def warn(msg): print(f"  [!!] {msg}")


def get_latest_version(client, bucket, key):
    """Return the latest version ID for a key (None if delete marker)."""
    resp = client.list_object_versions(Bucket=bucket, Prefix=key)
    versions = resp.get("Versions", [])
    if not versions:
        return None
    versions.sort(key=lambda v: v["LastModified"], reverse=True)
    return versions[0]["VersionId"]


def has_delete_marker_in_replica(key):
    """Check whether a delete marker exists in replica for the given key."""
    try:
        resp = s3_replica.list_object_versions(Bucket=REPLICA_BUCKET, Prefix=key)
        markers = resp.get("DeleteMarkers", [])
        return len(markers) > 0
    except Exception as e:
        warn(f"Error checking delete markers: {e}")
        return False


def main():
    print("\n=== Test: Delete Marker Replication ===")

    # Choose a target object that was already uploaded
    target_key = f"{CRITICAL_PREFIX}critical-file-05.txt"

    # ── verify object exists in primary ───────────────────────────────────────
    info(f"Target key: {target_key}")
    try:
        head = s3_primary.head_object(Bucket=PRIMARY_BUCKET, Key=target_key)
        ok(f"Object exists in primary (ETag: {head['ETag']})")
    except Exception as e:
        warn(f"Object not found in primary – run upload_and_verify.py first. ({e})")
        return

    # ── get current version before deletion ───────────────────────────────────
    version_before = get_latest_version(s3_primary, PRIMARY_BUCKET, target_key)
    info(f"Version before delete: {version_before}")

    # ── delete from primary (no VersionId → creates delete marker) ───────────
    delete_time = datetime.datetime.utcnow()
    s3_primary.delete_object(Bucket=PRIMARY_BUCKET, Key=target_key)
    ok(f"Object deleted from primary at {delete_time.isoformat()}Z")

    # Confirm delete marker in primary
    resp = s3_primary.list_object_versions(Bucket=PRIMARY_BUCKET, Prefix=target_key)
    primary_markers = resp.get("DeleteMarkers", [])
    if primary_markers:
        ok(f"Delete marker confirmed in primary (marker ID: {primary_markers[0]['VersionId']})")
    else:
        warn("No delete marker found in primary – unexpected!")

    # ── poll replica for delete marker ────────────────────────────────────────
    info("Polling replica bucket for delete marker replication (max 15 min) ...")
    start = time.time()
    max_wait = 900  # 15 minutes
    marker_found = False
    poll_interval = 30

    while (time.time() - start) < max_wait:
        if has_delete_marker_in_replica(target_key):
            elapsed = time.time() - start
            ok(f"Delete marker replicated in {elapsed:.1f}s!")
            marker_found = True
            break
        elapsed = time.time() - start
        info(f"  Elapsed: {elapsed:.0f}s – marker not yet in replica ...")
        time.sleep(poll_interval)

    total_elapsed = time.time() - start

    # ── attempt to retrieve from replica (should fail with 404 or return marker)
    print("\n  --- Retrieval Test After Deletion ---")
    try:
        s3_replica.get_object(Bucket=REPLICA_BUCKET, Key=target_key)
        warn("Object is READABLE in replica (unexpected – delete marker not active?)")
    except s3_replica.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "NoSuchVersion"):
            ok(f"Object correctly returns '{code}' from replica (delete marker active)")
        else:
            warn(f"Unexpected error code: {code}")

    # ── summary ───────────────────────────────────────────────────────────────
    print(f"\n  --- Delete Marker Replication Summary ---")
    print(f"  Target key        : {target_key}")
    print(f"  Delete time (UTC) : {delete_time.isoformat()}Z")
    print(f"  Marker replicated : {'YES' if marker_found else 'NO (timeout)'}")
    print(f"  Elapsed           : {total_elapsed:.1f}s")
    sla_met = marker_found and total_elapsed <= 900
    print(f"  15-min SLA met    : {'YES' if sla_met else 'NO'}")

    result = {
        "target_key": target_key,
        "delete_time_utc": delete_time.isoformat(),
        "marker_replicated": marker_found,
        "elapsed_seconds": total_elapsed,
        "sla_met": sla_met,
    }

    with open("delete_marker_results.json", "w") as f:
        json.dump(result, f, indent=2)
    ok("Results saved to delete_marker_results.json")

    return result


if __name__ == "__main__":
    main()
