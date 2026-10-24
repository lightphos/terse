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
	@echo "  make tcc1        - host builds stage1 (reliable)\n  make tcc1-native - stage0 compiles tc.te (may OOM)"
	@echo "  make bootstrap   - stage1 compiles tc.te -> out/tc"
	@echo "  make terse.NAME  - compile src/NAME.te with out/tc and run it"
	@echo "  make run.NAME    - compile and run src/NAME.te with host tersec and run"
	@echo "  make tst.NAME    - tst/t_NAME.te"
	@echo "  make tst         - run all tst t_*.te file"
	@echo "  make clean"
	@echo "CC=$(CC)  (export CC=... to change C compiler used by tc stages)"

verify: tst
	$(PYTHON) $(TERSEC_TEST)


# --- Bootstrap ----------------------------------------------------------
# Host-generated C for tc.te is ~130KB and fine.
# Native stage0 emit is much larger (nested statement-exprs) and often OOMs
# the C compiler on Windows (cc1.exe) when compiling full tc.te.
# Default tcc1 uses the host again (reliable). Optional: make tcc1-native

tcc:
	@mkdir -p $(OUT)
	$(PYTHON) $(TERSEC) build $(TC_SRC) -o $(STAGE0) --no-libs

# Reliable stage1: same as stage0 source, rebuilt by host under a new name
tcc1: tcc
	@mkdir -p $(OUT)
	$(PYTHON) $(TERSEC) build $(TC_SRC) -o $(STAGE1) --no-libs
	@echo "tcc1: host-built $(STAGE1) (use make tcc1-native to try stage0 self-compile)"

# Experimental: stage0 compiles tc.te (may OOM on Windows/low-RAM)
tcc1-native: tcc
	@mkdir -p $(OUT)
	CC=$(CC) $(STAGE0) $(TC_SRC) $(STAGE1)

# Full native chain when tcc1-native works on your machine
bootstrap: tcc1
	@mkdir -p $(OUT)
	@if [ -x "$(STAGE1)" ]; then \
	  CC=$(CC) $(STAGE1) $(TC_SRC) $(TC) || \
	  ($(PYTHON) $(TERSEC) build $(TC_SRC) -o $(TC) --no-libs && echo "bootstrap: host fallback -> $(TC)"); \
	else \
	  $(PYTHON) $(TERSEC) build $(TC_SRC) -o $(TC) --no-libs; \
	fi


# Smoke: host builds stage0; stage0 compiles a tiny program (not full tc.te)
bootstrap-verify: tcc
	@mkdir -p $(OUT)
	@echo "==> host stage0"
	@test -x "$(STAGE0)" || test -f "$(STAGE0)" || (echo "missing $(STAGE0)" && exit 1)
	@printf '%s\n' 'go { pr(42) }' > $(OUT)/_bv_hi.te
	@echo "==> stage0 compile smoke"
	@CC=$(CC) $(STAGE0) $(OUT)/_bv_hi.te $(OUT)/_bv_hi && \
	  test -f $(OUT)/_bv_hi -o -f $(OUT)/_bv_hi.exe && \
	  echo "bootstrap-verify: OK" || \
	  (echo "bootstrap-verify: stage0 smoke failed (use host if OOM on full tc.te)" && exit 1)

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
