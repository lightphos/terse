# Terse

A (very) succinct language that compiles to native binaries, with structures, interfaces, first-class higher-order functions, supporting libraries and builtin in test runner.

## Quick Start

> Requires python3

### Run and Test
```bash
# Build program in example directory to a binary
make run.eg dir=src

make tst.t_eg

make tst (all)
```

### VS Code Support
```bash
make vscode-terse
make vconde-install
```
In VS Code, reload window:

```
Ctrl+Shift+P
Developer: Reload Window
```

Select a terse file, then

Compile:

```
Ctrl+Shift+P

Terse: Compile
```

Run:

```
Ctrl+Shift+P
Terse: Run

or F5
```

## Language Spec

See [docs/bnf.md](docs/bnf.md) and [docs/SPEC.md](docs/SPEC.md) for the full language specification.

## Compiler Status (0.1)

- Hello world built in print out
- Basic arithmetic
- If else


## Compiler Status (0.2)

The reference compiler (`compiler/tersec.py`) implements:

- Lexer, recursive-descent parser, minimal type checker
- C code generation + gcc/clang backend → native binary
- Integers (`i64`), booleans, arithmetic & comparisons
- `if` expressions, `let` bindings, blocks
- Named functions + recursion
- **Higher-order functions**: pass functions as values, simple lambdas (`|x| x*2`)
- Function pointers under the hood (no environment capture yet)
- Text file reads and writes through `std.io`

Not yet implemented (but specified):

- Full closures with captures
- Records / structs / pattern matching
- Generics, ownership system, selective imports, and visibility modifiers

## Examples

| File | Description | Output |
|------|-------------|--------|
| `src/hi.te` | Hi there | 0 |
| `src/fact.te` | Recursion | 3628800 |
| `src/hof.te` | Higher-order + lambda | 149 |
| `src/if.te` | if + else | 59 |

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
multiple named `i64` functions with arbitrary parameters, recursion, and
`if`/`else`. The root
`tc` launcher bootstraps this frontend with `tersec.py` when needed, tries the
native frontend first, and reports when it falls back:

```sh
# Build the bootstrap.
make bootstrap
```


## TODO: Native Compiler Parity

- [x] Generalize function declarations and calls: multiple functions, arbitrary
  parameter/argument lists, optional `i64`/`bool` parameter and return
  annotations, `pub`, and one validated `go` entrypoint. The parser also accepts
  unused type/record/trait/method declarations and standard imports.
- [ ] Add semantics for type/record/trait/method declarations and source-module
  imports, including module resolution and visibility enforcement.
- [ ] Complete lexical and expression coverage: hexadecimal integers, floats,
  unit, decoded string escapes, block comments, assignment, composition,
  partial-application `_`, and postfix member/call/index/record/list forms.
- [ ] Add the documented statement and control forms: general block sequencing,
  `val`/`var`, assignment, `ret`, both `lp` loop forms, and `if match` with
  patterns and guards; account for `brk`/`skip` if they are part of the
  supported language contract.
- [ ] Implement the type forms and checking promised by the docs: primitive and
  function types, lists, records, tuples, `Option`/`Result`, annotations and
  inference, plus useful errors for unknown names, invalid calls, and mismatches.
- [ ] Port higher-order behavior and data features: function values, lambdas,
  closure captures, records/traits, lists, string operations, and the supported
  `fs`, JSON, and environment builtins/runtime. Move HTTP and DB APIs according
  to the extraction plan below, keeping limited HTTP features distinct from
  documented future middleware and request-decoding support.

## TODO: HTTP and DB Library Extraction

`std.http` and `std.db` are not ordinary Terse modules yet. HTTP routes are
recognized as a special AST form and emitted by compiler code; DB calls are
lowered by compiler-specific code. The socket and SQLite operations they depend
on currently live in the generated C runtime. A Terse library therefore needs
stable host primitives before those implementations can leave the compiler.

- [ ] Define a standard-library package layout and resolver for compiler-provided
  low-level modules, such as `std.net` and `std.sqlite`.
- [ ] Expose the minimum socket and SQLite host APIs through a generic native
  module/ABI boundary; keep protocol routing and database convenience APIs out
  of that boundary.
- [ ] Implement HTTP routing/server behavior and DB connection/query helpers in
  Terse library modules. Replace the special route-block syntax and typed
  `db.query[Record]` lowering with core-language API forms where possible.
- [ ] Migrate the consumers below and test them against the library APIs before
  removing the compiler's `HttpServe` parser/codegen, DB call lowering, and
  high-level HTTP/SQLite runtime code.
- [ ] Keep platform-specific socket/SQLite bindings only as low-level runtime
  support if the language still has no FFI or external native-module mechanism.

Migration TODOs for current consumers:
- [ ] `src/serve.te` uses both `std.http` and `std.db`.
- [ ] `src/db.te` uses compiler-provided `db.*` operations.
- [ ] HTTP integration tests in `compiler/test_compiler.py` currently validate
  compiler-backed route handling; move/add coverage for the library API.


## TODO

- tc -> terse compiler
- tp -> package manager
- tb -> bld and test

> Now you can't get more `terse` than that!


## License

MIT (for this reference implementation)
