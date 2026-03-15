#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test suite for standalone raytracer executable.
Tests the C++ raytracer binary directly.
"""

import sys
import os
import subprocess
import json
import tempfile
import shutil


def get_executable_path():
    """Get the path to the raytracer executable"""
    # Try common locations (cross-platform)
    possible_paths = [
        os.path.join(os.path.dirname(__file__), '..', 'build', 'bin', 'raytracer'),
        os.path.join(os.path.dirname(__file__), '..', 'bin', 'raytracer'),
        'raytracer',  # Assume in PATH
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    raise FileNotFoundError("raytracer executable not found. Please build the project first.")


def run_renderer(args, description):
    """Run the raytracer executable with given arguments"""
    exe_path = get_executable_path()
    
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {exe_path} {' '.join(args)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(
            [exe_path] + args,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        if stdout:
            print(f"STDOUT: {stdout}")
        if stderr:
            print(f"STDERR: {stderr}")
        
        if result.returncode == 0:
            print(f"✓ PASSED: {description}")
            return True
        else:
            print(f"✗ FAILED: {description} - Exit code: {result.returncode}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"✗ FAILED: {description} - Timeout")
        return False
    except Exception as e:
        print(f"✗ FAILED: {description} - {e}")
        return False


def test_help():
    """Test help output"""
    assert run_renderer(['--help'], "Help output"), "Help output test failed"


def test_version():
    """Test version output"""
    assert run_renderer(['--version'], "Version output"), "Version output test failed"


def test_test_mode():
    """Test built-in test mode"""
    assert run_renderer(['--test'], "Built-in test mode"), "Built-in test mode test failed"


def test_simple_scene():
    """Test simple scene rendering"""
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, 'standalone_simple.png')
    
    args = [
        '--output', output_file,
        '--width', '400',
        '--height', '300',
        '--samples', '16',
        '--look_from', '0,0,5',
        '--look_at', '0,0,0',
        '--vup', '0,-1,0',
        '--vfov', '40',
        '--aspect_ratio', '1.33',
        '--aperture', '0.0',
        '--focus_dist', '5.0',
        '--sphere', '0,0,0,1',
        '--material', '0,0,0,0,0.5,0.5,0.5'
    ]
    
    assert run_renderer(args, "Simple scene rendering"), "Simple scene rendering test failed"


def test_cornell_box():
    """Test Cornell Box rendering"""
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, 'standalone_cornell_box.png')
    
    args = [
        '--output', output_file,
        '--width', '400',
        '--height', '300',
        '--samples', '16',
        '--look_from', '2,3,5',
        '--look_at', '0,0,0',
        '--vup', '0,1,0',
        '--vfov', '40',
        '--aspect_ratio', '1.33',
        '--aperture', '0.0',
        '--focus_dist', '5.0',
        # Floor (white)
        '--triangle', '-2,-2,-2', '2,-2,-2', '2,-2,2', '0',
        '--triangle', '-2,-2,-2', '2,-2,2', '-2,-2,2', '0',
        # Ceiling (white)
        '--triangle', '-2,2,-2', '-2,2,2', '2,2,2', '0',
        '--triangle', '-2,2,-2', '2,2,2', '2,2,-2', '0',
        # Back wall (white)
        '--triangle', '-2,-2,-2', '-2,2,-2', '2,2,-2', '0',
        '--triangle', '-2,-2,-2', '2,2,-2', '2,-2,-2', '0',
        # Left wall (red)
        '--triangle', '-2,-2,-2', '-2,-2,2', '-2,2,2', '1',
        '--triangle', '-2,-2,-2', '-2,2,2', '-2,2,-2', '1',
        # Right wall (green)
        '--triangle', '2,-2,-2', '2,2,-2', '2,2,2', '2',
        '--triangle', '2,-2,-2', '2,2,2', '2,-2,2', '2',
        # Light
        '--triangle', '-0.5,1.98,-0.5', '0.5,1.98,-0.5', '0.5,1.98,0.5', '3',
        '--triangle', '-0.5,1.98,-0.5', '0.5,1.98,0.5', '-0.5,1.98,0.5', '3',
    ]
    
    assert run_renderer(args, "Cornell Box rendering"), "Cornell Box rendering test failed"


def test_multiple_objects():
    """Test multiple objects"""
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, 'standalone_multiple_objects.png')
    
    args = [
        '--output', output_file,
        '--width', '400',
        '--height', '300',
        '--samples', '16',
        '--look_from', '0,1,5',
        '--look_at', '0,0,0',
        '--vup', '0,1,0',
        '--vfov', '60',
        '--aspect_ratio', '1.33',
        '--aperture', '0.0',
        '--focus_dist', '5.0',
        # Three spheres
        '--sphere', '0,0,0,1', '0',
        '--sphere', '2,0,0,1', '1',
        '--sphere', '-2,0,0,1', '2',
    ]
    
    assert run_renderer(args, "Multiple objects rendering"), "Multiple objects rendering test failed"


def test_performance():
    """Test performance with higher sample count"""
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, 'standalone_performance.png')
    
    args = [
        '--output', output_file,
        '--width', '400',
        '--height', '300',
        '--samples', '100',
        '--look_from', '0,1,5',
        '--look_at', '0,0,0',
        '--vup', '0,1,0',
        '--vfov', '60',
        '--aspect_ratio', '1.33',
        '--aperture', '0.0',
        '--focus_dist', '5.0',
        '--sphere', '0,0,0,1', '0',
        '--sphere', '2,0,0,1', '1',
        '--sphere', '-2,0,0,1', '2',
    ]
    
    assert run_renderer(args, "Performance test (100 samples)"), "Performance test failed"


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("STANDALONE RAYTRACER TEST SUITE")
    print("="*60)
    
    tests = [
        ("Help output", test_help),
        ("Version output", test_version),
        ("Built-in test mode", test_test_mode),
        ("Simple scene rendering", test_simple_scene),
        ("Cornell Box rendering", test_cornell_box),
        ("Multiple objects rendering", test_multiple_objects),
        ("Performance test (100 samples)", test_performance),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ EXCEPTION: {name} - {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)
    
    print(f"Total: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    for name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {name}: {'PASSED' if result else 'FAILED'}")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
