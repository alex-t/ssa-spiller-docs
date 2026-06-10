#!/usr/bin/env python3
"""
SSA Spiller Test CFG Analysis Tool

This script analyzes MIR test files for the SSA register spiller by:
1. Finding all *.mir files in a directory
2. Parsing the RUN: line to get the compilation command
3. Running each test under GDB with breakpoints to capture CFG
4. Generating PDF visualizations of CFG before and after spilling
"""

import os
import sys
import subprocess
import re
import argparse
import glob
from pathlib import Path


def parse_run_line(mir_file):
    """
    Parse the RUN: line from a MIR file to extract the compilation command.
    
    Returns: The command line as a string, or None if not found.
    """
    with open(mir_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('# RUN:'):
                # Remove '# RUN:' prefix and expand %s to the file path
                cmd = line[7:].strip()
                cmd = cmd.replace('%s', str(mir_file))
                # Remove pipe to FileCheck if present
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


def run_test_with_gdb(cmd, mir_file, output_dir):
    """
    Run the test under GDB with breakpoints to capture CFG dot files.
    
    Breakpoints:
    - Line 174: Before spilling (viewCFG → before.dot)
    - Line 294: After spilling (viewCFG → spilled.dot)
    """
    func_name = extract_function_name(mir_file)
    if not func_name:
        print(f"  ⚠️  Could not extract function name from {mir_file}")
        return None, None
    
    # Prepare GDB commands
    # Note: We use 'p' (print) instead of 'call' to invoke viewCFG()
    gdb_commands = f"""
set pagination off
set confirm off
set print pretty on
break AMDGPUSSARegisterSpiller.cpp:174
commands
silent
p MF.viewCFG()
continue
end
break AMDGPUSSARegisterSpiller.cpp:294
commands
silent
p MF.viewCFG()
continue
end
run
quit
"""
    
    # Write GDB commands to a temporary file
    gdb_script = output_dir / 'gdb_commands.txt'
    with open(gdb_script, 'w') as f:
        f.write(gdb_commands)
    
    # Run under GDB
    print(f"  🔍 Running under GDB...")
    full_cmd = f"gdb --batch -x {gdb_script} --args {cmd} -o /dev/null"
    
    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Parse output to find dot file locations
        output = result.stderr + result.stdout
        
        # Find all dot files with pattern: /tmp/mf<func_name>-*.dot
        dot_pattern = rf'/tmp/mf{func_name}-[a-f0-9]+\.dot'
        dot_files = re.findall(dot_pattern, output)
        
        if len(dot_files) >= 2:
            return dot_files[0], dot_files[1]
        elif len(dot_files) == 1:
            print(f"  ⚠️  Only found one CFG dot file (expected 2)")
            return dot_files[0], None
        else:
            print(f"  ⚠️  No CFG dot files found in GDB output")
            print(f"  Debug: Looking for pattern {dot_pattern}")
            # Print first 50 lines of output for debugging
            lines = output.split('\n')[:50]
            for line in lines:
                if 'dot' in line.lower() or 'tmp' in line:
                    print(f"    {line}")
            return None, None
    
    except subprocess.TimeoutExpired:
        print(f"  ❌ GDB execution timed out")
        return None, None
    except Exception as e:
        print(f"  ❌ Error running GDB: {e}")
        return None, None


def generate_pdf(dot_file, output_pdf):
    """
    Generate a PDF from a dot file using the dot command.
    """
    if not dot_file or not os.path.exists(dot_file):
        return False
    
    try:
        subprocess.run(
            ['dot', '-Tpdf', '-o', str(output_pdf), dot_file],
            check=True,
            capture_output=True,
            timeout=10
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Error generating PDF: {e}")
        return False
    except FileNotFoundError:
        print(f"  ❌ 'dot' command not found. Please install graphviz.")
        return False
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return False


def analyze_test(mir_file, output_dir):
    """
    Analyze a single MIR test file.
    """
    print(f"\n📋 Analyzing: {mir_file.name}")
    
    # Parse RUN line
    cmd = parse_run_line(mir_file)
    if not cmd:
        print(f"  ❌ No RUN: line found")
        return False
    
    print(f"  ✓ Parsed command: {cmd[:80]}...")
    
    # Extract function name
    func_name = extract_function_name(mir_file)
    if not func_name:
        print(f"  ❌ Could not extract function name")
        return False
    
    print(f"  ✓ Function name: {func_name}")
    
    # Run under GDB to capture CFG
    dot_before, dot_after = run_test_with_gdb(cmd, mir_file, output_dir)
    
    # Generate PDFs
    success = False
    if dot_before:
        pdf_before = output_dir / f"{func_name}_before.pdf"
        if generate_pdf(dot_before, pdf_before):
            print(f"  ✅ Generated: {pdf_before}")
            success = True
        else:
            print(f"  ❌ Failed to generate before PDF")
    
    if dot_after:
        pdf_after = output_dir / f"{func_name}_spilled.pdf"
        if generate_pdf(dot_after, pdf_after):
            print(f"  ✅ Generated: {pdf_after}")
            success = True
        else:
            print(f"  ❌ Failed to generate spilled PDF")
    
    return success


def main():
    parser = argparse.ArgumentParser(
        description='Analyze SSA spiller MIR tests and generate CFG visualizations'
    )
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='Directory containing *.mir test files (default: current directory)'
    )
    parser.add_argument(
        '-o', '--output',
        default='cfg_analysis',
        help='Output directory for PDF files (default: cfg_analysis)'
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    test_dir = Path(args.directory).resolve()
    output_dir = Path(args.output).resolve()
    
    if not test_dir.exists() or not test_dir.is_dir():
        print(f"❌ Error: Directory not found: {test_dir}")
        return 1
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all MIR files
    mir_files = sorted(test_dir.glob('*.mir'))
    
    if not mir_files:
        print(f"❌ No *.mir files found in {test_dir}")
        return 1
    
    print(f"🔍 Found {len(mir_files)} MIR test file(s) in {test_dir}")
    print(f"📁 Output directory: {output_dir}")
    
    # Analyze each test
    success_count = 0
    for mir_file in mir_files:
        if analyze_test(mir_file, output_dir):
            success_count += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"✅ Successfully analyzed {success_count}/{len(mir_files)} tests")
    print(f"📁 Output saved to: {output_dir}")
    print(f"{'='*60}")
    
    return 0 if success_count > 0 else 1


if __name__ == '__main__':
    sys.exit(main())

