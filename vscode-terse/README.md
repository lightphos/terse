# VS Code Terse Extension

This extension provides two commands for Terse source files:

- `Terse: Compile` — compiles the current `.terse` file into `output/<name>`
- `Terse: Run` — compiles and executes the generated binary, showing stdout in the `Terse` output channel

## Setup

1. Open `vscode-terse` in VS Code.
2. Run `npm install`.
3. Run `npm run compile`.
4. Press `F5` to launch the extension in the Extension Development Host.

## Install in main VS Code

1. Install `vsce` globally if needed:
	```bash
	npm install -g vsce
	```
2. From `vscode-terse`, run:
	```bash
	npm run package
	```
3. In main VS Code, open the Command Palette and choose `Extensions: Install from VSIX...`.
4. Select the generated `.vsix` file.
5. Reload VS Code.

## Usage

1. Open a `.terse` file in the workspace root.
2. Run the `Terse: Compile` or `Terse: Run` command from the command palette.
3. The output binary is written into the `output/` folder relative to the workspace root.
