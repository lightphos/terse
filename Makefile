.PHONY: terse vscode-terse install-vscode-terse compile

dir ?= examples
terse.%:
	python3 compiler/tersec.py build $(dir)/$*.te -o output/$*
	./output/$*

vscode-terse:
	cd vscode-terse && npm install && npm run compile && npm run package

install-vscode-terse:
	cd vscode-terse && code --install-extension vscode-terse-0.0.1.vsix

compile.%:
	python3 compiler/tersec.py build examples/$1.te -o output/$1
