# AGENTS.md

## Project
Terse is a compact, statically typed language compiled to native code via a Python host compiler and a C backend. The main compiler entrypoint is `compiler/tersec.py`; `compiler/tc.te` is an experimental self-hosted Terse frontend that the host compiler can bootstrap.

The repo layout is deliberately small:
- `compiler/` – host compiler and test harness
- `src/` – example programs and app modules
- `tst/` – test programs (`t_*.te`)
- `lib/` – optional library modules
- `vscode-terse/` – separate extension package

## Requirements
- Python 3.12+
- `gcc` or `clang` on `PATH`


## Build and run commands
Use the repository Makefile for the common paths:

```bash
# Compile a source file with the host compiler and write the binary to out/
make run.hi dir=src
# or, for a named example under src/
make run.NAME dir=src

# Compile a test under tst/
make tst.NAME

# Run the full test suite
make tst

# Build the bootstrapping compiler from compiler/tc.te
make tcc
make tcc1
make bootstrap
```

Direct CLI usage:

```bash
python3 compiler/tersec.py build src/hi.te -o out/hi
python3 compiler/tersec.py run src/hi.te -o out/hi
python3 compiler/tersec.py check src/hi.te
```

Useful compiler options:

```bash
python3 compiler/tersec.py build FILE [-o OUT] [--keep-c] [--no-libs] [-f]
```

## Test commands

```bash
# Unit tests for the host compiler
python3 -m unittest compiler.test_compiler -v

# All Terse tests in tst/
make tst
```

## Notes
- `make tst` runs every `tst/t_*.te` program and expects the output binary in the generated `out/` directory.
- `go { ... }` is the executable entrypoint for a Terse program; `fn main` is not used.
- Generated artifacts land in `out/` and can be cleaned with `make clean`.
- The project documentation for the language itself lives in [SPEC.md](./SPEC.md) and [TERSE_BNF.md](./TERSE_BNF.md); keep README brief and user-focused.

## Reference-code workflow
Before modifying language semantics or compiler behavior, inspect local reference material and prior art in the XERJ indexes if available:

```bash
~/.local/bin/xerj search --url http://127.0.0.1:9200 --prefix terse-src "<question>"
~/.local/bin/xerj search --url http://127.0.0.1:9200 --prefix ref-airtight "<question>"
~/.local/bin/xerj search --url http://127.0.0.1:9200 --prefix ref-prometeo "<question>"
```

If the local XERJ daemon is not running:

```bash
~/.local/bin/xerj --insecure --bind 127.0.0.1 --port 9200 --data-dir ~/.xerj/terse-data --disable-feedback
```

This repo keeps the compiler and language spec in sync manually; prefer precise source-level checks when making changes.