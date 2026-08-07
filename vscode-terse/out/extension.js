"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const child_process_1 = require("child_process");
const path = require("path");
const fs = require("fs");
const outputChannel = vscode.window.createOutputChannel('Terse');
function getWorkspaceFolder(document) {
    return vscode.workspace.getWorkspaceFolder(document.uri);
}
function ensureDirectory(filePath) {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
}
function buildTerse(sourcePath, outPath, cwd) {
    return new Promise((resolve, reject) => {
        const python = process.platform === 'win32' ? 'python' : 'python3';
        const args = ['compiler/tersec.py', 'build', sourcePath, '-o', outPath];
        const child = (0, child_process_1.execFile)(python, args, { cwd }, (error, stdout, stderr) => {
            if (error) {
                reject(new Error(stderr || stdout || error.message));
                return;
            }
            resolve(stdout.trim());
        });
        child.stdout?.on('data', (data) => {
            outputChannel.append(data.toString());
        });
        child.stderr?.on('data', (data) => {
            outputChannel.append(data.toString());
        });
    });
}
function runOutput(exePath, cwd) {
    vscode.window.showInformationMessage(`Running ${path.basename(exePath)} in ${cwd}`);
    return new Promise((resolve, reject) => {
        (0, child_process_1.execFile)(exePath, { cwd }, (error, stdout, stderr) => {
            if (error) {
                reject(new Error(stderr || stdout || error.message));
                return;
            }
            resolve(stdout);
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
    if (document.languageId !== 'terse' && path.extname(document.fileName) !== '.terse') {
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
    const outputName = path.basename(document.fileName, '.terse');
    const outPath = path.join('output', outputName + (process.platform === 'win32' ? '.exe' : ''));
    const outFsPath = path.join(workspace.uri.fsPath, outPath);
    ensureDirectory(outFsPath);
    try {
        outputChannel.clear();
        outputChannel.show(true);
        outputChannel.appendLine(`Compiling ${path.basename(document.fileName)} -> ${outPath}`);
        await buildTerse(sourcePath, outFsPath, workspace.uri.fsPath);
        outputChannel.appendLine(`Compiled to ${outPath}`);
        vscode.window.showInformationMessage(`Compiled to ${outPath}`);
    }
    catch (err) {
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
    if (document.languageId !== 'terse' && path.extname(document.fileName) !== '.terse') {
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
    const outputName = path.basename(document.fileName, '.terse');
    const outPath = path.join('output', outputName + (process.platform === 'win32' ? '.exe' : ''));
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
    }
    catch (err) {
        vscode.window.showErrorMessage(`Terse run failed: ${err instanceof Error ? err.message : String(err)}`);
    }
}
function activate(context) {
    context.subscriptions.push(vscode.commands.registerCommand('terse.compile', compileCommand));
    context.subscriptions.push(vscode.commands.registerCommand('terse.run', runCommand));
}
function deactivate() { }
//# sourceMappingURL=extension.js.map