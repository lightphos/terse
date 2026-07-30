# Terse

A succinct language that compiles to native binaries, with first-class higher-order functions, and (specified) support for REST APIs and databases.

## Quick Start

```bash
# Build a program to a binary
python3 compiler/tersec.py build examples/hello.terse -o hello
./hello          # prints 42

# Or compile + run in one step
python3 compiler/tersec.py run examples/fact.terse

# Type-check only
python3 compiler/tersec.py check examples/hof.terse
```

## Language Spec

See [docs/SPEC.md](docs/SPEC.md) for the full language specification.

## Compiler Status (v0.1)

The reference compiler (`compiler/tersec.py`) implements:

- Lexer, recursive-descent parser, minimal type checker
- C code generation + gcc/clang backend → native binary
- Integers (`i64`), booleans, arithmetic & comparisons
- `if` expressions, `let` bindings, blocks
- Named functions + recursion
- **Higher-order functions**: pass functions as values, simple lambdas (`|x| x*2`)
- Function pointers under the hood (no environment capture yet)

Not yet implemented (but specified):

- Full closures with captures
- Strings beyond basic support
- Records / structs / pattern matching
- Real `http.serve` and `db.query` (stubs planned)
- Generics, modules, ownership system

## Examples

| File | Description | Output |
|------|-------------|--------|
| `examples/hello.terse` | Basic arithmetic | 42 |
| `examples/fact.terse` | Recursion | 3628800 |
| `examples/hof.terse` | Higher-order + lambda | 149 |
| `examples/iflet.terse` | if + let | 59 |

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

Future backends: direct LLVM IR.

## License

MIT (for this reference implementation)


## v0.2 features

- Strings: `"hi"`, `"a" + "b"`, `len(s)`, `s[i]`
- Lists: `[1, 2, 3]`, `len(xs)`, `xs[i]`, `print(xs)`
- `print(x)` for ints, strings, lists
- See `examples/io.terse`
