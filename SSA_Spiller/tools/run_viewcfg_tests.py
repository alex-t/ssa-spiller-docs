#!/usr/bin/env python3
"""
LLVM MIR Test Viewer - Automated CFG Visualization

This script runs LLVM MIR tests under GDB and automatically calls MF.viewCFG()
at specified breakpoints to generate CFG dot files.

Usage:
    python3 run_viewcfg_tests.py [directory]

Where directory is optional (defaults to current directory).
"""

import os
import sys
import subprocess
import shlex
import tempfile
import re
from pathlib import Path


def find_run_command(mir_file):
    """
    Find and extract the RUN: command from a MIR test file.
    
    Returns the command as a string, or None if not found.
    The RUN: line format is typically:
        # RUN: llc -mtriple=... %s | FileCheck %s
    """
    with open(mir_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Look for RUN: directive
            if line.startswith('# RUN:') or line.startswith('#RUN:'):
                # Remove '# RUN:' or '#RUN:' prefix
                if '# RUN:' in line:
                    cmd = line.split('# RUN:', 1)[1].strip()
                else:
                    cmd = line.split('#RUN:', 1)[1].strip()
                
                # Replace %s with the actual file path
                cmd = cmd.replace('%s', str(mir_file))
                
                # Remove pipe to FileCheck and everything after
                if '|' in cmd:
                    cmd = cmd.split('|')[0].strip()
                
                return cmd
    
    return None


def create_gdb_script(breakpoints):
    """
    Create a temporary GDB script file with breakpoints that call MF.viewCFG().
    
    Args:
        breakpoints: List of tuples (file:line), e.g. [("Foo.cpp", 123), ...]
    
    Returns:
        Path to the temporary GDB script file.
    """
    # Create temporary file for GDB commands
    fd, script_path = tempfile.mkstemp(suffix='.gdb', text=True)
    
    with os.fdopen(fd, 'w') as f:
        # GDB setup commands
        f.write("set pagination off\n")
        f.write("set confirm off\n")
        f.write("set print pretty on\n")
        f.write("\n")
        
        # Set breakpoints with automatic actions
        for source_file, line_num in breakpoints:
            f.write(f"break {source_file}:{line_num}\n")
            f.write("commands\n")
            f.write("  silent\n")
            f.write("  printf \"[viewCFG] Breakpoint hit at %s:%d\\n\", __FILE__, __LINE__\n")
            f.write("  p MF.viewCFG()\n")
            f.write("  continue\n")
            f.write("end\n")
            f.write("\n")
        
        # Run the program
        f.write("run\n")
        f.write("quit\n")
    
    return script_path


def run_test_under_gdb(command, gdb_script):
    """
    Execute a test command under GDB with the given script.
    
    Args:
        command: Command string to run (will be parsed with shlex.split)
        gdb_script: Path to GDB script file
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Parse command safely using shlex
        cmd_args = shlex.split(command)
        
        # Build GDB command: gdb -q -x script.gdb --args <command>
        gdb_cmd = ['gdb', '-q', '-batch', '-x', gdb_script, '--args'] + cmd_args
        
        # Redirect output to /dev/null to suppress test output
        # We only care about GDB's viewCFG() calls which write to /tmp
        result = subprocess.run(
            gdb_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60
        )
        
        return result.returncode == 0
    
    except subprocess.TimeoutExpired:
        print("  (timeout)")
        return False
    except Exception as e:
        print(f"  (error: {e})")
        return False


def process_mir_file(mir_file, breakpoints):
    """
    Process a single MIR test file.
    
    Args:
        mir_file: Path to the .mir file
        breakpoints: List of (source_file, line_number) tuples for GDB
    
    Returns:
        True if successful, False otherwise
    """
    # Extract filename for progress message
    filename = mir_file.name
    
    print(f"Running test for {filename} ...", end=' ', flush=True)
    
    # Step 1: Find RUN: command
    command = find_run_command(mir_file)
    if not command:
        print("(no RUN: line found)")
        return False
    
    # Step 2: Create GDB script
    gdb_script = None
    try:
        gdb_script = create_gdb_script(breakpoints)
        
        # Step 3: Run under GDB
        success = run_test_under_gdb(command, gdb_script)
        
        if success:
            print("done")
        else:
            print("failed")
        
        return success
    
    finally:
        # Clean up temporary GDB script
        if gdb_script and os.path.exists(gdb_script):
            try:
                os.unlink(gdb_script)
            except:
                pass


def main():
    """
    Main entry point.
    
    Usage: python3 run_viewcfg_tests.py [directory]
    """
    # Parse command-line arguments
    if len(sys.argv) > 1:
        test_dir = Path(sys.argv[1])
    else:
        test_dir = Path('.')
    
    # Resolve to absolute path
    test_dir = test_dir.resolve()
    
    # Validate directory
    if not test_dir.exists() or not test_dir.is_dir():
        print(f"Error: Directory not found: {test_dir}", file=sys.stderr)
        return 1
    
    # Find all .mir files
    mir_files = sorted(test_dir.glob('*.mir'))
    
    if not mir_files:
        print(f"No .mir files found in {test_dir}", file=sys.stderr)
        return 1
    
    # Define breakpoints (source_file, line_number)
    # These are the locations where we want to call MF.viewCFG()
    breakpoints = [
        ('AMDGPUSSARegisterSpiller.cpp', 174),  # Before spilling
        ('AMDGPUSSARegisterSpiller.cpp', 294),  # After spilling
    ]
    
    print(f"Found {len(mir_files)} test(s) in {test_dir}")
    print(f"Breakpoints: {breakpoints}")
    print()
    
    # Process each test
    success_count = 0
    for mir_file in mir_files:
        if process_mir_file(mir_file, breakpoints):
            success_count += 1
    
    # Summary
    print()
    print(f"Results: {success_count}/{len(mir_files)} tests completed successfully")
    
    # Exit with appropriate code
    return 0 if success_count == len(mir_files) else 1


if __name__ == '__main__':
    sys.exit(main())

