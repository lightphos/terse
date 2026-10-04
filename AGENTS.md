# AGENTS.md

## Project
Reference compiler for the **Terse** language, implemented in Python at `compiler/tersec.py` (lexer → recursive-descent parser → type checker → C codegen) which invokes gcc. `compiler/tc.te` is the early Terse-written compiler frontend, bootstrapped by the reference compiler and emitting C for GCC. Source files use the `.te` extension. No Python lint/CI configured.

## Commands
- Build + run an example: `make terse.<name> dir=src` → `output/<name>`; also `./run.sh <name>` (build+run) or `./cmp.sh <name>` (build only)
- Direct CLI: `python3 compiler/tersec.py {build|run|check} FILE [-o OUT] [--keep-c] [-v]`. `check` only parses + typechecks and prints `OK`.
- Tests: `bash compiler/run_tests.sh` (a **shell** script — do not invoke with `python3`). Equivalent to `python3 -m unittest compiler.test_compiler -v`.
- Language spec: `spec/SPEC.md`, grammar: `spec/bnf.md` (the README's `docs/SPEC.md` link is stale; `docs/` does not exist).

## Gotchas
- **gcc must be on PATH** and sqlite3 headers present (`-lsqlite3` is linked on non-Windows). Without gcc, every compile/test fails with `FileNotFoundError: 'gcc'`.
- **`TestExamples` in `compiler/test_compiler.py`** compiles the checked-in `src/*.te` programs.
- HTTP tests (`TestHttp`) start real servers on fixed ports 18081 and 18099.
- `std.*` imports name compiler-provided modules such as `std.fs`; `db.*`, `http.serve`, `tst.check.equals`, `pr`, `json`, and `len` are implemented in CodeGen + the embedded C runtime. Source imports resolve under `src/` and currently expose functions only.
- `std.tst` is a builtin test module: `tst.check.equals(a, b)` compares i64/bool/str and `exit(1)`s on mismatch (abort-style). Tests are invoked explicitly via `go { ... }` — there is no auto-discovery. See `tests/examples/t_add.te`.
- `db.connect/exec/query/query_one` are native (SQLite in the C runtime); `support/sqliteserver.py` is only for `sqlite_rx` clients, not the native runtime. `support/terse.db` is gitignored.
- Program entry: `go()` for an empty body or `go { ... }` for a program body. `fn main` is not a Terse entrypoint. Generated C `main` prints the go body's i64 result unless `pr()` already produced output (trailing-zero suppression); tests assert stdout accordingly.
- Requires Python 3.12+. Binaries land in gitignored `output/` (with sibling `.c` files when `--keep-c`).
- `vscode-terse/` is a separate npm extension compiling the same `tersec.py`; only touch it when working on the extension itself.