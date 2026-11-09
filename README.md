# Terse

Terse is a compact, statically typed language that compiles to native binaries through a C backend. The repo includes the Python host compiler, example programs, test suite, and a small standard library surface.

## Quick start

Prerequisites:
- Python 3.12+
- `gcc` or `clang` available on `PATH`

```
Example source (`src/hi.te`):

```terse
go {
  val name = arg(1) == "" ? "all" : arg(1)
  pr("Hi, " + name + "! This is terse!")
}
```

## Build commands

```bash
# Compile and run
python3 compiler/tersec.py build src/hi.te -o out/hi
./out/hi

# Makefile shortcuts
make run.NAME dir=src
make run.hi

# Parse + typecheck only
python3 compiler/tersec.py check src/hi.te

# Build the bootstrap compiler from the Terse source frontend
make tcc
make tcc1
make bootstrap
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
# Host compiler tests
make verify

# All Terse tests
make tst
```

Tests are under `tst/` and prefixed with `t_`, ie. `t_*.te`.


## Language docs

The language design, semantics, and grammar are documented in:
- [SPEC.md](./SPEC.md)
- [BNF.md](./BNF.md)
- [BENCHMARK](./BENCH.md)

## VS Code support

```bash
cd vscode-terse
npm install
npm run compile
npm run package
```

There after reload the VS Code window and use terse commands from the command palette.

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


## Memory management

Generated programs allocate through a **bump arena** in `compiler/runtime.c` (linked into every binary). Lists, maps, strings, and similar runtime objects use the arena instead of per-object `malloc`/`free`.

### How it works

1. The arena holds one or more **chunks** (default **256 KiB**, or larger when a single object needs more).
2. Chunks are obtained with system `malloc`.
3. Client allocations **bump** a cursor inside the current chunk (8-byte aligned). Each block stores a small size header so `realloc` can copy.
4. Individual objects are **not** freed. Growing a list or map may abandon the old buffer (copy-forward `realloc`).
5. Optional **`arena.reset()`** releases every chunk at once (e.g. end of a batch or test).

This fits Terse’s C backend: short-lived program runs, tests, and request-style servers where freeing the whole arena is enough.

```text
  _arena_head ─────────────────────────────────────────┐
                                                       │
                                                       ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Chunk N (newest)                                            │
  │  next ──► Chunk N-1 ──► … ──► Chunk 0 ──► NULL              │
  │                                                             │
  │  used ──────────┐                                           │
  │                 ▼                                           │
  │  ┌──────┬──────────┬──────┬──────────┬──────┬────────────┐  │
  │  │ size │ payload  │ size │ payload  │ size │  free …    │  │
  │  │ hdr  │ (list,   │ hdr  │ (string, │ hdr  │            │  │
  │  │      │  map…)   │      │  …)      │      │            │  │
  │  └──────┴──────────┴──────┴──────────┴──────┴────────────┘  │
  │  ◄────────── live objects ──────────►◄── bump space ──►     │
  └─────────────────────────────────────────────────────────────┘

  arena_alloc(n)
       │  align n; if not enough room in current chunk → new chunk
       ▼
  write size header, advance `used`, return pointer to payload

  arena_realloc(ptr, n)
       │  read old size from header; arena_alloc(n); memcpy
       ▼
  old payload stays in the chunk (abandoned; no free)

  arena_reset()
       │
       ▼
  free every chunk via system free; head = NULL; used = 0
```

### Runtime API (C)

| Function | Role |
|----------|------|
| `arena_alloc` / `arena_calloc` | New block |
| `arena_realloc` | New block + copy; old block left in place |
| `arena_strdup` | Copy a C string into the arena |
| `arena_used` | Approximate bytes handed to clients |
| `arena_chunk_count` | Number of chunks |
| `arena_reset` | Free all chunks and zero counters |

### Terse surface

```terse
arena.used()     // long — bytes allocated to clients
arena.chunks()   // long — chunk count
arena.reset()    // drop the arena (optional)
```


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


## Event-loop async (`~~>` / `~>`)

`~~>` marks an event-loop task; `~>` suspends the connection (e.g. `~> tim.wait(100)`). Thread async remains `~~` / `~`. See `src/nhttp_srv.te`.
