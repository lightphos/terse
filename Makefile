.PHONY: terse examples io serve go vscode-terse install-vscode-terse compile

terse:
	python3 compiler/tersec.py build examples/minicompiler.terse -o output/tersec

examples:
	python3 compiler/tersec.py build examples/hello.terse -o output/hello
	python3 compiler/tersec.py build examples/fact.terse -o output/fact
#	python3 compiler/tersec.py build examples/hof.terse -o output/hof
	python3 compiler/tersec.py build examples/iflet.terse -o output/iflet
	
io:
	python3 compiler/tersec.py build examples/io.terse -o output/io

serve:
	python3 compiler/tersec.py build examples/http_hello.terse -o output/http_hello
	python3 compiler/tersec.py build examples/serve.terse -o output/serve

go:
	python3 compiler/tersec.py build examples/go_entry.terse -o output/go_entry
	python3 compiler/tersec.py build examples/http_top.terse -o output/http_top

vscode-terse:
	cd vscode-terse && npm install && npm run compile && npm run package

install-vscode-terse:
	cd vscode-terse && code --install-extension vscode-terse-0.0.1.vsix

compile:
	python3 compiler/tersec.py build examples/$1.terse -o output/$1
