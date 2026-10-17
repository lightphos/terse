import * as vscode from 'vscode';
import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

const outputChannel = vscode.window.createOutputChannel('Terse');

function getWorkspaceFolder(document: vscode.TextDocument): vscode.WorkspaceFolder | undefined {
  return vscode.workspace.getWorkspaceFolder(document.uri);
}

function ensureDirectory(filePath: string) {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function buildTerse(sourcePath: string, outPath: string, cwd: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const python = process.platform === 'win32' ? 'python' : 'python3';
    const args = ['compiler/tersec.py', 'build', sourcePath, '-o', outPath];
    const child = spawn(python, args, { cwd });

    let stdout = '';
    let stderr = '';

    child.stdout?.on('data', (data) => {
      const text = data.toString();
      stdout += text;
      outputChannel.append(text);
    });
    child.stderr?.on('data', (data) => {
      const text = data.toString();
      stderr += text;
      outputChannel.append(text);
    });

    child.on('error', (error) => {
      reject(new Error(stderr || stdout || error.message));
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve(stdout.trim());
      } else {
        reject(new Error(stderr || stdout || `Process exited with code ${code}`));
      }
    });
  });
}

function runOutput(exePath: string, cwd: string): Promise<string> {
  vscode.window.showInformationMessage(`Running ${path.basename(exePath)} in ${cwd}`);

  return new Promise((resolve, reject) => {
    const child = spawn(exePath, [], { cwd });

    let stdout = '';
    let stderr = '';

    child.stdout?.on('data', (data) => {
      const text = data.toString();
      stdout += text;
      outputChannel.append(text);
    });
    child.stderr?.on('data', (data) => {
        const text = data.toString();
        stderr += text;
        outputChannel.append(text);
      });

    child.on('error', (error) => {
      reject(new Error(stderr || stdout || error.message));
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error(stderr || stdout || `Process exited with code ${code}`));
      }
    });
  });
}

async function compileCommand() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage('No active editor');
    return;
  }

  const document = editor.document;
  if (document.languageId !== 'terse' && path.extname(document.fileName) !== '.te') {
    vscode.window.showErrorMessage('Active file is not a Terse source file');
    return;
  }

  await document.save();

  const workspace = getWorkspaceFolder(document);
  if (!workspace) {
    vscode.window.showErrorMessage('Open the Terse workspace folder first');
    return;
  }

  const sourcePath = path.relative(workspace.uri.fsPath, document.uri.fsPath);
  const outputName = path.basename(document.fileName, '.te');
  const outPath = path.join('out', outputName + (process.platform === 'win32' ? '.exe' : ''));
  const outFsPath = path.join(workspace.uri.fsPath, outPath);
  ensureDirectory(outFsPath);

  try {
    outputChannel.clear();
    outputChannel.show(true);
    outputChannel.appendLine(`Compiling ${path.basename(document.fileName)} -> ${outPath}`);
    await buildTerse(sourcePath, outFsPath, workspace.uri.fsPath);
    outputChannel.appendLine(`Compiled to ${outPath}`);
    vscode.window.showInformationMessage(`Compiled to ${outPath}`);
  } catch (err) {
    vscode.window.showErrorMessage(`Terse compile failed: ${err instanceof Error ? err.message : String(err)}`);
  }
}

async function runCommand() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage('No active editor');
    return;
  }

  const document = editor.document;
  if (document.languageId !== 'terse' && path.extname(document.fileName) !== '.te') {
    vscode.window.showErrorMessage('Active file is not a Terse source file');
    return;
  }

  await document.save();

  const workspace = getWorkspaceFolder(document);
  if (!workspace) {
    vscode.window.showErrorMessage('Open the Terse workspace folder first');
    return;
  }

  const sourcePath = path.relative(workspace.uri.fsPath, document.uri.fsPath);
  const outputName = path.basename(document.fileName, '.te');
  const outPath = path.join('out', outputName + (process.platform === 'win32' ? '.exe' : ''));
  const outFsPath = path.join(workspace.uri.fsPath, outPath);
  ensureDirectory(outFsPath);

  try {
    outputChannel.clear();
    outputChannel.show(true);
    outputChannel.appendLine(`Compiling ${path.basename(document.fileName)} -> ${outPath}`);
    await buildTerse(sourcePath, outFsPath, workspace.uri.fsPath);
    outputChannel.appendLine(`Running ${outPath}`);
    const result = await runOutput(outFsPath, workspace.uri.fsPath);
    outputChannel.appendLine(result);
    vscode.window.showInformationMessage(`Ran ${outPath}`);
  } catch (err) {
    vscode.window.showErrorMessage(`Terse run failed: ${err instanceof Error ? err.message : String(err)}`);
  }
}

async function testCommand() {
  const workspace = vscode.workspace.workspaceFolders?.[0];
  if (!workspace) {
    vscode.window.showErrorMessage('Open the Terse workspace folder first');
    return;
  }

  const cwd = workspace.uri.fsPath;
  outputChannel.clear();
  outputChannel.show(true);
  outputChannel.appendLine('Running all tests in tst/...');

  await new Promise<void>((resolve) => {
    const child = spawn('make', ['tst'], { cwd, shell: true });

    child.stdout?.on('data', (data) => {
      outputChannel.append(data.toString());
    });
    child.stderr?.on('data', (data) => {
      outputChannel.append(data.toString());
    });

    child.on('error', (error) => {
      outputChannel.appendLine(`Error: ${error.message}`);
      resolve();
    });

    child.on('close', () => {
      resolve();
    });
  });

  outputChannel.appendLine('Done.');
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(vscode.commands.registerCommand('terse.compile', compileCommand));
  context.subscriptions.push(vscode.commands.registerCommand('terse.run', runCommand));
  context.subscriptions.push(vscode.commands.registerCommand('terse.test', testCommand));
}

export function deactivate() {}
