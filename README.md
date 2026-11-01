# Terse

A succinct language that compiles to native binaries, with structures, interfaces, first-class higher-order functions, supporting libraries and builtin in test runner.

### Hi

> src/hi.te
```terse

go {
    val a = arg(1) == "" ? "World" : arg(1) 
    pr("Hi, " + a + "! This is terse!")
}

```

> make run.hi
```
Hi, World! This is terse
```
## Howz

> Requires python3

### Run and Test
```bash
# Build program in example directory to a binary
make run.eg dir=src
make tst.t_eg
make tst (all)
```

> Tests are detected and run if functions are prefixed by `t_`


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


## Output layout (`~/.terse/out`)

By default the host writes under the Terse home directory:

| What | Path |
|------|------|
| Home | `~/.terse` (override with `$TERSE_HOME`) |
| Binaries / generated `.c` | `~/.terse/out/<name>` (override with `$TERSE_OUT`) |
| Libraries | `~/.terse/out/lib/<module>/module.o` (+ `module.meta`) (override with `$TERSE_LIB`) |

### Resolution rules

- **No `-o`:** writes `~/.terse/out/<stem>` from the source file name
- **`-o name` (bare name):** also under `~/.terse/out/name`
- **`-o path/to/out` or an absolute `-o`:** uses that path as given

```bash
python3 compiler/tersec.py build src/hi.te
# → ~/.terse/out/hi

python3 compiler/tersec.py build src/hi.te -o out/hi
# → out/hi  (relative path that includes a directory)

python3 compiler/tersec.py lib src/utils.te
# → ~/.terse/out/lib/utils/module.o
```

Environment overrides:

```bash
export TERSE_OUT=/path/to/out
export TERSE_LIB=/path/to/libs
export TERSE_HOME=/path/to/.terse
```

**Makefile note:** 

- Explicit library build: `python3 compiler/tersec.py lib path/to/mod.te`
- Auto-link of `~/.terse/out/lib/...` on `use` is **off by default**. Enable with `TERSE_AUTOLIB=1` if you want imports to prefer a fresh `module.o` over inlining.


## Stranger-friendly

```bash
python3 compiler/tersec.py build src/hi.te && ~/.terse/out/hi

or 

make run.hi
```

Try the following:

| File | Shows |
|------|--------|
| `src/hi.te` | smallest `go` + `pr` |
| `src/fmt.te` | string `+` and `fmt(...)` |
| `src/quickstart.te` | list, `lp`, `fn`, `fmt` |

## Features

| Feature | Description |
|---------|-------------|
| Primitives | `int, long, chr, bool, dbl, flt, str ...` |
| Variables | `var/val` |
| Constants | `fix`|
| Enums | `en` |
| Arrays | `a[]`|
| Lists | `[]` |
| Maps |`{x:y}`|
| Struct | `rec` |
| Traits | `tr`|
| Loops | `lp` list or indexes |
| Conditions | `if/else` |
| Matching | `if "match" => ` |
| High order functions | pass functions around |
| Lambda | `\|x\| fn(x)`, closures todo|
| Pipes | see below |
| Tuples | todo |
| Generics | `[T]`, qualified todo |
| Exceptions | `err` todo |


### Primitives

Canonical names only (no aliases):

| Name | Meaning |
|------|---------|
| `bool` | boolean |
| `str` | string |
| `chr` | 8-bit signed |
| `byte` | 8-bit unsigned |
| `int` | 32-bit signed |
| `long` | 64-bit signed (**default** integer) |
| `flt` | 32-bit float |
| `dbl` | 64-bit float (**default** float literal) |

```terse
fn add(a: long, b: long) -> long = a + b
var xs: [long] = [1, 2, 3]
var m: {str: long} = {:}
```

### Pipe operator `|>`

`|>` is left-to-right function application (same idea as Elixir / F#). It rewrites at parse time — there is no special runtime opcode.

```terse
xs |> map(double) |> sum()
```

desugars to:

```terse
sum(map(xs, double))
```


Built-ins like `map` expect `(collection, fn)`; piping puts the collection in the first slot, which is why `xs |> map(double)` works.

## Library packages (`lib/`)


Optional libraries sit next to the compiler tree. Dots in `use` map to path
segments under `lib/` or `src/`:

```text
lib/math.te           →  use math          →  math.fact(5)
lib/calc/math.te      →  use calc.math     →  math.abs(x)   (alias = last segment)
lib/cnx/http.te       →  use cnx.http      →  http.srv(...)
lib/std/tst.te        →  use std.tst       →  tst.eq(...)
src/arith.te          →  use arith         →  app modules
src/usage/util.te     →  use usage.util    →  util.*
```

```terse
use std.tst
use calc.math

fn t_fact5() {
  tst.eq(math.fact(5), 120)
}
```

**General rule:** `use a.b.c` resolves to the first existing file among:

1. Next to the importing file: `a/b/c.te`
2. Project `lib/a/b/c.te` (optional packages)
3. Project `src/a/b/c.te` (app modules)
4. Project root `a/b/c.te`

The import alias is the **last** path segment (`use calc.math` → `math`), so calls look like `math.fact(...)`. In `tst/` sources, public names are also available unqualified (`fact(5)`).

- **`pub`** functions are the public API of a package  
- No registry yet — packages are files under `lib/` / `src/`  
- Precompile: `python3 compiler/tersec.py lib lib/calc/math.te` → `~/.terse/out/lib/...`


| Libs | Function |
| -----| ---------|
| std.io  | file i/o |
| std.out | pr/*con?* - assumed, no use needed |
| lib.tst | testing |
| lib.http | http *client*/server |
| lib.db | todo, *plugin* mechanism |
| lib.msg | *todo* |
| lib.ai | *todo* |
| lib.maths | *todo*, rnd |
| lib.process | *todo*, env, calls |
| lib.loom | concurrency *todo* |


## Language Spec

See [spec/TERSE_BNF.md](spec/TERSE_BNF.md) and [spec/SPEC.md](spec/SPEC.md) for the full language specification.

## Compiler Status (0.1)

- Built in print out
- Basic arithmetic
- If else

## Compiler Status (0.2)

The reference compiler (`compiler/tersec.py`) implements:

- Lexer, recursive-descent parser, minimal type checker
- C code generation + gcc/clang backend → native binary
- Integers (`long`/`int`/`chr`/`byte`), booleans, arithmetic & comparisons
- `if` expressions, `let` bindings, blocks
- Named functions + recursion
- **Higher-order functions**: pass functions as values, simple lambdas (`|x| x*2`)
- Function pointers under the hood (no environment capture yet)
- Text file reads and writes through `std.io`

Not yet implemented (but specified):

- Full closures with captures
- Records / structs / pattern matching
- Generics, ownership system, selective imports, and visibility modifiers


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
- **Pattern matching**: `if` / `match` arms
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


## TODO: Native Compiler Parity

- [x] Generalize function declarations and calls: multiple functions, arbitrary
  parameter/argument lists, optional `long`/`bool` parameter and return
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


## TODO

- tc -> native terse compiler
- tp -> package manager and processor
  - tp get <module:version> (from github?)
  - tp bld 
  - tp tst

> 
> Now you really can't get more `terse` than that, can you?
> 

## License

MIT (for this reference implementation)
