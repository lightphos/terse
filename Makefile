.PHONY: terse vscode-terse install-vscode-terse compile tcc tc-test

TC_TEST_FILE ?= out/tc-test-file

tcc:
	@mkdir -p out
	python3 compiler/tersec.py build compiler/tc.te -o out/tc-stage0

tc-test:
	TERSE_TEST_FILE=$(TC_TEST_FILE) python3 compiler/tersec.py run compiler/t_tc.te -o out/t-tc
	@native_log=$$(./tc compiler/tc_smoke.te -o out/tc-smoke 2>&1); \
	  printf '%s\n' "$$native_log"; \
	  printf '%s\n' "$$native_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(out/tc-smoke)" = "hello world"
	@hello_log=$$(./tc src/hello.te -o out/tc-hello 2>&1); \
	  printf '%s\n' "$$hello_log"; \
	  printf '%s\n' "$$hello_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(out/tc-hello)" = "hello world"
	@fact_log=$$(./tc src/fact.te -o out/tc-fact 2>&1); \
	  printf '%s\n' "$$fact_log"; \
	  printf '%s\n' "$$fact_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(out/tc-fact)" = "3628800"
	@bool_log=$$(./tc src/bool.te -o out/tc-bool 2>&1); \
	  printf '%s\n' "$$bool_log"; \
	  printf '%s\n' "$$bool_log" | grep -q 'compiled with the Terse frontend'; \
	  test "$$(out/tc-bool)" = "42"

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
