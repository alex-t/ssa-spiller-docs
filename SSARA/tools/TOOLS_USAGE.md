# SSA Register Spiller Analysis Tools - Usage Guide

## Overview

This directory contains Python and PowerShell scripts for analyzing, visualizing, and debugging the SSA-aware register spiller implementation.

---

## 📊 CFG Visualization Tools

### 1. `run_viewcfg_tests.py` - Automated CFG Generation

**Purpose:** Automatically generates Control Flow Graph (CFG) visualizations by running MIR tests under GDB.

**How it works:**
- Runs `.mir` test files under GDB
- Sets breakpoints at key spilling points
- Automatically calls `MF.viewCFG()` to dump CFG to `.dot` files
- Captures CFG both before and after spilling

**Usage:**
```bash
# Run on SSASpiller test directory
cd /path/to/llvm-project
python3 ../ssa-spiller-docs/tools/run_viewcfg_tests.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/

# Or on a specific test directory
python3 ../ssa-spiller-docs/tools/run_viewcfg_tests.py \
  llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater/
```

**Output:**
- Dot files in `/tmp/` with names like `cfg.function_name.dot`
- Console output showing progress and success/failure for each test

**Breakpoint Configuration:**
The script sets breakpoints at (you can customize in the script):
- Line 174: Before spilling
- Line 294: After spilling

**Requirements:**
- GDB installed
- LLVM built with debug symbols (`-DCMAKE_BUILD_TYPE=Debug` or `RelWithDebInfo`)
- Tests must have `# RUN:` directive

---

### 2. `analyze_spiller_cfg.py` - CFG Analysis & PDF Generation

**Purpose:** Converts GDB-generated `.dot` files into beautiful side-by-side PDF comparisons showing CFG transformations.

**How it works:**
- Scans MIR test files for `# RUN:` commands
- Runs each test under GDB with viewCFG breakpoints
- Converts `.dot` files to PDFs using Graphviz
- Creates before/after comparison visualizations

**Usage:**
```bash
# Analyze all tests in SSASpiller directory
cd /path/to/llvm-project
python3 ../ssa-spiller-docs/tools/analyze_spiller_cfg.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/

# Analyze a specific test file
python3 ../ssa-spiller-docs/tools/analyze_spiller_cfg.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/spill-dominated-branches.mir
```

**Output:**
- PDF files in `cfg_analysis/` directory:
  - `test_name_before.pdf` - CFG before spilling
  - `test_name_spilled.pdf` - CFG after spilling and SSA repair
- Shows basic blocks, edges, dominance relationships, PHI nodes

**Requirements:**
- GDB
- Graphviz (`dot` command)
- Python 3

**Install Graphviz:**
```bash
# Ubuntu/Debian
sudo apt install graphviz

# macOS
brew install graphviz
```

---

### 3. `analyze_spiller_tests.py` - Test Results Analysis

**Purpose:** Analyzes test execution and provides detailed statistics about spilling behavior.

**How it works:**
- Runs MIR tests with `-debug-only=amdgpu-ssa-spiller`
- Parses debug output to extract metrics
- Reports statistics on spills, reloads, CFG transformations

**Usage:**
```bash
# Analyze all SSASpiller tests
cd /path/to/llvm-project
python3 ../ssa-spiller-docs/tools/analyze_spiller_tests.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/

# Analyze specific test
python3 ../ssa-spiller-docs/tools/analyze_spiller_tests.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/spill-linear-dominated.mir
```

**Output:**
- Per-test statistics:
  - Number of spills/reloads
  - Dominated vs reachable uses
  - CFG transformations (splits, PHI insertions)
  - Register pressure before/after
- Summary across all tests
- Failure reports with error details

**Requirements:**
- LLVM built with `-DLLVM_ENABLE_ASSERTIONS=ON`
- Debug build recommended for detailed output

---

## 📑 Presentation & Documentation Tools

### 4. PowerShell Scripts for Marp Presentations

These scripts help export and manage Marp-based presentations (Markdown → PDF/HTML).

#### `export_presentation.ps1`
**Purpose:** Export Marp presentation to PDF/HTML with custom styling.

**Usage:**
```powershell
# On Windows with PowerShell
.\export_presentation.ps1 -InputFile "SSA_Spiller_Presentation.md" -Format pdf

# Export to HTML
.\export_presentation.ps1 -InputFile "SSA_Spiller_Presentation.md" -Format html
```

#### `export_locally.ps1`
**Purpose:** Export presentation using local Marp CLI installation.

**Usage:**
```powershell
.\export_locally.ps1 "SSA_Spiller_Presentation_fixed.md"
```

#### `copy_to_windows.ps1`
**Purpose:** Copy files from WSL to Windows filesystem for presentation export.

**Usage:**
```powershell
# From WSL
.\copy_to_windows.ps1 /mnt/c/Users/YourName/Documents/

# Copies presentation files to Windows for easier sharing
```

#### `convert_mermaid.ps1`
**Purpose:** Convert Mermaid diagrams in Markdown to images for presentations.

**Usage:**
```powershell
.\convert_mermaid.ps1 -InputFile "CFG_EXAMPLE_MERMAID.md"
```

**Requirements:**
- Marp CLI installed: `npm install -g @marp-team/marp-cli`
- For Mermaid: `npm install -g @mermaid-js/mermaid-cli`

---

## 🔧 Configuration Files

### `CMakePresets.json`
**Purpose:** Custom CMake build presets for LLVM development.

