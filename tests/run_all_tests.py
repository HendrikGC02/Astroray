#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Master test runner for all Astroray tests.
Executes all test suites and aggregates results.
"""

import sys
import os
import time
import subprocess
from datetime import datetime


def run_python_test(script_path, name):
    """Run a Python test script"""
    print(f"\n{'='*60}")
    print(f"Running: {name}")
    print(f"Script: {script_path}")
    print(f"{'='*60}")
    
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        elapsed = time.time() - start
        
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        
        if result.returncode == 0:
            print(f"✓ PASSED: {name} ({elapsed:.2f}s)")
            return True, elapsed
        else:
            print(f"✗ FAILED: {name} ({elapsed:.2f}s)")
            return False, elapsed
            
    except subprocess.TimeoutExpired:
        print(f"✗ FAILED: {name} - Timeout")
        return False, 300
    except Exception as e:
        print(f"✗ FAILED: {name} - {e}")
        return False, 0


def print_banner(title):
    """Print a formatted banner"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def print_summary(results):
    """Print test summary"""
    print("\n" + "="*60)
    print("  TEST SUMMARY")
    print("="*60)
    
    total = len(results)
    passed = sum(1 for r in results if r[1])
    failed = total - passed
    total_time = sum(r[2] for r in results)
    
    print(f"Total tests:  {total}")
    print(f"Passed:       {passed}")
    print(f"Failed:       {failed}")
    print(f"Total time:   {total_time:.2f}s")
    print("="*60)
    
    print("\nResults:")
    for name, success, elapsed in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        print(f"  {status}: {name} ({elapsed:.2f}s)")
    
    return failed == 0


def main():
    """Main test runner"""
    print("\n" + "="*60)
    print("  ASTRORAY TEST SUITE")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # Get the directory where this script is located
    test_dir = os.path.dirname(os.path.abspath(__file__))
    
    # List of test scripts to run
    test_scripts = [
        ("Python Bindings", os.path.join(test_dir, "test_python_bindings.py")),
        ("Standalone Renderer", os.path.join(test_dir, "test_standalone_renderer.py")),
    ]
    
    # Run all tests
    results = []
    for name, script_path in test_scripts:
        if os.path.exists(script_path):
            success, elapsed = run_python_test(script_path, name)
            results.append((name, success, elapsed))
        else:
            print(f"\n✗ SKIPPED: {name} - Script not found: {script_path}")
            results.append((name, False, 0))
    
    # Print summary
    success = print_summary(results)
    
    print(f"\n  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())