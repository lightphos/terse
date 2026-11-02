# Terse

Terse is a compact, statically typed language that compiles to native binaries through a C backend. The repo includes the Python host compiler, example programs, test suite, and a small standard library surface.

## Quick start

Prerequisites:
- Python 3.12+
- `gcc` or `clang` available on `PATH`

Compile and run the built-in hello example:

```bash
python3 compiler/tersec.py build src/hi.te -o out/hi
./out/hi
```

Or use the Makefile shortcuts:

```bash
make run.hi dir=src
make tst
```

Example source (`src/hi.te`):

```terse
go {
  val name = arg(1) == "" ? "World" : arg(1)
  pr("Hi, " + name + "! This is terse!")
}
```

## Build commands

```bash
# Compile a source file using the Python host compiler
python3 compiler/tersec.py build src/hi.te -o out/hi

# Run a source file directly
python3 compiler/tersec.py run src/hi.te -o out/hi

# Parse + typecheck only
python3 compiler/tersec.py check src/hi.te

# Build the bootstrap compiler from the Terse source frontend
make tcc
make tcc1
make bootstrap

# Compile/run a project example under src/
make run.NAME dir=src

# Run tests under tst/
make tst
```

## Project layout

```text
compiler/      Host compiler and tests
src/           Example programs and app modules
lib/           Optional library modules
tst/           Test programs (t_*.te)
SPEC.md        Language specification
TERSE_BNF.md   Grammar reference
vscode-terse/  VS Code extension
```

## Testing

```bash
# Host compiler unit tests
python3 -m unittest compiler.test_compiler -v

# All Terse test programs
make tst
```

Tests under `tst/` are written as `t_*.te` programs and are compiled by the host compiler.

## Language docs

The language design, semantics, and grammar are documented in:
- [SPEC.md](./SPEC.md)
- [TERSE_BNF.md](./TERSE_BNF.md)

This README intentionally stays concise; implementation details and language rules live in the spec files.

## VS Code support

```bash
cd vscode-terse
npm install
npm run compile
npm run package
```

Then reload the VS Code window and use the Terse commands from the command palette.

## Status

The compiler is in active development. It supports a growing subset of the language, including native compilation via a C backend, module imports, basic types, conditionals, loops, functions, and higher-order constructs. See [SPEC.md](./SPEC.md) for the current language contract.

For the prioritized next work items and staged native-lift plan, see [roadmap.md](./roadmap.md).

## Compiler Status (0.3)

The reference compiler (`compiler/tersec.py`, now split into the `compiler/tersec/` package) implements:

- Lexer (`lexer.py`), recursive-descent parser (`parser.py`), type checker with generic specialization and overload resolution (`typecheck.py`), C codegen (`codegen.py`), plus shared type helpers (`utils.py`)
- C code generation + gcc/clang backend → native binary; C runtime extracted to `compiler/runtime.c`
- Integers (`long/int`), booleans, arithmetic & comparisons
- `if`/`else` expressions, ternary, blocks, `ret`, `val`/`var` bindings
- Named functions + recursion
- `fix` / `pub fix` constants; `pub` visibility
- **Higher-order functions**: pass functions as values, simple lambdas (`|x| x*2`)
- Function pointers under the hood (no environment capture yet)
- **Parameter overloading** (distinct param type lists)
- **Records / structs**, **methods**, **enums** (+ payloads), **traits** (implicit satisfaction)
- **Pattern guards**: `if` arms
- **Loops**: for-in, C-style `lp i = 0; ...;`, condition loops; `brk` / `skip`
- **Lists**: width types `[long]`/`[int]`/`[str]`/…, `+`, `len`, index, `map`
- **Maps**: `{str:long|str}`, put/get, `has`, `keys`, `len`, for-in keys
- **Modules**: `use`, `pub`, parallel `tst` ↔ `src` test files
- Frozen std: `std.str`, `std.io`, `std.tst`; `env` get/set
- Text file reads and writes through `std.io`
- `go` entrypoint; `go()`; `pr`; string/int concat
- Unit-test runner (`tst.check.equals`); hard errors for unknown names/functions
- Output layout `~/.terse/out` (overridable via `TERSE_OUT`/`TERSE_HOME`); optional `lib` objects (`TERSE_AUTOLIB` for auto-link)
- **Pipe operator** `|>` (left-to-right function application, desugared at parse time)

Not yet implemented (but specified):

- Full closures with environment capture
- Ownership/borrowing system
- Native `tc.te` feature parity with the host compiler
- Richer package system beyond path `use`
- HTTP beyond minimal `http.srv`


## Architecture

```
.terse source
    ↓ Lexer
  tokens
    ↓ Parser
   AST
    ↓ TypeChecker (basic)
   AST
    ↓ CodeGen → C source
    ↓ gcc -O2
  native binary
```

## Terse Compiler Bootstrap

`compiler/tc.te` is the first compiler frontend written in Terse. It reads a
source file, builds a token/node arena, emits C, and invokes GCC. Its current
native subset includes arithmetic and logical expressions, `pr(string)`, and
multiple named `long` functions with arbitrary parameters, recursion, and
`if`/`else`. The root
`tc` launcher bootstraps this frontend with `tersec.py` when needed, tries the
native frontend first, and reports when it falls back:

```sh
# Build the bootstrap.
make bootstrap
```

## License

MIT (for this reference implementation)
