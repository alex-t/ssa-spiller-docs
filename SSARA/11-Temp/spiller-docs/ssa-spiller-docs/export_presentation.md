# Exporting SSA Spiller Presentation

## Option 1: Using Marp CLI (Recommended)

### On Windows (PowerShell):
```powershell
# Install Node.js from https://nodejs.org/ if not already installed
# Then install Marp CLI:
npm install -g @marp-team/marp-cli

# Export to PowerPoint:
marp SSA_Spiller_Presentation.md --pptx --output SSA_Spiller_Presentation.pptx

# Or export to PDF:
marp SSA_Spiller_Presentation.md --pdf --output SSA_Spiller_Presentation.pdf

# Or export to HTML:
marp SSA_Spiller_Presentation.md --html --output SSA_Spiller_Presentation.html
```

## Option 2: Using VS Code Extension (Local Installation)

1. In Cursor, open Extensions (Ctrl+Shift+X)
2. Search for "Marp for VS Code"
3. Click the gear icon → **"Install Locally"** (NOT "Install in Workspace")
4. Open `SSA_Spiller_Presentation.md`
5. Press Ctrl+Shift+P → "Marp: Export slide deck"
6. Choose PPTX format

## Option 3: Copy File to Windows and Export Locally

1. Copy `SSA_Spiller_Presentation.md` to your Windows machine
2. Install Marp CLI on Windows (see Option 1)
3. Run export command locally

## Troubleshooting

- **Extension installs on remote**: Make sure to choose "Install Locally" not "Install in Workspace"
- **No Node.js**: Download from https://nodejs.org/ (LTS version recommended)
- **Permission errors**: On Windows, you may need to run PowerShell as Administrator for global npm installs





