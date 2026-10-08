.PHONY: terse vscode-terse install-vscode-terse compile tcc tc-test

TC_TEST_FILE ?= output/tc-test-file

tcc:
	@mkdir -p output
	python3 compiler/tersec.py build compiler/tc.te -o output/tc-stage0

tc-test:
	TERSE_TEST_FILE=$(TC_TEST_FILE) python3 compiler/tersec.py run compiler/t_tc.te -o output/t-tc
	@native_log=$$(./tc compiler/tc_smoke.te -o output/tc-smoke 2>&1); \
	  printf '%s\n' "$$native_log"; \
	  printf '%s\n' "$$native_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(output/tc-smoke)" = "hello world"
	@hello_log=$$(./tc src/hello.te -o output/tc-hello 2>&1); \
	  printf '%s\n' "$$hello_log"; \
	  printf '%s\n' "$$hello_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(output/tc-hello)" = "hello world"
	@fact_log=$$(./tc src/fact.te -o output/tc-fact 2>&1); \
	  printf '%s\n' "$$fact_log"; \
	  printf '%s\n' "$$fact_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(output/tc-fact)" = "3628800"
	@bool_log=$$(./tc src/bool.te -o output/tc-bool 2>&1); \
	  printf '%s\n' "$$bool_log"; \
	  printf '%s\n' "$$bool_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(output/tc-bool)" = "42"

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
