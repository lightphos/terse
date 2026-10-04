.PHONY: terse vscode-terse install-vscode-terse compile tcc tc-test

TC_TEST_FILE ?= output/tc-test-file

tcc:
	@mkdir -p output
	python3 compiler/tersec.py build compiler/tc.te -o output/tc-stage0

tc-test:
	TERSE_TEST_FILE=$(TC_TEST_FILE) python3 compiler/tersec.py run compiler/t_tc.te -o output/t-tc

dir ?= src
terse.%:
	python3 compiler/tersec.py build $(dir)/$*.te -o output/$*
	./output/$*

vscode-terse:
	cd vscode-terse && npm install && npm run compile && npm run package

install-vscode-terse:
	cd vscode-terse && code --install-extension vscode-terse-0.0.1.vsix

compile.%:
	python3 compiler/tersec.py build src/$1.te -o output/$1
