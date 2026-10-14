.PHONY: terse vscode-terse install-vscode-terse compile tcc tc-test

TC_TEST_FILE ?= out/tc-test-file

tcc:
	@mkdir -p out
	python3 compiler/tersec.py build compiler/tc.te -o out/tc-stage0

tcc1: tcc
	out/tc-stage0 compiler/tc.te out/tc-stage1

bootstrap: tcc1
	out/tc-stage1 compiler/tc.te out/tc 

dir ?= src
terse.%:
# 	python3 compiler/tersec.py build $(dir)/$*.te -o out/$*
	./tc $(dir)/$*.te -o out/$*
	./out/$*

vscode-terse:
	cd vscode-terse && npm install && npm run compile && npm run package

install-vscode-terse:
	cd vscode-terse && code --install-extension vscode-terse-0.0.1.vsix

compile.%:
	python3 compiler/tersec.py build src/$1.te -o out/$1
	./out/$*

test:
	tst/test.sh

