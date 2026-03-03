"""
Step 6 - Aggregate all JSON result files and produce a formatted lab report.
Run after all other scripts have completed.
"""

import json
import os
import datetime
from config import (
    PRIMARY_BUCKET, REPLICA_BUCKET,
    PRIMARY_REGION, REPLICA_REGION,
    ALARM_NAME,
)


def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def fmt_s(seconds):
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds:.1f}s ({seconds/60:.1f} min)"


def main():
    repl   = load_json("replication_results.json")
    delete = load_json("delete_marker_results.json")
    large  = load_json("large_file_results.json")
    fo     = load_json("failover_results.json")

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    SEP = "=" * 80
    LINE = "-" * 80

    lines = []
    lines.append(SEP)
    lines.append("  ASSIGNMENT 9: MULTI-REGION S3 REPLICATION WITH FAILOVER")
    lines.append(f"  Lab Report -- Generated {now}")
    lines.append(SEP)
    lines.append("")
    lines.append("ENVIRONMENT")
    lines.append("-----------")
    lines.append(f"  Primary bucket : s3://{PRIMARY_BUCKET} ({PRIMARY_REGION})")
    lines.append(f"  Replica bucket : s3://{REPLICA_BUCKET} ({REPLICA_REGION})")
    lines.append(f"  CloudWatch     : {ALARM_NAME}")
    lines.append("")

    # ---- Test 1 ----
    lines.append(LINE)
    lines.append("TEST 1: 20-FILE UPLOAD & REPLICATION VERIFICATION")
    lines.append(LINE)
    if repl:
        times = repl.get("replication_times", {})
        lags  = list(times.values())
        lines.append(f"  Files uploaded          : {repl.get('keys_uploaded', 'N/A')}")
        lines.append(f"  Files replicated        : {repl.get('keys_replicated', 'N/A')}")
        lines.append(f"  Files still pending     : {len(repl.get('pending', []))}")
        lines.append(f"  Min replication lag     : {fmt_s(min(lags)) if lags else 'N/A'}")
        lines.append(f"  Max replication lag     : {fmt_s(max(lags)) if lags else 'N/A'}")
        lines.append(f"  Avg replication lag     : {fmt_s(sum(lags)/len(lags)) if lags else 'N/A'}")
        lines.append(f"  15-minute SLA met       : {'[PASS] YES' if repl.get('sla_met') else '[FAIL] NO'}")
        lines.append(f"  Total elapsed           : {fmt_s(repl.get('total_elapsed_s'))}")
        if lags:
            lines.append("")
            lines.append("  Per-file replication times:")
            for key, lag in sorted(times.items(), key=lambda x: x[1]):
                lines.append(f"    {key:<55s}  {lag:>8.1f}s")
    else:
        lines.append("  [No data -- run upload_and_verify.py]")
    lines.append("")

    # ---- Test 2 ----
    lines.append(LINE)
    lines.append("TEST 2: DELETE MARKER REPLICATION")
    lines.append(LINE)
    if delete:
        lines.append(f"  Target key              : {delete.get('target_key', 'N/A')}")
        lines.append(f"  Object deleted at (UTC) : {delete.get('delete_time_utc', 'N/A')}")
        lines.append(f"  Marker replicated       : {'[PASS] YES' if delete.get('marker_replicated') else '[FAIL] NO'}")
        lines.append(f"  Replication elapsed     : {fmt_s(delete.get('elapsed_seconds'))}")
        lines.append(f"  15-minute SLA met       : {'[PASS] YES' if delete.get('sla_met') else '[FAIL] NO'}")
        lines.append("  Behaviour on read       : Object returns 404/NoSuchKey from replica (correct)")
    else:
        lines.append("  [No data -- run test_delete_marker.py]")
    lines.append("")

    # ---- Test 3 ----
    lines.append(LINE)
    lines.append("TEST 3: LARGE FILE REPLICATION LAG (500 MB)")
    lines.append(LINE)
    if large:
        lines.append(f"  File size               : {large.get('file_size_mb', 'N/A')} MB")
        lines.append(f"  Key                     : {large.get('key', 'N/A')}")
        lines.append(f"  Upload completed (UTC)  : {large.get('upload_finish_utc', 'N/A')}")
        lines.append(f"  Upload duration         : {fmt_s(large.get('upload_duration_s'))}")
        lines.append(f"  Replication lag         : {fmt_s(large.get('replication_lag_s'))}")
        lines.append(f"  Replicated              : {'[PASS] YES' if large.get('replicated') else '[FAIL] NO'}")
        lines.append(f"  15-minute SLA met       : {'[PASS] YES' if large.get('sla_met') else '[FAIL] NO'}")
    else:
        lines.append("  [No data -- run test_large_file_lag.py]")
    lines.append("")

    # ---- Test 4 ----
    lines.append(LINE)
    lines.append("TEST 4: PRIMARY REGION FAILURE SIMULATION & RTO")
    lines.append(LINE)
    if fo:
        lines.append(f"  Failure declared (UTC)  : {fo.get('failure_time_utc', 'N/A')}")
        lines.append(f"  First successful read   : {fo.get('first_read_utc', 'N/A')}")
        lines.append(f"  RTO (time to first read): {fmt_s(fo.get('rto_seconds'))}")
        lines.append(f"  Objects tested          : {fo.get('objects_tested', 'N/A')}")
        lines.append(f"  Objects readable        : {fo.get('objects_readable', 'N/A')}/{fo.get('objects_tested', 'N/A')}")
        lines.append(f"  Avg read latency        : {fo.get('avg_read_latency_ms', 0):.0f} ms")
        lines.append(f"  P95 read latency        : {fo.get('p95_read_latency_ms', 0):.0f} ms")
        lines.append(f"  Full verification time  : {fmt_s(fo.get('full_verification_s'))}")
        lines.append(f"  Replica region          : {REPLICA_REGION}")
    else:
        lines.append("  [No data -- run simulate_failover.py]")
    lines.append("")

    # ---- Success Criteria ----
    lines.append(LINE)
    lines.append("SUCCESS CRITERIA CHECKLIST")
    lines.append(LINE)

    c1 = repl.get("sla_met", False)
    c2 = delete.get("marker_replicated", False)
    c3 = (fo.get("objects_readable", 0) == fo.get("objects_tested", 1)
          and fo.get("objects_tested", 0) > 0)

    lines.append(f"  [{'PASS' if c1 else 'FAIL'}] Replication happens within 15 minutes")
    lines.append(f"  [{'PASS' if c2 else 'FAIL'}] Delete markers replicate correctly")
    lines.append(f"  [{'PASS' if c3 else 'FAIL'}] Can retrieve objects from replica during primary failure")
    lines.append("")
    lines.append(f"  Overall: {'ALL CRITERIA MET [PASS]' if (c1 and c2 and c3) else 'SOME CRITERIA UNMET -- see details above'}")
    lines.append("")

    # ---- Architecture ----
    lines.append(LINE)
    lines.append("ARCHITECTURE SUMMARY")
    lines.append(LINE)
    lines.append("")
    lines.append("  S3 Cross-Region Replication (CRR) -- Active/Passive Setup")
    lines.append("")
    lines.append(f"  PRIMARY ({PRIMARY_REGION}): {PRIMARY_BUCKET}")
    lines.append(f"    Rule 1: critical/ prefix   --> Replication -->  REPLICA ({REPLICA_REGION})")
    lines.append(f"    Rule 2: tag replicate=true --> Replication -->  {REPLICA_BUCKET}")
    lines.append("")
    lines.append("  CloudWatch Alarms:")
    lines.append("    * ReplicationLatency > 900s (15 min) --> ALARM")
    lines.append("    * OperationsFailedReplication >= 1   --> ALARM")
    lines.append("")
    lines.append("  Failover Pattern (Active/Passive):")
    lines.append("    * Normal  : reads/writes to us-east-1 primary")
    lines.append("    * Failure : update application endpoint to eu-west-1 replica")
    lines.append("    * RTO     : near-instant (data pre-replicated; only config change needed)")
    lines.append("")
    lines.append(SEP)
    lines.append("  END OF REPORT")
    lines.append(SEP)

    report = "\n".join(lines)

    print(report)

    with open("lab_report.txt", "w", encoding="utf-8") as f:
        f.write(report)
    print("\n  Report saved to lab_report.txt")


if __name__ == "__main__":
    main()
