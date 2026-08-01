# Publishing `vscode-terse` to the Visual Studio Marketplace

Steps to publish the extension so it can be installed into main VS Code.

1. Create a publisher (one-time):

   ```bash
   npm install -g vsce
   vsce create-publisher <your-publisher-name>
   ```

   Follow prompts — you'll need to provide a Microsoft account and verify.

2. Create a Personal Access Token (PAT) for publishing (follow vsce docs). Then export it:

   ```bash
   export VSCE_PAT=your_personal_access_token
   # On PowerShell
   $env:VSCE_PAT = 'your_personal_access_token'
   ```

3. From the extension folder, increment the `version` in `package.json` and publish:

   ```bash
   npm run package      # creates .vsix locally
   npm run publish      # runs `vsce publish` (requires VSCE_PAT)
   ```

4. After publishing, your extension will appear in the Marketplace under your publisher.

Notes:
- Make sure `publisher` in `package.json` matches the publisher you created.
- The Marketplace requires a 128x128 PNG icon for the published extension; if you want to publish, replace `images/icon.svg` with a `images/icon.png` of that size.
- See https://code.visualstudio.com/api/working-with-extensions/publishing-extension for more details.

Note: this repository now contains a `LICENSE` file (MIT). Packaging via `vsce package` will no longer prompt about a missing license.
