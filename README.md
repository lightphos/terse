# Terse

A succinct language that compiles to native binaries, with structures, interfaces, first-class higher-order functions, and (specified) support for REST APIs and databases.

## Quick Start

> Requires python3

### CLI Run
```bash
# Build program in example directory to a binary
make terse.hello dir=src
./output/hello          # prints hello world
```
### VS Code Support
```bash
make vscode-terse
make vconde-install
```
In vscode ide, reload window:

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
```

## Language Spec

See [docs/SPEC.md](docs/SPEC.md) for the full language specification.

## Compiler Status (0.1beta)

The reference compiler (`compiler/tersec.py`) implements:

- Lexer, recursive-descent parser, minimal type checker
- C code generation + gcc/clang backend → native binary
- Integers (`i64`), booleans, arithmetic & comparisons
- `if` expressions, `let` bindings, blocks
- Named functions + recursion
- **Higher-order functions**: pass functions as values, simple lambdas (`|x| x*2`)
- Function pointers under the hood (no environment capture yet)
- Text file reads and writes through `std.fs`
- Growable lists of records for AST-style node storage

Not yet implemented (but specified):

- Full closures with captures
- Strings beyond basic support
- Records / structs / pattern matching
- SQLite database runtime: `db.connect`, `db.exec`, `db.query`, and `db.query_one`
- Generics, ownership system, selective imports, and visibility modifiers

## Examples

| File | Description | Output |
|------|-------------|--------|
| `src/hello.te` | Basic arithmetic | 42 |
| `src/fact.te` | Recursion | 3628800 |
| `src/hof.te` | Higher-order + lambda | 149 |
| `src/iflet.te` | if + let | 59 |

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
source file, builds a typed token/node arena, parses integer arithmetic,
emits C, and invokes GCC. The root `tc` launcher quietly bootstraps
the Terse compiler with the reference compiler when needed:

```sh
# Build the stage-one tc executable explicitly (optional; ./tc does this as needed).
make tcc

# Compile and run a source file through tc.
./tc compiler/tc_smoke.te
output/tc_smoke
./tc compiler/tc_smoke.te -o output/tc-smoke

# Run the Terse-language regression suite.
make tc-test
```

`compiler/t_tc.te` ports the language-level regression cases from
`compiler/test_compiler.py`. Python-only checks for subprocess compilation,
negative compiler diagnostics, and live HTTP orchestration remain in the
Python test suite.

The Terse frontend is an early slice, not yet a replacement for the Python
compiler. It scans to the first `=` or `{` and parses one expression containing
decimal integer literals, parentheses, and `+`, `-`, `*`, `/`, and `%`. It does
not yet parse declarations or verify that the expression belongs to a go entrypoint.
For other syntax, `tc` reports that it is using the reference compiler, which
keeps the command usable while the self-hosted frontend gains coverage.

## License

MIT (for this reference implementation)


## 0.1beta features

- Strings: `"hi"`, `"a" + "b"`, `len(s)`, `s[i]`
- Lists: `[1, 2, 3]`, `len(xs)`, `xs[i]`, `pr(xs)`
- `pr(x)` for ints, strings, lists
- See `src/io.te`
