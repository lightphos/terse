# AGENTS.md

## Project
Reference compiler for the **Terse** language, implemented as a single Python file at `compiler/tersec.py` (lexer → recursive-descent parser → type checker → C codegen) which then invokes gcc to produce a native binary. Source files use the `.te` extension. No modules system, no Python lint/CI configured.

## Commands
- Build + run an example: `make terse.<name> dir=examples` → `output/<name>`; also `./run.sh <name>` (build+run) or `./cmp.sh <name>` (build only)
- Direct CLI: `python3 compiler/tersec.py {build|run|check} FILE [-o OUT] [--keep-c] [-v]`. `check` only parses + typechecks and prints `OK`.
- Tests: `bash compiler/run_tests.sh` (a **shell** script — do not invoke with `python3`). Equivalent to `python3 -m unittest compiler.test_compiler -v`.
- Language spec: `spec/SPEC.md`, grammar: `spec/bnf.md` (the README's `docs/SPEC.md` link is stale; `docs/` does not exist).

## Gotchas
- **gcc must be on PATH** and sqlite3 headers present (`-lsqlite3` is linked on non-Windows). Without gcc, every compile/test fails with `FileNotFoundError: 'gcc'`.
- **`TestExamples` in `compiler/test_compiler.py` is stale**: it still builds `examples/*.terse`, but examples were renamed to `.te` (commit 6215060), so those tests fail with a missing-file assert until updated to `.te`.
- HTTP tests (`TestHttp`) start real servers on fixed ports 18081 and 18099.
- Most `use std.*` lines are parsed and **ignored** — `db.*`, `http.serve`, `tst.check.equals`, `pr`, `json`, `len` are builtins implemented in CodeGen + the embedded C runtime.
- `std.tst` is a builtin test module: `tst.check.equals(a, b)` compares i64/bool/str and `exit(1)`s on mismatch (abort-style). Tests are invoked explicitly via `go { ... }` — there is no auto-discovery. See `tests/examples/t_add.te`.
- `db.connect/exec/query/query_one` are native (SQLite in the C runtime); `support/sqliteserver.py` is only for `sqlite_rx` clients, not the native runtime. `support/terse.db` is gitignored.
- Program entry: last top-level expression, `fn main()`, or `go { ... }`. Generated `main` prints the program's i64 result unless `pr()` already produced output (trailing-zero suppression); tests assert stdout accordingly.
- Requires Python 3.12+. Binaries land in gitignored `output/` (with sibling `.c` files when `--keep-c`).
- `vscode-terse/` is a separate npm extension compiling the same `tersec.py`; only touch it when working on the extension itself.