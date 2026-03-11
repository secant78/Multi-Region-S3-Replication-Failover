"""
Master runner — executes all lab steps in sequence.
Run this single script to complete the entire assignment.

Usage:
    python run_all.py [--skip-large]

Flags:
    --skip-large   Skip the 500 MB upload (saves time; SLA test still runs)
"""

import sys
import time
import importlib


def banner(title):
    print("\n" + "█" * 70)
    print(f"  {title}")
    print("█" * 70)


def run_step(module_name, label):
    banner(f"STEP: {label}")
    mod = importlib.import_module(module_name)
    result = mod.main()
    print(f"\n  ✓ {label} complete")
    return result


def main():
    skip_large = "--skip-large" in sys.argv

    print("\n" + "="*70)
    print("  Assignment 9: Multi-Region S3 Replication — Full Lab Run")
    print("="*70)

    # Step 1 – Infrastructure
    run_step("setup_infrastructure", "Infrastructure Setup (IAM + Buckets + CRR + CloudWatch)")

    # Brief pause for replication configuration to propagate
    print("\n  Waiting 15s for CRR configuration to propagate ...")
    time.sleep(15)

    # Step 2 – Upload 20 files and verify replication
    run_step("upload_and_verify", "Upload 20 Files & Verify Replication")

    # Step 3 – Delete marker test
    run_step("test_delete_marker", "Delete Marker Replication Test")

    # Step 4 – Large file lag test
    if skip_large:
        print("\n  [SKIP] Large file test skipped (--skip-large flag set)")
    else:
        run_step("test_large_file_lag", "500 MB Large File Replication Lag Test")

    # Step 5 – Failover simulation
    run_step("simulate_failover", "Primary Region Failure Simulation & RTO")

    # Step 6 – Report
    run_step("generate_report", "Lab Report Generation")

    print("\n" + "="*70)
    print("  ALL STEPS COMPLETE — See lab_report.txt for full results")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
