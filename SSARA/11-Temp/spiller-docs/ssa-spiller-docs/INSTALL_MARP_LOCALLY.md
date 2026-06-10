# How to Install Marp Extension Locally in Cursor (Remote Workspace)

## Method 1: Command Palette (Try This First)

1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
2. Type: `Extensions: Install Extensions`
3. Search for "Marp for VS Code"
4. Right-click on the extension → Look for "Install Locally" or "Install in User Settings"

## Method 2: Settings Configuration

1. Open Settings (`Ctrl+,`)
2. Search for: `remote.extensionKind`
3. Add Marp extension to use local extension host:
   - Add to settings.json:
   ```json
   "remote.extensionKind": {
     "marp-team.marp-vscode": ["ui"]
   }
   ```
   - This forces the extension to run in the UI (local) instead of remote

## Method 3: Manual Installation via Command Line

On your Windows machine, you can try:
```powershell
# Navigate to Cursor's extension directory
cd "$env:USERPROFILE\.cursor\extensions"

# Or try installing via code command if available
code --install-extension marp-team.marp-vscode --force
```

## Method 4: Use Marp CLI Instead (Easiest)

Since extension installation is problematic, use Marp CLI directly:

1. Install Node.js on Windows: https://nodejs.org/
2. Open PowerShell on Windows
3. Run:
   ```powershell
   npm install -g @marp-team/marp-cli
   ```
4. Copy `SSA_Spiller_Presentation.md` to your Windows machine
5. Run:
   ```powershell
   marp SSA_Spiller_Presentation.md --pptx --output SSA_Spiller_Presentation.pptx
   ```

This completely bypasses the extension and works entirely on your local Windows machine.




