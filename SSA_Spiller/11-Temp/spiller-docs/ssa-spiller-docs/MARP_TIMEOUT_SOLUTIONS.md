# Export SSA Spiller Presentation - Solutions

## Problem
Marp VS Code extension times out after 30 seconds when generating PDF/PPTX.
This is likely due to:
- Hardcoded 30-second timeout in the extension
- Loading 10 images (~2MB total) from remote filesystem
- No configurable timeout setting in VS Code

## Solution 1: Use Marp CLI (Recommended - No Timeout!)

**On your Windows machine:**

```powershell
# 1. Install Node.js if needed: https://nodejs.org/

# 2. Install Marp CLI globally
npm install -g @marp-team/marp-cli

# 3. Copy the presentation file to Windows
# (Use Cursor's file explorer to download, or SCP/SFTP)

# 4. Copy images directory to Windows (same relative path structure)
# OR update image paths in the .md file to point to local copies

# 5. Export to PPTX (no timeout!)
marp SSA_Spiller_Presentation.md --pptx --output SSA_Spiller_Presentation.pptx

# Or export to PDF
marp SSA_Spiller_Presentation.md --pdf --output SSA_Spiller_Presentation.pdf
```

**Advantages:**
- ✅ No timeout limit
- ✅ Faster (runs locally, no remote filesystem overhead)
- ✅ More reliable
- ✅ Better error messages

## Solution 2: Try Increasing VS Code Timeout (May Not Work)

The Marp VS Code extension doesn't expose a timeout setting, but you can try:

1. Open VS Code Settings (`Ctrl+,`)
2. Search for: `marp`
3. Look for any timeout-related settings (unlikely to exist)

**Alternative:** Check if there's a way to configure it via `settings.json`:
```json
{
  "marp.timeout": 60000  // This probably won't work - setting doesn't exist
}
```

## Solution 3: Optimize Images (Reduce Load Time)

If you want to stick with the extension, try reducing image sizes:

```bash
# On remote system, compress images
cd /work/atimofee/sandbox/bugs/ssa-spiller/tests/spiller/Presentation/
for img in *.jpg; do
  convert "$img" -quality 75 -resize 1920x1080 "compressed_$img"
done
```

Then update image paths in the presentation to use compressed versions.

## Solution 4: Export HTML First, Then Convert

1. Export to HTML (usually faster):
   - Marp: Export slide deck → HTML
2. Use a separate tool to convert HTML to PPTX/PDF

## Recommendation

**Use Marp CLI (Solution 1)** - it's the most reliable and doesn't have timeout issues.
The VS Code extension is convenient for previewing, but CLI is better for actual exports.



