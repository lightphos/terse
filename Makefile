.PHONY: terse vscode-terse install-vscode-terse compile tcc tcc1 bootstrap test clean help tst

# On macOS, `gcc` is usually Apple clang. Override: make CC=gcc-14
export CC ?= clang

# Host Python compiler and sources (adjust if your layout differs)
PYTHON   ?= python3
TERSEC   ?= compiler/tersec.py
TERSEC_TEST   ?= compiler/test_compiler.py
TC_SRC   ?= compiler/tc.te
OUT      ?= out

STAGE0   := $(OUT)/tc-stage0
STAGE1   := $(OUT)/tc-stage1
TC       := $(OUT)/tc

# App sources
dir ?= src
tdir ?= tst

help:
	@echo "Targets:"
	@echo "  make tcc         - host build stage0 (Python tersec -> out/tc-stage0)"
	@echo "  make tcc1        - stage0 compiles tc.te -> out/tc-stage1"
	@echo "  make bootstrap   - stage1 compiles tc.te -> out/tc"
	@echo "  make terse.NAME  - compile src/NAME.te with out/tc and run it"
	@echo "  make run.NAME    - compile and run src/NAME.te with host tersec and run"
	@echo "  make tst.NAME    - tst/t_NAME.te"
	@echo "  make tst         - run all tst t_*.te file"
	@echo "  make clean"
	@echo "CC=$(CC)  (export CC=... to change C compiler used by tc stages)"

verify:
	$(PYTHON) $(TERSEC_TEST)


# --- Bootstrap ----------------------------------------------------------
# Generated C is large; host/tc use -O0 so Apple clang does not abort at -O2.

tcc:
	@mkdir -p $(OUT)
	$(PYTHON) $(TERSEC) build $(TC_SRC) -o $(STAGE0)

tcc1: tcc
	CC=$(CC) $(STAGE0) $(TC_SRC) $(STAGE1)

bootstrap: tcc1
	CC=$(CC) $(STAGE1) $(TC_SRC) $(TC)

# --- Compile & run apps -------------------------------------------------

# Native compiler: ./out/tc <source.te> <output>
# (CLI is positional; not -o)
terse.%:
	@mkdir -p $(OUT)
	CC=$(CC) $(TC) $(dir)/$*.te $(OUT)/$*
	$(OUT)/$*

# Host Python compiler
run.%:
	@mkdir -p $(OUT)
	$(PYTHON) $(TERSEC) build $(dir)/$*.te -o $(OUT)/$*
	$(OUT)/$*

tst.%:
	@mkdir -p $(OUT)
	$(PYTHON) $(TERSEC) build $(tdir)/$*.te -o $(OUT)/$*
	$(OUT)/$*

# --- VS Code extension / tests ------------------------------------------

vscode-terse:
	cd vscode-terse && npm install && npm run compile && npm run package

install-vscode-terse:
	cd vscode-terse && code --install-extension vscode-terse-0.0.1.vsix

test:
	tst/test.sh

tst:
	@for f in tst/t_*.te; do \
		base=$$(basename $$f .te); \
		$(MAKE) --no-print-directory tst.$$base; \
	done

clean:
	rm -rf $(OUT)
