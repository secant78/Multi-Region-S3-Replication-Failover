"""
Step 4 – Upload a 500 MB file to the primary bucket and measure replication lag.

The file is generated in-memory in 10 MB chunks using a multipart upload
so no local disk space is required. Replication lag is tracked until the
object appears in the replica bucket.
"""

import boto3
import time
import io
import json
import datetime
from config import (
    PRIMARY_REGION, REPLICA_REGION,
    PRIMARY_BUCKET, REPLICA_BUCKET,
    CRITICAL_PREFIX,
)

s3_primary = boto3.client("s3", region_name=PRIMARY_REGION)
s3_replica  = boto3.client("s3", region_name=REPLICA_REGION)

TARGET_SIZE_MB  = 500
CHUNK_SIZE_MB   = 10          # multipart chunk – must be >= 5 MB
LARGE_FILE_KEY  = f"{CRITICAL_PREFIX}large-test-file-500mb.bin"
MAX_WAIT_S      = 1800        # poll up to 30 minutes for large file


def ok(msg):   print(f"  [OK]  {msg}")
def info(msg): print(f"  [..] {msg}")
def warn(msg): print(f"  [!!] {msg}")


def upload_large_file():
    """Stream a synthetic 500 MB file to S3 using multipart upload."""
    print(f"\n=== Uploading 500 MB Large File ===")
    info(f"Key: {LARGE_FILE_KEY}")
    info(f"Bucket: {PRIMARY_BUCKET}")

    chunk_size = CHUNK_SIZE_MB * 1024 * 1024
    total_size = TARGET_SIZE_MB * 1024 * 1024
    num_parts  = total_size // chunk_size   # 50 parts of 10 MB each

    # Initiate multipart upload
    mpu = s3_primary.create_multipart_upload(
        Bucket=PRIMARY_BUCKET,
        Key=LARGE_FILE_KEY,
        ContentType="application/octet-stream",
    )
    upload_id = mpu["UploadId"]
    info(f"Multipart upload initiated (ID: {upload_id[:8]}...)")

    parts = []
    upload_start = time.time()

    try:
        for part_num in range(1, num_parts + 1):
            # Generate chunk of pseudo-random-ish data
            chunk = bytes([part_num % 256] * chunk_size)
            resp = s3_primary.upload_part(
                Bucket=PRIMARY_BUCKET,
                Key=LARGE_FILE_KEY,
                PartNumber=part_num,
                UploadId=upload_id,
                Body=chunk,
            )
            parts.append({"PartNumber": part_num, "ETag": resp["ETag"]})
            pct = (part_num / num_parts) * 100
            info(f"  Uploaded part {part_num}/{num_parts} ({pct:.0f}%)")

        # Complete multipart upload
        s3_primary.complete_multipart_upload(
            Bucket=PRIMARY_BUCKET,
            Key=LARGE_FILE_KEY,
            MultipartUpload={"Parts": parts},
            UploadId=upload_id,
        )
        upload_duration = time.time() - upload_start
        ok(f"Large file upload complete in {upload_duration:.1f}s "
           f"({TARGET_SIZE_MB / upload_duration:.1f} MB/s)")

    except Exception as e:
        warn(f"Upload failed: {e}")
        s3_primary.abort_multipart_upload(
            Bucket=PRIMARY_BUCKET, Key=LARGE_FILE_KEY, UploadId=upload_id
        )
        raise

    return datetime.datetime.utcnow(), upload_duration


def poll_replica_for_large_file(upload_finish_utc, upload_duration_s):
    """Poll replica bucket until large file appears, measuring lag."""
    print(f"\n=== Polling Replica for Large File ===")
    info(f"Upload completed at: {upload_finish_utc.isoformat()}Z")
    info(f"Polling max {MAX_WAIT_S}s ({MAX_WAIT_S//60} min) ...")

    start = time.time()
    interval = 60  # check every minute for large file

    while (time.time() - start) < MAX_WAIT_S:
        try:
            head = s3_replica.head_object(Bucket=REPLICA_BUCKET, Key=LARGE_FILE_KEY)
            elapsed = time.time() - start
            size_mb = head["ContentLength"] / (1024 * 1024)
            ok(f"Large file replicated!")
            ok(f"  Size in replica  : {size_mb:.1f} MB")
            ok(f"  Replication lag  : {elapsed:.1f}s ({elapsed/60:.1f} min)")
            return elapsed, True
        except Exception:
            elapsed = time.time() - start
            info(f"  Not yet in replica ({elapsed:.0f}s elapsed) ...")
            time.sleep(interval)

    elapsed = time.time() - start
    warn(f"Large file NOT replicated within {MAX_WAIT_S}s!")
    return elapsed, False


def main():
    upload_finish_utc, upload_duration_s = upload_large_file()
    replication_lag_s, replicated = poll_replica_for_large_file(
        upload_finish_utc, upload_duration_s
    )

    print(f"\n  --- Large File Replication Summary ---")
    print(f"  File size         : {TARGET_SIZE_MB} MB")
    print(f"  Upload duration   : {upload_duration_s:.1f}s")
    print(f"  Replication lag   : {replication_lag_s:.1f}s ({replication_lag_s/60:.1f} min)")
    print(f"  Replicated        : {'YES' if replicated else 'NO (timeout)'}")
    sla_met = replicated and replication_lag_s <= 900
    print(f"  15-min SLA met    : {'YES' if sla_met else 'NO'}")

    result = {
        "file_size_mb": TARGET_SIZE_MB,
        "key": LARGE_FILE_KEY,
        "upload_finish_utc": upload_finish_utc.isoformat(),
        "upload_duration_s": upload_duration_s,
        "replication_lag_s": replication_lag_s,
        "replicated": replicated,
        "sla_met": sla_met,
    }

    with open("large_file_results.json", "w") as f:
        json.dump(result, f, indent=2)
    ok("Results saved to large_file_results.json")

    return result


if __name__ == "__main__":
    main()