**Usage:**
```bash
# Copy to llvm/ directory
cp ../ssa-spiller-docs/tools/CMakePresets.json llvm/

# Use preset
cmake --preset=<preset-name>
```

**Common presets:**
- `debug` - Debug build with assertions
- `release` - Optimized release build
- `relwithdebinfo` - Optimized with debug info

---

## 📁 Output Directories

### `cfg_analysis/`
Contains PDF visualizations of test CFGs:
- `test_name_before.pdf` - CFG before spilling
- `test_name_spilled.pdf` - CFG after spilling

**Useful for:**
- Verifying CFG transformations (split-before-use)
- Understanding dominance relationships
- Debugging PHI insertion points
- Visualizing reload placement

---

## 🎯 Common Workflows

### Workflow 1: Debug a Failing Test

```bash
# 1. Run test with debug output
cd llvm-project
./bin/llc -march=amdgcn -mcpu=gfx900 \
  -debug-only=amdgpu-ssa-spiller \
  llvm/test/CodeGen/AMDGPU/SSASpiller/failing-test.mir

# 2. Generate CFG visualization
python3 ../ssa-spiller-docs/tools/analyze_spiller_cfg.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/failing-test.mir

# 3. View the PDFs
xdg-open cfg_analysis/test_failing_test_before.pdf
xdg-open cfg_analysis/test_failing_test_spilled.pdf

# 4. Compare before/after to identify issue
```

### Workflow 2: Analyze All Tests

```bash
# 1. Generate statistics
python3 ../ssa-spiller-docs/tools/analyze_spiller_tests.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/ > test-stats.txt

# 2. Generate all CFG visualizations
python3 ../ssa-spiller-docs/tools/analyze_spiller_cfg.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/

# 3. Review PDFs in cfg_analysis/
ls -lh cfg_analysis/
```

### Workflow 3: Verify a Code Change

```bash
# 1. Before making changes, generate baseline CFGs
python3 ../ssa-spiller-docs/tools/analyze_spiller_cfg.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/
mv cfg_analysis cfg_analysis_baseline

# 2. Make your code changes
# ... edit AMDGPUSSARegisterSpiller.cpp ...

# 3. Rebuild
ninja AMDGPUSSARegisterSpiller

# 4. Generate new CFGs
python3 ../ssa-spiller-docs/tools/analyze_spiller_cfg.py \
  llvm/test/CodeGen/AMDGPU/SSASpiller/

# 5. Compare baseline vs new
diff -r cfg_analysis_baseline/ cfg_analysis/
# Or visually compare PDFs
```

### Workflow 4: Create Presentation

```bash
# 1. Write presentation in Markdown (Marp format)
vim ../ssa-spiller-docs/SSA_Spiller_Presentation.md

# 2. Export to PDF (Windows/PowerShell)
cd ../ssa-spiller-docs/tools
.\export_presentation.ps1 -InputFile "../SSA_Spiller_Presentation.md" -Format pdf

# 3. Share the PDF
```

---

## 🐛 Troubleshooting

### GDB Breakpoints Not Hitting

**Problem:** `run_viewcfg_tests.py` completes but no `.dot` files generated.

**Solution:**
```bash
# Check debug symbols
nm ./bin/llc | grep AMDGPUSSARegisterSpiller

# If no symbols, rebuild with debug info
cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
ninja
```

### Graphviz Not Found

**Problem:** `analyze_spiller_cfg.py` fails with "dot command not found".

**Solution:**
```bash
# Install Graphviz
sudo apt install graphviz  # Ubuntu/Debian
brew install graphviz      # macOS
```

### Test Timeouts

**Problem:** Tests timeout in GDB.

**Solution:**
- Increase timeout in `run_viewcfg_tests.py` (line 117)
- Use simpler/smaller test cases
- Check for infinite loops in spiller logic

### Wrong Line Numbers

**Problem:** Breakpoints set at wrong locations after code changes.

**Solution:**
- Update line numbers in `run_viewcfg_tests.py` (lines 206-207)
- Or use function breakpoints: `break AMDGPUSSARegisterSpiller::spillAndReload`

---

## 📝 Customization

### Adding Custom Breakpoints

Edit `run_viewcfg_tests.py`:
```python
# Line 205-208
breakpoints = [
    ('AMDGPUSSARegisterSpiller.cpp', 174),  # Before spilling
    ('AMDGPUSSARegisterSpiller.cpp', 294),  # After spilling
    ('AMDGPUSSARegisterSpiller.cpp', 832),  # Before reachable use handling
]
```

### Custom CFG Styling

Modify Graphviz attributes in `analyze_spiller_cfg.py` to change:
- Node colors
- Edge styles
- Font sizes
- Layout algorithm (dot, circo, fdp, etc.)

### Custom Test Analysis

Extend `analyze_spiller_tests.py` to extract additional metrics:
- PHI node counts
- Subregister spill statistics
- Register pressure per block
- Hoist-to-NCD success rate

---

## 🔗 Related Documentation

- **NOTES.md** - Complete technical diary and current status
- **SPILL_PLACEMENT_DESIGN.md** - Algorithm design and rationale
- **SSA_SPILLER_TEST_PATTERNS.md** - Test case patterns
- **IMPLEMENTATION_PLAN.md** - Implementation roadmap

---

## 📞 Support

For issues or questions:
1. Check NOTES.md for context
2. Review test output with `-debug-only=amdgpu-ssa-spiller`
3. Generate CFG visualizations to understand behavior
4. Compare against working test cases

---

**Last Updated:** 2025-11-19
**Location:** `/path/to/ssa-spiller-docs/tools/`

