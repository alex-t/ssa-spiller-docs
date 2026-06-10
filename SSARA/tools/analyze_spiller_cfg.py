#!/usr/bin/env python3
"""
LLVM SSA Spiller CFG Analyzer

This script runs LLVM MIR tests under GDB, captures CFG visualizations,
and generates PDF files showing the CFG before and after spilling.

Usage:
    python3 analyze_spiller_cfg.py [directory] [-o output_dir]

Where:
    directory   - Directory containing .mir test files (default: current directory)
    -o          - Output directory for PDF files (default: cfg_analysis)
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
    """
    with open(mir_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('# RUN:') or line.startswith('#RUN:'):
                # Remove '# RUN:' prefix
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


def extract_function_name(mir_file):
    """
    Extract the function name from the MIR file.
    Looks for 'name: <function_name>' in the machine function definition.
    """
    with open(mir_file, 'r') as f:
        for line in f:
            match = re.match(r'^name:\s+(\w+)', line.strip())
            if match:
                return match.group(1)
    return None


def create_gdb_script(breakpoints, output_markers=True):
    """
    Create a temporary GDB script file with breakpoints that call MF.viewCFG().
    
    Args:
        breakpoints: List of tuples (file, line), e.g. [("Foo.cpp", 123), ...]
        output_markers: If True, print markers to help identify which breakpoint fired
    
    Returns:
        Path to the temporary GDB script file.
    """
    fd, script_path = tempfile.mkstemp(suffix='.gdb', text=True)
    
    with os.fdopen(fd, 'w') as f:
        # GDB setup
        f.write("set pagination off\n")
        f.write("set confirm off\n")
        f.write("set print pretty on\n")
        f.write("\n")
        
        # Set breakpoints
        for idx, (source_file, line_num) in enumerate(breakpoints):
            f.write(f"break {source_file}:{line_num}\n")
            f.write("commands\n")
            f.write("  silent\n")
            if output_markers:
                f.write(f'  printf "===CFG_MARKER_{idx}===\\n"\n')
            f.write("  p MF.viewCFG()\n")
            f.write("  continue\n")
            f.write("end\n")
            f.write("\n")
        
        f.write("run\n")
        f.write("quit\n")
    
    return script_path


def run_test_under_gdb(command, gdb_script, func_name):
    """
    Execute test under GDB and extract CFG dot file paths.
    
    Returns:
        Tuple of (dot_before, dot_after) file paths, or (None, None) on error
    """
    try:
        # Parse command safely
        cmd_args = shlex.split(command)
        
        # Replace 'llc' with full path to Debug build
        # Look for llc in build/Debug/bin/llc
        if cmd_args[0] == 'llc' or cmd_args[0].endswith('/llc'):
            # Find the script's directory (assuming we're in llvm-project root)
            script_dir = Path(__file__).parent
            debug_llc = script_dir / 'build' / 'Debug' / 'bin' / 'llc'
            if debug_llc.exists():
                cmd_args[0] = str(debug_llc)
        
        # Build GDB command
        gdb_cmd = ['gdb', '-q', '-batch', '-x', gdb_script, '--args'] + cmd_args
        
        # Run GDB and capture output (both stdout and stderr)
        result = subprocess.run(
            gdb_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60
        )
        
        # Combine stdout and stderr as viewCFG() writes to stderr
        output = result.stdout + result.stderr
        
        # Extract dot files
        # Note: processFunction is called twice (SGPR pass, then VGPR pass)
        # viewCFG() output appears much later in GDB output (after subprocess finishes)
        # We want the VGPR pass (last 2 dot files)
        dot_before = None
        dot_after = None
        
        # Find all dot files
        dot_pattern = r"Writing '(/tmp/mf[^']+\.dot)'"
        all_dot_files = re.findall(dot_pattern, output)
        
        # We expect 4 dot files: SGPR before, SGPR after, VGPR before, VGPR after
        # We want the last 2 (VGPR pass)
        if len(all_dot_files) >= 4:
            dot_before = all_dot_files[-2]  # Third dot file (VGPR before)
            dot_after = all_dot_files[-1]   # Fourth dot file (VGPR after)
        elif len(all_dot_files) == 2:
            # Only one pass ran (e.g., only VGPR needed)
            dot_before = all_dot_files[0]
            dot_after = all_dot_files[1]
        elif len(all_dot_files) > 0:
            # Unexpected number, take last 2 or what we have
            dot_before = all_dot_files[-2] if len(all_dot_files) >= 2 else None
            dot_after = all_dot_files[-1]
        
        # Fallback: if markers didn't work, try to find dot files sequentially
        if not dot_before and not dot_after:
            all_matches = re.findall(dot_pattern, output)
            if len(all_matches) >= 2:
                dot_before, dot_after = all_matches[0], all_matches[1]
            elif len(all_matches) == 1:
                dot_before = all_matches[0]
        
        return dot_before, dot_after
    
    except subprocess.TimeoutExpired:
        print(f"  Error: GDB execution timed out")
        return None, None
    except Exception as e:
        print(f"  Error: {e}")
        return None, None


def generate_pdf(dot_file, output_pdf):
    """
    Generate a PDF from a dot file using the dot command.
    Returns True on success, False on failure.
    """
    if not dot_file or not os.path.exists(dot_file):
        return False
    
    try:
        subprocess.run(
            ['dot', '-Tpdf', '-o', str(output_pdf), dot_file],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10
        )
        return True
    except FileNotFoundError:
        print(f"  Error: 'dot' command not found. Install graphviz: sudo apt install graphviz")
        return False
    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False


def process_mir_file(mir_file, output_dir, breakpoints):
    """
    Process a single MIR test file: run under GDB, capture CFGs, generate PDFs.
    
    Returns:
        Number of PDFs successfully generated (0, 1, or 2)
    """
    filename = mir_file.name
    print(f"\n📋 Processing: {filename}")
    
    # Step 1: Extract function name
    func_name = extract_function_name(mir_file)
    if not func_name:
        print(f"  ❌ Could not extract function name")
        return 0
    print(f"  Function: {func_name}")
    
    # Step 2: Find RUN command
    command = find_run_command(mir_file)
    if not command:
        print(f"  ❌ No RUN: line found")
        return 0
    print(f"  Command: {command[:60]}...")
    
    # Step 3: Create GDB script
    gdb_script = None
    try:
        gdb_script = create_gdb_script(breakpoints)
        
        # Step 4: Run under GDB
        print(f"  🔍 Running under GDB...")
        dot_before, dot_after = run_test_under_gdb(command, gdb_script, func_name)
        
        # Step 5: Generate PDFs
        pdf_count = 0
        
        if dot_before:
            pdf_before = output_dir / f"{func_name}_before.pdf"
            if generate_pdf(dot_before, pdf_before):
                print(f"  ✅ Generated: {pdf_before.name}")
                pdf_count += 1
            else:
                print(f"  ❌ Failed to generate before PDF")
        else:
            print(f"  ⚠️  No 'before' CFG dot file found")
        
        if dot_after:
            pdf_after = output_dir / f"{func_name}_spilled.pdf"
            if generate_pdf(dot_after, pdf_after):
                print(f"  ✅ Generated: {pdf_after.name}")
                pdf_count += 1
            else:
                print(f"  ❌ Failed to generate spilled PDF")
        else:
            print(f"  ⚠️  No 'after' CFG dot file found")
        
        return pdf_count
    
    finally:
        # Clean up GDB script
        if gdb_script and os.path.exists(gdb_script):
            try:
                os.unlink(gdb_script)
            except:
                pass


def main():
    """
    Main entry point.
    
    Usage: python3 analyze_spiller_cfg.py [directory] [-o output_dir]
    """
    # Simple argument parsing
    test_dir = Path('.')
    output_dir = Path('cfg_analysis')
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '-o' and i + 1 < len(args):
            output_dir = Path(args[i + 1])
            i += 2
        else:
            test_dir = Path(args[i])
            i += 1
    
    # Resolve paths
    test_dir = test_dir.resolve()
    output_dir = output_dir.resolve()
    
    # Validate test directory
    if not test_dir.exists() or not test_dir.is_dir():
        print(f"Error: Directory not found: {test_dir}", file=sys.stderr)
        return 1
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all .mir files
    mir_files = sorted(test_dir.glob('*.mir'))
    
    if not mir_files:
        print(f"Error: No .mir files found in {test_dir}", file=sys.stderr)
        return 1
    
    # Define breakpoints (file, line)
    breakpoints = [
        ('AMDGPUSSARegisterSpiller.cpp', 174),  # Before spilling (start of processFunction)
        ('AMDGPUSSARegisterSpiller.cpp', 294),  # After spilling (end of block processing)
    ]
    
    # Print header
    print("="*70)
    print("SSA Spiller CFG Analyzer")
    print("="*70)
    print(f"Test directory:   {test_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Tests found:      {len(mir_files)}")
    print(f"Breakpoints:      {breakpoints}")
    print("="*70)
    
    # Process each test
    total_pdfs = 0
    for mir_file in mir_files:
        pdf_count = process_mir_file(mir_file, output_dir, breakpoints)
        total_pdfs += pdf_count
    
    # Summary
    print("\n" + "="*70)
    print(f"✅ Generated {total_pdfs} PDF files ({total_pdfs // 2} tests visualized)")
    print(f"📁 Output saved to: {output_dir}")
    print("="*70)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

